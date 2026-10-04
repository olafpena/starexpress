"""Crea el proyecto de costeo de cada Orden Taller existente y recalcula sus montos."""

import frappe

from taller.erp.costeo import crear_proyecto
from taller.erp.documentos import actualizar_orden


def execute():
    for nombre in frappe.get_all("Orden Taller", filters={"docstatus": ["<", 2]}, pluck="name"):
        doc = frappe.get_doc("Orden Taller", nombre)
        crear_proyecto(doc)
        actualizar_orden(nombre)
