"""
Se elimina el campo `agencia` de la Orden Taller: en el tipo Agencia quien paga es
el Cliente (la agencia) y el dueño del vehículo queda en el Vehículo.

Si la base todavía tiene la columna (Frappe no borra columnas al quitar campos),
las órdenes Agencia que la usaban pasan ese valor a `cliente`. El dueño anterior
queda como propietario del vehículo si éste no tenía uno.
"""

import frappe

from taller.patches.v0_3.clientes_y_documentos_erpnext import asegurar_cliente


def execute():
    if not frappe.db.has_column("Orden Taller", "agencia"):
        return

    ordenes = frappe.db.sql("""select name, cliente, agencia, vehiculo from `tabOrden Taller`
                               where tipo_flujo = 'Agencia' and ifnull(agencia, '') != ''""", as_dict=True)
    for orden in ordenes:
        agencia = orden.agencia
        if not frappe.db.exists("Customer", agencia):
            agencia = asegurar_cliente(agencia, "Agencia")
        if orden.vehiculo and orden.cliente and not frappe.db.get_value("Vehiculo Taller", orden.vehiculo, "cliente"):
            frappe.db.set_value("Vehiculo Taller", orden.vehiculo, "cliente", orden.cliente)
        frappe.db.set_value("Orden Taller", orden.name, {
            "cliente": agencia,
            "cliente_nombre": frappe.db.get_value("Customer", agencia, "customer_name"),
        }, update_modified=False)
