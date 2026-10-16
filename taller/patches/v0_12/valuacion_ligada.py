"""Las órdenes ligan su valuación desde que se crea (como el inventario): liga las valuaciones en borrador."""

import frappe


def execute():
    frappe.db.sql("""
        update `tabOrden Taller` o
        join `tabValuacion Taller` v on v.orden_taller = o.name and v.docstatus = 0
        set o.valuacion = v.name, o.valuacion_total = v.total
        where ifnull(o.valuacion, '') = ''
    """)
