"""
Estatus de la orden: crea el catálogo Estatus Orden Taller (Activo, Inactivo,
Cancelado, Terminado) y asigna el estatus inicial a las órdenes existentes:
Activo, salvo las canceladas (Cancelado) y las ya cerradas (Terminado).
"""

import frappe

from taller.flujo import configuracion as conf


def execute():
    conf.instalar()

    # Corre una sola vez, al aparecer el campo: la columna nueva puede traer "Activo"
    # por omisión, así que se asigna a todas según su estado
    for orden in frappe.get_all(conf.DOCTYPE, fields=["name", "docstatus", "workflow_state"]):
        if orden.workflow_state == conf.ESTADO_CANCELADA:
            estatus = conf.ESTATUS_CANCELADO
        elif orden.docstatus == 1:
            estatus = conf.ESTATUS_TERMINADO
        else:
            estatus = conf.ESTATUS_ACTIVO
        frappe.db.set_value(conf.DOCTYPE, orden.name, conf.CAMPO_ESTATUS, estatus, update_modified=False)
