"""Llena los totales de horas estimadas y reales (debajo de la tabla de pasos) de las órdenes existentes."""

import frappe


def execute():
    frappe.db.sql("""
        update `tabOrden Taller` o
        join (select parent, sum(ifnull(horas_estimadas, 0)) est, sum(ifnull(horas_reales, 0)) rea
              from `tabPaso Orden Taller` where parenttype = 'Orden Taller' group by parent) p
          on p.parent = o.name
        set o.total_horas_estimadas = round(p.est, 2), o.total_horas_reales = round(p.rea, 2)
    """)
