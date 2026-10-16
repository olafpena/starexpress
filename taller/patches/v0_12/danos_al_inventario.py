"""
La Orden Taller ya no lleva "Descripción de daños": los daños se registran en el
inventario. Lo que ya estaba capturado se agrega a las observaciones del inventario.
"""

import frappe

from taller.flujo import configuracion as conf


def execute():
    if not frappe.db.has_column(conf.DOCTYPE, "descripcion_danos"):
        return
    ordenes = frappe.db.sql("""
        select o.descripcion_danos, i.name inventario, i.observaciones
        from `tabOrden Taller` o join `tabInventario` i on i.name = o.inventario
        where ifnull(o.descripcion_danos, '') != ''
    """, as_dict=True)
    for o in ordenes:
        if o.descripcion_danos in (o.observaciones or ""):
            continue
        texto = "\n\n".join(filter(None, [o.observaciones, f"Daños (de la orden): {o.descripcion_danos}"]))
        frappe.db.set_value(conf.DOCTYPE_INVENTARIO, o.inventario, "observaciones", texto, update_modified=False)
