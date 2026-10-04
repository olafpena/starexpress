"""
La configuración de la compañía guardaba "Desactivar total redondeado" con
set_single_value, que no ejecuta Global Defaults.on_update; el valor quedaba
guardado pero cotizaciones, órdenes y facturas seguían redondeando al peso.
Guardar Global Defaults aplica el valor predeterminado en esos documentos.
"""

import frappe


def execute():
    globales = frappe.get_single("Global Defaults")
    if globales.disable_rounded_total:
        globales.save(ignore_permissions=True)
