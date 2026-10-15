# Reportes CDG – dashboard de resultados + motor de acumulado

Toma la bajada SAP de un mes, la ordena por unidad de negocio y rubro, y la suma
al acumulado del año (`public/data/acumulado.json`). El sitio de `public/` lee ese
archivo y muestra el dashboard.

```
reportes-cdg/
├── public/              ← lo único que Vercel publica
│   ├── index.html       ← dashboard (sin build)
│   └── data/acumulado.json
├── config/              ← cuentas.csv y ceco.json (NO se publican)
├── procesar_mes.py      ← motor mensual (NO se publica)
├── tests/
└── vercel.json
```

## Puesta en marcha en Vercel (una sola vez)

1. Crear un repositorio **privado** en GitHub y subir esta carpeta (el `.gitignore` ya excluye los Excel).
2. En Vercel: *Add New → Project → Import* el repo.
3. *Framework Preset*: **Other**. Sin *Build Command*. El *Output Directory* ya lo define `vercel.json` (`public`).
4. *Deploy*.
5. **Proteger el acceso**: *Settings → Deployment Protection* (la disponibilidad de cada
   opción depende del plan de Vercel). Son resultados internos: no dejar la URL abierta.

Para reemplazar el dashboard actual (`dashboardeconomico.vercel.app`), conectar este repo
a ese mismo proyecto de Vercel o apuntar el dominio al proyecto nuevo.

## Flujo mensual

1. Colocar la bajada del mes en una carpeta local (fuera del repo).
2. `python procesar_mes.py --bajada RUTA/bajada.xlsx [--hoja NOMBRE] [--ledgers 0L]`
3. Revisar el resumen y los **controles** que imprime.
4. Subir `public/data/acumulado.json` al repo (`git add`, `commit`, `push`) → Vercel republica solo.

Procesar de nuevo el mismo mes **reemplaza** ese mes, no lo duplica.
Si la bajada trae más de un período, indicar `--anio` y `--mes`.

## Unidades de negocio (por los últimos 5 dígitos del centro de coste)

| Unidad | Subunidades | Centros |
|---|---|---|
| Casino | Slots, Mesas, Poker, Bingo | 01200, 01100, 01300 + 01301, 01400 |
| Hotel | Alojamiento, AA&BB Hotel, Salones | 20xxx y 50xxx (según `config/ceco.json`) |
| AA&BB | locales del casino y genéricos | 3xxxx |
| Casino Online | Casino Online y Deportivas / Poker Online | 01001 + 01002 / 02300 |
| Parking | Cubierto, Descubierto, Genérico | 40xxx |
| Otros Negocios | Shows, Alquiler de Locales | 60000, 80100 |
| Disco | — | 61xxx → **excluida** |
| Estructura | — | 90000, 90001 → se reparte |

`Casino Total` = Slots + Mesas + Poker + Bingo.

## Reglas de cálculo

- **Ingresos**: cuentas con `CLASE = INGRESOS` (SAP los trae negativos; se invierte el signo).
- **Gasto de personal**: `CLASE_2 = GASTO DE PERSONAL`.
- **Costos fijos y variables**: el resto de las cuentas de costo, según `CLASE`.
- **EBITDA** = Ingresos − Costos fijos y variables − Gasto de personal.
- **Casino Genérico (01000)** se reparte entre Slots y Mesas según ingresos del período.
- **Estructura (90000, 90001)** se reparte entre Slots, Mesas, Poker y Bingo según
  ingresos del período, *después* de repartir el Casino Genérico.
- **EBITDA final** = EBITDA − Estructura asignada.
- El acumulado anual suma los meses ya repartidos (no se reparte de nuevo sobre el acumulado).

## Controles que informa cada corrida

- Conciliación: resultado total de la bajada vs. suma de unidades + excluidos + sin asignar.
- Asientos en centros **sin asignar** (hoy: 80000 Otros Turismo, y cualquier centro nuevo).
- Asientos de **Disco** (se excluyen, pero se avisa si tiene movimientos).
- Cuentas **sin mapear** (no entran al resultado hasta agregarlas a `config/cuentas.csv`).
- Totales por **ledger** (0L / ZC) de la bajada.

## Mantenimiento

- Cuenta nueva → agregar fila en `config/cuentas.csv` (con `CLASE` y `CLASE_2`).
- Centro de coste nuevo → agregar en `config/ceco.json` (`unidad`, `subunidad`, `rol`).
  Roles: `directo`, `generico_casino`, `estructura`, `excluido`, `sin_asignar`.
- Pruebas: `python tests/test_motor.py`

## Privacidad

El motor lee solo período, ejercicio, centro de coste, cuenta, importe, ledger y
moneda. No guarda usuarios, proveedores, textos de asiento ni números de documento.
No subir al repo la bajada original ni las hojas USUARIOS / DOCUMENTOS de la matriz.

## Comparativos del dashboard

- **vs 25**: se calcula solo si el acumulado tiene los mismos meses del año anterior
  (procesar también las bajadas de 2025). Si faltan meses, muestra "—".
- **vs Fc**: usa un bloque opcional `"forecast"` en `acumulado.json`, con la misma forma
  que `"meses"` (`"forecast": {"2026-09": {"resultado": {...}}}`). Si no existe, muestra "—".
- Los avisos naranjas del dashboard salen de los controles del motor (centros sin unidad,
  cuentas sin mapear, conciliación).
