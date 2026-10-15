"""
Antes de sincronizar: workflow_state vuelve a ser campo estándar de Orden Taller.

Al quitarlo del DocType (Form Builder), el Workflow lo recreó como Custom Field;
se borra ese Custom Field para que no choque con el campo del JSON. La columna de
la base de datos y sus valores se conservan.
"""

import frappe


def execute():
    for nombre in frappe.get_all("Custom Field", filters={"dt": "Orden Taller", "fieldname": "workflow_state"},
                                 pluck="name"):
        frappe.delete_doc("Custom Field", nombre, ignore_permissions=True, force=True)
