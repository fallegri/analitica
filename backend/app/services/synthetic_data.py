"""
Generador de datos sintéticos para probar el pipeline completo sin depender
de un archivo real. Cuatro variantes, cada una pensada para ejercitar un
módulo distinto del sistema:

- "ventas_series_tiempo": varias gestiones (años fiscales) con tendencia y
  estacionalidad real, para probar el módulo de Proyección.
- "datos_sucios_eda": con cada problema que el motor de calidad sabe
  detectar (nulos, negativos, atípicos, codificación errónea, fechas
  mezcladas, moneda inconsistente, abreviaturas de ciudad, categorías
  inconsistentes, numérico-como-texto, duplicados).
- "esquema_estrella": dos tablas de dimensión (productos, clientes) + una
  de hechos (ventas) con relaciones reales, para probar Detección de
  Esquema.
- "inventario_generico": un dataset de uso general, mayormente limpio, de
  un dominio distinto (inventario de almacén) para probar diccionario e
  insights sin el sesgo de los otros tres escenarios.

Todas devuelven un dict {nombre_hoja: DataFrame} — para las variantes de
una sola tabla es un dict de un solo elemento, así el llamador (router +
xlsx writer) no necesita tratarlas distinto.
"""
import random
import string

import numpy as np
import pandas as pd

_PRODUCTOS = ["Coca Cola 2L", "Pepsi 2L", "Sprite 2L", "Fanta 2L", "Agua Vital 2L", "Jugo Del Valle 1L"]
_CATEGORIAS = ["Bebida gaseosa", "Bebida gaseosa", "Bebida gaseosa", "Bebida gaseosa", "Agua", "Jugo"]
_CANALES = ["Tienda", "Online", "Mayorista"]
_CIUDADES_OK = ["Santa Cruz", "La Paz", "Cochabamba", "Sucre", "Tarija"]
_CIUDADES_VARIANTES = ["Santa Cruz", "SCZ", "santa cruz", "La Paz", "LP", "Cochabamba", "CBB"]
_CATEGORIAS_SUCIAS = ["Bebida", "bebida", "BEBIDA", "Bebidas", "Alimento", "alimento"]
_MOJIBAKE_WORDS = ["PromociÃ³n", "DescripciÃ³n aÃ±adida", "ArtÃ­culo especial"]


def _sheets(df_or_dict) -> dict[str, pd.DataFrame]:
    if isinstance(df_or_dict, dict):
        return df_or_dict
    return {"Datos": df_or_dict}


def generate_ventas_series_tiempo(n_records: int = 1200, gestiones: int = 3, seed: int | None = None) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=gestiones)
    total_days = gestiones * 365
    day_offsets = rng.integers(0, total_days, size=n_records)
    dates = [start + pd.Timedelta(days=int(d)) for d in day_offsets]

    n_prod = len(_PRODUCTOS)
    prod_idx = rng.integers(0, n_prod, size=n_records)

    rows = []
    for i in range(n_records):
        d = dates[i]
        p_idx = prod_idx[i]
        # tendencia: crece con el tiempo transcurrido; estacionalidad: pico en nov-dic-ene
        days_elapsed = (d - start).days
        trend = 1.0 + (days_elapsed / total_days) * 0.6  # hasta +60% al final del período
        month_factor = 1.4 if d.month in (11, 12, 1) else (0.8 if d.month in (2, 3) else 1.0)
        base_qty = rng.integers(5, 30)
        cantidad = max(1, int(base_qty * trend * month_factor * rng.uniform(0.85, 1.15)))
        precio_unitario = round(rng.uniform(8, 25), 2)
        monto_total = round(cantidad * precio_unitario, 2)
        rows.append({
            "fecha": d.strftime("%d/%m/%Y"),
            "gestion": d.year,
            "producto": _PRODUCTOS[p_idx],
            "categoria": _CATEGORIAS[p_idx],
            "canal_venta": random.choice(_CANALES),
            "ciudad": random.choice(_CIUDADES_OK),
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
            "monto_total": monto_total,
        })

    return _sheets(pd.DataFrame(rows).sort_values("fecha").reset_index(drop=True))


def generate_datos_sucios_eda(n_records: int = 800, seed: int | None = None) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    rows = []
    date_formats = ["%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"]
    currency_prefixes = ["Bs.", "USD", "$", ""]

    for i in range(n_records):
        base_date = pd.Timestamp("2023-01-01") + pd.Timedelta(days=int(rng.integers(0, 700)))
        fmt = random.choice(date_formats)
        fecha_str = base_date.strftime(fmt)

        cantidad = int(rng.integers(1, 50))
        if rng.random() < 0.03:  # ~3% valores negativos (error de captura)
            cantidad = -cantidad
        if rng.random() < 0.01:  # ~1% atípicos extremos
            cantidad = cantidad * 50

        precio = round(rng.uniform(10, 200), 2)
        monto_texto = f"{random.choice(currency_prefixes)}{precio}".strip()
        if rng.random() < 0.1:  # ~10% como texto con separador de miles
            monto_texto = f"{precio:,.2f}"

        categoria = random.choice(_CATEGORIAS_SUCIAS)
        ciudad = random.choice(_CIUDADES_VARIANTES)
        producto = random.choice(_PRODUCTOS)
        if rng.random() < 0.02:  # ~2% con caracteres mal codificados
            producto = random.choice(_MOJIBAKE_WORDS)

        row = {
            "fec_registro": fecha_str,
            "cod_prod": f"P{(i % 30):03d}",
            "desc_prod": producto,
            "categoria": categoria,
            "ciudad": ciudad,
            "cantidad": cantidad,
            "monto": monto_texto,
        }

        # ~5% de nulos distribuidos en columnas no clave
        if rng.random() < 0.05:
            row[random.choice(["desc_prod", "categoria", "ciudad", "monto"])] = None

        rows.append(row)

    df = pd.DataFrame(rows)
    # ~2% de filas completamente duplicadas
    n_dupes = max(1, int(len(df) * 0.02))
    dupes = df.sample(n=n_dupes, random_state=seed).copy()
    df = pd.concat([df, dupes], ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)

    return _sheets(df)


def generate_esquema_estrella(n_records: int = 1500, n_productos: int = 40, n_clientes: int = 150, seed: int | None = None) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)

    productos = pd.DataFrame({
        "cod_prod": [f"P{i:03d}" for i in range(n_productos)],
        "nombre_producto": [f"{random.choice(_PRODUCTOS)} #{i}" for i in range(n_productos)],
        "categoria": [random.choice(list(set(_CATEGORIAS))) for _ in range(n_productos)],
        "precio_lista": [round(rng.uniform(8, 30), 2) for _ in range(n_productos)],
    })

    clientes = pd.DataFrame({
        "cod_cliente": [f"C{i:04d}" for i in range(n_clientes)],
        "nombre_cliente": [f"Cliente {i}" for i in range(n_clientes)],
        "ciudad": [random.choice(_CIUDADES_OK) for _ in range(n_clientes)],
        "segmento": [random.choice(["Minorista", "Mayorista", "Institucional"]) for _ in range(n_clientes)],
    })

    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=1)
    ventas_rows = []
    for i in range(n_records):
        d = start + pd.Timedelta(days=int(rng.integers(0, 365)))
        prod = productos.iloc[int(rng.integers(0, n_productos))]
        cli = clientes.iloc[int(rng.integers(0, n_clientes))]
        cantidad = int(rng.integers(1, 20))
        ventas_rows.append({
            "id_venta": i + 1,
            "fecha": d.strftime("%d/%m/%Y"),
            "cod_prod": prod["cod_prod"],
            "cod_cliente": cli["cod_cliente"],
            "cantidad": cantidad,
            "monto_total": round(cantidad * prod["precio_lista"], 2),
        })
    ventas = pd.DataFrame(ventas_rows)

    return {"Productos": productos, "Clientes": clientes, "Ventas": ventas}


def generate_inventario_generico(n_records: int = 800, seed: int | None = None) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    categorias = ["Electrónica", "Papelería", "Limpieza", "Ferretería", "Oficina"]
    proveedores = ["Distribuidora Andina", "Import Express", "Suministros del Sur", "Comercial Boliviana"]
    almacenes = ["Almacén Central", "Almacén Norte", "Almacén Sur"]

    rows = []
    start = pd.Timestamp.today().normalize() - pd.DateOffset(days=365)
    for i in range(n_records):
        cat = random.choice(categorias)
        ingreso = start + pd.Timedelta(days=int(rng.integers(0, 365)))
        rows.append({
            "sku": f"SKU-{i:05d}",
            "nombre_producto": f"{cat[:4]}-Item-{i}",
            "categoria": cat,
            "cantidad_stock": int(rng.integers(0, 500)),
            "precio_unitario": round(rng.uniform(5, 800), 2),
            "proveedor": random.choice(proveedores),
            "fecha_ultimo_ingreso": ingreso.strftime("%d/%m/%Y"),
            "ubicacion_almacen": random.choice(almacenes),
        })

    return _sheets(pd.DataFrame(rows))


VARIANTS = {
    "ventas_series_tiempo": {
        "label": "Ventas — serie de tiempo (para Proyección)",
        "description": "Varias gestiones con tendencia y estacionalidad real. Ideal para probar el módulo de Proyección.",
        "generator": generate_ventas_series_tiempo,
        "default_n": 1200,
    },
    "datos_sucios_eda": {
        "label": "Datos sucios (para Calidad/EDA)",
        "description": "Nulos, negativos, atípicos, codificación errónea, fechas mezcladas, moneda inconsistente, ciudades sin uniformar, duplicados.",
        "generator": generate_datos_sucios_eda,
        "default_n": 800,
    },
    "esquema_estrella": {
        "label": "Esquema estrella (multi-tabla)",
        "description": "Productos + Clientes (dimensión) y Ventas (hecho) con relaciones reales. Ideal para Detección de Esquema.",
        "generator": generate_esquema_estrella,
        "default_n": 1500,
    },
    "inventario_generico": {
        "label": "Inventario genérico (uso general)",
        "description": "Dataset de inventario de almacén, mayormente limpio, para probar diccionario e insights sin sesgo de los otros escenarios.",
        "generator": generate_inventario_generico,
        "default_n": 800,
    },
}


def generate_variant(variant_id: str, n_records: int | None = None, seed: int | None = None) -> dict[str, pd.DataFrame]:
    if variant_id not in VARIANTS:
        raise ValueError(f"Variante desconocida: {variant_id}")
    spec = VARIANTS[variant_id]
    n = n_records or spec["default_n"]
    return spec["generator"](n, seed=seed)
