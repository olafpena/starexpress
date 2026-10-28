from frappe import _


def get_data():
    """Pestaña Conexiones: documentos que apuntan a la orden (campo orden_taller) y el proyecto."""
    return {
        "fieldname": "orden_taller",
        "internal_links": {"Project": "proyecto"},
        "transactions": [
            {"label": _("Unidad"), "items": ["Inventario", "Valuacion Taller"]},
            {"label": _("Ventas"), "items": ["Quotation", "Sales Order", "Sales Invoice"]},
            {"label": _("Costeo"), "items": ["Project"]},
        ],
    }
