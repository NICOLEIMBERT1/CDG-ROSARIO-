#!/usr/bin/env python3
"""
procesar_mes.py - Toma la bajada contable (SAP) de un mes, la ordena por
unidad de negocio / rubro y la suma al acumulado del año.

Uso:
    python procesar_mes.py --bajada BAJADA.xlsx [--hoja NOMBRE]
                           [--anio 2026 --mes 9] [--ledgers 0L ZC]

Reglas (ver README.md):
  * Unidad de negocio  -> últimos 5 dígitos del centro de coste (config/ceco.json)
  * Ingresos / costos  -> CLASE de la cuenta (config/cuentas.csv)
  * Gasto de personal  -> CLASE_2 = GASTO DE PERSONAL
  * Casino Genérico (01000) se reparte entre Slots y Mesas según ingresos del período
  * Estructura (90000/90001) se reparte entre Slots, Mesas, Poker y Bingo según
    ingresos del período (después de repartir el Casino Genérico)
  * Disco se excluye; los centros sin regla quedan en "Sin asignar" (se informa)

Solo se leen las columnas necesarias. NO se guarda usuario, proveedor, texto
de asiento ni número de documento.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent
CFG_CECO = RAIZ / "config" / "ceco.json"
CFG_CUENTAS = RAIZ / "config" / "cuentas.csv"
ACUMULADO = RAIZ / "public" / "data" / "acumulado.json"

COL_PERIODO = "Período contable"
COL_EJERCICIO = "Ejercicio"
COL_CECO = "Centro de coste"
COL_CUENTA = "Cuenta de mayor"
COL_VALOR = "Valor de moneda de sociedad"
COL_LEDGER = "Ledger"
COL_MONEDA = "Clave de moneda de sociedad"
REQUERIDAS = [COL_PERIODO, COL_EJERCICIO, COL_CECO, COL_CUENTA, COL_VALOR]

SUBUNIDADES_CASINO = ["Slots", "Mesas", "Poker", "Bingo"]
METRICAS = ["ingresos", "costos_fijos", "costos_variables", "personal"]


# --------------------------------------------------------------------------
# Carga de maestros
# --------------------------------------------------------------------------
def cargar_maestros():
    with open(CFG_CECO, encoding="utf-8") as f:
        ceco = json.load(f)
    cuentas = pd.read_csv(CFG_CUENTAS, dtype=str).fillna("")
    cuentas["CUENTA"] = cuentas["CUENTA"].str.strip()
    cuentas = cuentas.drop_duplicates("CUENTA").set_index("CUENTA")
    return ceco, cuentas


# --------------------------------------------------------------------------
# Lectura y clasificación de líneas
# --------------------------------------------------------------------------
def leer_bajada(ruta, hoja=None):
    df = pd.read_excel(ruta, sheet_name=hoja or 0, dtype={COL_CUENTA: str, COL_CECO: str})
    faltan = [c for c in REQUERIDAS if c not in df.columns]
    if faltan:
        sys.exit(f"La bajada no tiene las columnas requeridas: {faltan}")
    cols = REQUERIDAS + [c for c in (COL_LEDGER, COL_MONEDA) if c in df.columns]
    return df[cols].copy()  # descarta usuarios, proveedores, textos, documentos


def clasificar(df, ceco_cfg, cuentas):
    """Agrega columnas: ceco5, unidad, subunidad, rol, y las 4 métricas (signo de gestión)."""
    df = df.copy()
    df[COL_CUENTA] = df[COL_CUENTA].astype(str).str.strip()
    df["ceco5"] = df[COL_CECO].astype(str).str.strip().str[-5:]

    def ubicar(c5):
        return ceco_cfg.get(c5, {"unidad": "Sin asignar", "subunidad": f"CECO sin regla ({c5})", "rol": "sin_asignar"})

    ub = df["ceco5"].map(ubicar)
    df["unidad"] = ub.map(lambda d: d["unidad"])
    df["subunidad"] = ub.map(lambda d: d["subunidad"])
    df["rol"] = ub.map(lambda d: d["rol"])

    df["clase"] = df[COL_CUENTA].map(cuentas["CLASE"]).fillna("")
    df["clase2"] = df[COL_CUENTA].map(cuentas["CLASE_2"]).fillna("")
    df["mapeada"] = df["clase"] != ""

    v = df[COL_VALOR].astype(float)
    df["ingresos"] = v.where(df["clase"] == "INGRESOS", 0.0) * -1  # SAP: crédito negativo -> ingreso positivo
    es_costo = df["clase"].isin(["COSTOS FIJOS", "COSTOS VARIABLES"])
    es_pers = es_costo & (df["clase2"] == "GASTO DE PERSONAL")
    df["personal"] = v.where(es_pers, 0.0)
    df["costos_fijos"] = v.where(es_costo & ~es_pers & (df["clase"] == "COSTOS FIJOS"), 0.0)
    df["costos_variables"] = v.where(es_costo & ~es_pers & (df["clase"] == "COSTOS VARIABLES"), 0.0)
    return df


# --------------------------------------------------------------------------
# Cálculo del resultado del mes
# --------------------------------------------------------------------------
def _suma(df):
    return {m: float(df[m].sum()) for m in METRICAS}


def calcular_mes(df):
    """df: líneas clasificadas de UN período. Devuelve (resultado, controles)."""
    ctrl = {"avisos": []}
    ok = df[df["mapeada"]]

    # 1) Directos por unidad / subunidad
    directos = ok[ok["rol"] == "directo"]
    subs = {}
    for (u, s), g in directos.groupby(["unidad", "subunidad"]):
        subs[(u, s)] = _suma(g)
    for s in SUBUNIDADES_CASINO:  # garantizar las 4 del casino aunque no tengan movimiento
        subs.setdefault(("Casino", s), {m: 0.0 for m in METRICAS})

    # 2) Casino Genérico (01000) -> Slots y Mesas según ingresos
    gen = ok[ok["rol"] == "generico_casino"]
    gen_tot = _suma(gen)
    ctrl["casino_generico"] = gen_tot
    if abs(gen_tot["ingresos"]) > 1:
        ctrl["avisos"].append("El centro 01000 (Casino Genérico) tiene ingresos; no se reparten, quedan en control.")
    base = subs[("Casino", "Slots")]["ingresos"] + subs[("Casino", "Mesas")]["ingresos"]
    gen_costos = sum(gen_tot[m] for m in METRICAS if m != "ingresos")
    if gen_costos != 0 and base <= 0:
        ctrl["avisos"].append("No se pudo repartir el Casino Genérico: ingresos de Slots+Mesas <= 0.")
        ctrl["casino_generico_sin_repartir"] = gen_costos
    else:
        for s in ("Slots", "Mesas"):
            pct = subs[("Casino", s)]["ingresos"] / base if base > 0 else 0.0
            for m in METRICAS:
                if m != "ingresos":
                    subs[("Casino", s)][m] += gen_tot[m] * pct
        ctrl["casino_generico_reparto"] = {
            s: (subs[("Casino", s)]["ingresos"] / base if base > 0 else 0.0) for s in ("Slots", "Mesas")
        }

    # 3) EBITDA (antes de estructura)
    for k, d in subs.items():
        d["costos"] = d["costos_fijos"] + d["costos_variables"]
        d["ebitda"] = d["ingresos"] - d["costos"] - d["personal"]
        d["estructura"] = 0.0

    # 4) Estructura -> Slots, Mesas, Poker, Bingo según ingresos
    est = ok[ok["rol"] == "estructura"]
    est_tot = _suma(est)
    est_monto = sum(est_tot[m] for m in METRICAS if m != "ingresos")
    if abs(est_tot["ingresos"]) > 1:
        ctrl["avisos"].append("Los centros de Estructura (90000/90001) tienen ingresos; no se reparten.")
    base_c = sum(subs[("Casino", s)]["ingresos"] for s in SUBUNIDADES_CASINO)
    ctrl["estructura_total"] = est_monto
    if est_monto != 0 and base_c <= 0:
        ctrl["avisos"].append("No se pudo repartir la Estructura: ingresos del Casino <= 0.")
        ctrl["estructura_sin_repartir"] = est_monto
    elif est_monto != 0:
        ctrl["estructura_reparto"] = {}
        for s in SUBUNIDADES_CASINO:
            pct = subs[("Casino", s)]["ingresos"] / base_c
            subs[("Casino", s)]["estructura"] = est_monto * pct
            ctrl["estructura_reparto"][s] = pct
    for d in subs.values():
        d["ebitda_final"] = d["ebitda"] - d["estructura"]

    # 5) Armado del resultado: subunidades, unidades y Casino Total
    resultado = {}
    for (u, s), d in sorted(subs.items()):
        resultado.setdefault(u, {"subunidades": {}})["subunidades"][s] = d
    for u, bloque in resultado.items():
        campos = METRICAS + ["costos", "ebitda", "estructura", "ebitda_final"]
        bloque["total"] = {c: sum(x[c] for x in bloque["subunidades"].values()) for c in campos}

    # 6) Controles
    excl = ok[ok["rol"] == "excluido"]
    ctrl["excluido_disco"] = {"lineas": int(len(excl)), "resultado": float((excl["ingresos"] - excl["costos_fijos"] - excl["costos_variables"] - excl["personal"]).sum())}
    if len(excl):
        ctrl["avisos"].append(f"Disco tiene {len(excl)} asientos; se excluyen del reporte.")
    sin = ok[ok["rol"] == "sin_asignar"]
    ctrl["sin_asignar"] = {
        "lineas": int(len(sin)),
        "resultado": float((sin["ingresos"] - sin["costos_fijos"] - sin["costos_variables"] - sin["personal"]).sum()),
        "ceco": sorted(sin["ceco5"].unique().tolist()),
    }
    if len(sin):
        ctrl["avisos"].append(f"{len(sin)} asientos en centros sin unidad asignada: {ctrl['sin_asignar']['ceco']}")
    nomap = df[~df["mapeada"]]
    ctrl["cuentas_sin_mapeo"] = {
        "lineas": int(len(nomap)),
        "importe_sap": float(nomap[COL_VALOR].astype(float).sum()),
        "cuentas": sorted(nomap[COL_CUENTA].unique().tolist()),
    }
    if len(nomap):
        ctrl["avisos"].append(f"{len(nomap)} asientos con cuenta sin mapear: {ctrl['cuentas_sin_mapeo']['cuentas']}")

    # Conciliación: resultado total de la bajada = unidades + estructura + generico sin repartir + excluidos + sin asignar
    total_bajada = float((ok["ingresos"] - ok["costos_fijos"] - ok["costos_variables"] - ok["personal"]).sum())
    suma_unidades = sum(b["total"]["ebitda_final"] for b in resultado.values())
    sin_repartir = -(ctrl.get("casino_generico_sin_repartir", 0.0) + ctrl.get("estructura_sin_repartir", 0.0))
    otros = ctrl["excluido_disco"]["resultado"] + ctrl["sin_asignar"]["resultado"]
    otros += gen_tot["ingresos"] + est_tot["ingresos"]  # ingresos en 01000/90000: no se reparten
    ctrl["conciliacion"] = {
        "resultado_bajada_mapeada": total_bajada,
        "resultado_unidades": suma_unidades,
        "diferencia": total_bajada - (suma_unidades + sin_repartir + otros),
    }
    if abs(ctrl["conciliacion"]["diferencia"]) > 1:
        ctrl["avisos"].append("La conciliación NO cierra: revisar.")
    return resultado, ctrl


def casino_total(resultado):
    """Casino Total = Slots + Mesas + Poker + Bingo (la unidad 'Casino' ya los contiene)."""
    return resultado.get("Casino", {}).get("total")


# --------------------------------------------------------------------------
# Acumulado
# --------------------------------------------------------------------------
def cargar_acumulado():
    if ACUMULADO.exists():
        with open(ACUMULADO, encoding="utf-8") as f:
            return json.load(f)
    return {"meta": {"moneda": "ARS", "criterio_signos": "ingresos y costos positivos"}, "meses": {}}


def recalcular_ytd(acum):
    """Suma mensual de cada año (la Estructura ya viene repartida mes a mes)."""
    ytd = {}
    for clave, mes in sorted(acum["meses"].items()):
        anio = clave[:4]
        y = ytd.setdefault(anio, {"hasta": clave, "unidades": {}})
        y["hasta"] = clave
        for u, bloque in mes["resultado"].items():
            yu = y["unidades"].setdefault(u, {"subunidades": {}, "total": {}})
            for s, d in bloque["subunidades"].items():
                ys = yu["subunidades"].setdefault(s, {})
                for k, val in d.items():
                    ys[k] = ys.get(k, 0.0) + val
            for k, val in bloque["total"].items():
                yu["total"][k] = yu["total"].get(k, 0.0) + val
    acum["acumulado_anual"] = ytd
    return acum


def guardar(acum):
    ACUMULADO.parent.mkdir(parents=True, exist_ok=True)
    acum["meta"]["actualizado"] = datetime.now().isoformat(timespec="seconds")
    with open(ACUMULADO, "w", encoding="utf-8") as f:
        json.dump(acum, f, ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bajada", required=True, help="Excel con la bajada SAP del mes")
    ap.add_argument("--hoja", default=None, help="Nombre de la hoja (por defecto, la primera)")
    ap.add_argument("--anio", type=int, default=None)
    ap.add_argument("--mes", type=int, default=None)
    ap.add_argument("--ledgers", nargs="*", default=None, help="Filtrar por ledger (ej. 0L). Por defecto, todos.")
    args = ap.parse_args(argv)

    ceco_cfg, cuentas = cargar_maestros()
    bruto = leer_bajada(args.bajada, args.hoja)

    ledger_tot = None
    if COL_LEDGER in bruto.columns:
        ledger_tot = bruto.groupby(COL_LEDGER)[COL_VALOR].agg(["count", "sum"]).round(2).to_dict("index")
        if args.ledgers:
            bruto = bruto[bruto[COL_LEDGER].isin(args.ledgers)]

    periodos = bruto[[COL_EJERCICIO, COL_PERIODO]].drop_duplicates().values.tolist()
    if args.anio and args.mes:
        bruto = bruto[(bruto[COL_EJERCICIO] == args.anio) & (bruto[COL_PERIODO] == args.mes)]
        periodos = [[args.anio, args.mes]]
    elif len(periodos) != 1:
        sys.exit(f"La bajada trae {len(periodos)} períodos {periodos}. Indicá --anio y --mes.")
    anio, mes = int(periodos[0][0]), int(periodos[0][1])
    clave = f"{anio}-{mes:02d}"

    df = clasificar(bruto, ceco_cfg, cuentas)
    resultado, ctrl = calcular_mes(df)
    if ledger_tot:
        ctrl["totales_por_ledger"] = ledger_tot
    if COL_MONEDA in df.columns and (df[COL_MONEDA] != "ARS").any():
        ctrl["avisos"].append("Hay importes en una moneda distinta de ARS en 'Clave de moneda de sociedad'.")

    acum = cargar_acumulado()
    reemplazo = clave in acum["meses"]
    acum["meses"][clave] = {"resultado": resultado, "controles": ctrl}
    acum["meses"] = dict(sorted(acum["meses"].items()))
    acum = recalcular_ytd(acum)
    guardar(acum)

    print(f"\nPeríodo {clave} {'(reemplazado)' if reemplazo else '(agregado)'} - {len(df)} asientos procesados")
    for u, b in resultado.items():
        t = b["total"]
        print(f"  {u:<15} ingresos {t['ingresos']/1e6:>12,.1f} M   EBITDA {t['ebitda']/1e6:>10,.1f} M   EBITDA final {t['ebitda_final']/1e6:>10,.1f} M")
    print("\nControles:")
    print(f"  Conciliación: diferencia = {ctrl['conciliacion']['diferencia']:,.2f}")
    for a in ctrl["avisos"]:
        print("  AVISO:", a)
    if not ctrl["avisos"]:
        print("  Sin avisos.")
    print(f"\nAcumulado guardado en {ACUMULADO}")
    return acum


if __name__ == "__main__":
    main()
