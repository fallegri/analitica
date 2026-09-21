"""Helper compartido entre reglas de tabla que necesitan ubicar columnas por rol.

Los nombres de campo no se conocen de antemano (dependen del archivo que suba
cada usuario), así que estas listas son vocabulario genérico por rol —no
nombres exactos esperados— y quedan cortas a propósito para que sea fácil
sumar sinónimos si aparecen en datasets reales."""

CODE_HINTS = ["cod", "id", "sku", "folio", "referencia", "clave", "key"]
PRICE_HINTS = ["precio", "monto", "price", "importe", "valor", "total"]
PRODUCT_HINTS = ["prod", "desc", "product", "articulo", "artículo", "item", "ítem"]


def find_col(columns, hints: list[str]) -> str | None:
    for c in columns:
        low = str(c).lower()
        if any(h in low for h in hints):
            return c
    return None
