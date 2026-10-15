"""Prueba las reglas de reparto con datos inventados (sin información real).

Ejecutar:  python tests/test_motor.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import procesar_mes as pm  # noqa: E402

ING = "7070011001"   # INGRESOS RULETA AMERICANA (clase INGRESOS)
PERS = "6400000000"  # SUELDOS Y SALARIOS (costo fijo, gasto de personal)
LUZ = "6282000000"   # ELECTRICIDAD (costo fijo, no personal)


def fila(ceco, cuenta, valor):
    return {pm.COL_PERIODO: 9, pm.COL_EJERCICIO: 2026, pm.COL_CECO: f"AXCZR{ceco}",
            pm.COL_CUENTA: cuenta, pm.COL_VALOR: valor}


def test_repartos():
    filas = [
        # Ingresos (SAP: crédito = negativo)
        fila("01100", ING, -1000),   # Mesas
        fila("01200", ING, -3000),   # Slots
        fila("01300", ING, -500),    # Poker torneos
        fila("01301", ING, -500),    # CAP -> suma en Poker
        fila("01400", ING, -1000),   # Bingo
        fila("20100", ING, -200),    # Hotel
        fila("60000", ING, -50),     # Shows (Otros Negocios)
        # Costos
        fila("01000", PERS, 600),    # Casino Genérico -> Slots 3/4, Mesas 1/4
        fila("90000", LUZ, 600),     # Estructura
        fila("90001", LUZ, 600),     # Estructura
        fila("61000", LUZ, 10),      # Disco -> excluido
        fila("80000", LUZ, 5),       # Otros turismo -> sin asignar
        fila("01200", LUZ, 100),     # costo directo Slots
    ]
    ceco, cuentas = pm.cargar_maestros()
    df = pm.clasificar(pd.DataFrame(filas), ceco, cuentas)
    res, ctrl = pm.calcular_mes(df)
    sub = res["Casino"]["subunidades"]

    # Poker suma 01300 + 01301
    assert sub["Poker"]["ingresos"] == 1000
    # Casino Genérico 600 -> Slots 450 / Mesas 150 (en personal)
    assert abs(sub["Slots"]["personal"] - 450) < 1e-9
    assert abs(sub["Mesas"]["personal"] - 150) < 1e-9
    # Estructura 1200 por ingresos: base 6000 -> Slots 50%, Mesas 1/6, Poker 1/6, Bingo 1/6
    assert abs(sub["Slots"]["estructura"] - 600) < 1e-9
    assert abs(sub["Mesas"]["estructura"] - 200) < 1e-9
    assert abs(sub["Poker"]["estructura"] - 200) < 1e-9
    assert abs(sub["Bingo"]["estructura"] - 200) < 1e-9
    # EBITDA Slots = 3000 - 100 - 450 ; final = - 600
    assert abs(sub["Slots"]["ebitda"] - (3000 - 100 - 450)) < 1e-9
    assert abs(sub["Slots"]["ebitda_final"] - (3000 - 100 - 450 - 600)) < 1e-9
    # Casino Total = suma de las cuatro
    assert abs(res["Casino"]["total"]["ingresos"] - 6000) < 1e-9
    assert abs(res["Casino"]["total"]["estructura"] - 1200) < 1e-9
    # Otras unidades no absorben estructura
    assert res["Hotel"]["total"]["estructura"] == 0
    assert res["Otros Negocios"]["subunidades"]["Shows"]["ingresos"] == 50
    # Disco excluido y 80000 sin asignar, informados
    assert ctrl["excluido_disco"]["lineas"] == 1
    assert ctrl["sin_asignar"]["ceco"] == ["80000"]
    # Conciliación cierra
    assert abs(ctrl["conciliacion"]["diferencia"]) < 1e-6, ctrl["conciliacion"]


def test_cuenta_sin_mapeo():
    filas = [fila("01200", "9999999999", 100), fila("01200", ING, -500)]
    ceco, cuentas = pm.cargar_maestros()
    df = pm.clasificar(pd.DataFrame(filas), ceco, cuentas)
    res, ctrl = pm.calcular_mes(df)
    assert ctrl["cuentas_sin_mapeo"]["cuentas"] == ["9999999999"]
    assert res["Casino"]["subunidades"]["Slots"]["ingresos"] == 500


if __name__ == "__main__":
    test_repartos()
    test_cuenta_sin_mapeo()
    print("OK: todas las pruebas pasaron")
