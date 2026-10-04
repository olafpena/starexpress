"""
Liga la Orden Taller con ERPNext:

  * campos `orden_taller` en Cotización, Orden de venta y Factura de venta,
  * cliente, agencia y aseguradora pasan de texto a Customer,
  * vehículo como DocType propio (Vehiculo Taller),
  * la regla de Facturación pide facturas enviadas en lugar del folio a mano.
"""

import frappe

from taller.erp.documentos import actualizar_orden
from taller.flujo import configuracion as conf

REGLA_ANTERIOR = {"descripcion": "Facturación: folio fiscal", "condicion": "doc.folio_factura"}
REGLA_NUEVA = next(r for r in conf.REGLAS_EJEMPLO if r["condicion"] == "doc.facturado")


def execute():
    regla = frappe.db.get_value(conf.DOCTYPE_REGLAS, REGLA_ANTERIOR, "name")
    if regla:
        frappe.db.set_value(conf.DOCTYPE_REGLAS, regla, {
            "descripcion": REGLA_NUEVA["descripcion"],
            "condicion": REGLA_NUEVA["condicion"],
            "mensaje": REGLA_NUEVA["mensaje"],
        })

    conf.instalar()

    company = frappe.defaults.get_global_default("company")
    for orden in frappe.get_all(conf.DOCTYPE, fields=["name", "company", "cliente", "cliente_nombre",
                                                     "agencia", "aseguradora", "vehiculo", "placas",
                                                     "vin", "marca", "modelo", "anio", "color"]):
        cambios = {}
        if not orden.company and company:
            cambios["company"] = company
        if not orden.cliente and orden.cliente_nombre:
            cambios["cliente"] = asegurar_cliente(orden.cliente_nombre, "Particular")
        for campo, grupo in (("agencia", "Agencia"), ("aseguradora", "Aseguradora")):
            if orden.get(campo) and not frappe.db.exists("Customer", orden.get(campo)):
                cambios[campo] = asegurar_cliente(orden.get(campo), grupo)
        if not orden.vehiculo and (orden.placas or orden.vin):
            cambios["vehiculo"] = crear_vehiculo(orden, cambios.get("cliente") or orden.cliente)
        if cambios:
            frappe.db.set_value(conf.DOCTYPE, orden.name, cambios, update_modified=False)
        actualizar_orden(orden.name)


def asegurar_cliente(nombre, grupo):
    existente = frappe.db.get_value("Customer", {"customer_name": nombre})
    if existente:
        return existente
    if not frappe.db.exists("Customer Group", grupo):
        grupo = frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
    return frappe.get_doc({"doctype": "Customer", "customer_name": nombre, "customer_type": "Individual",
                           "customer_group": grupo}).insert(ignore_permissions=True).name


def crear_vehiculo(orden, cliente):
    return frappe.get_doc({
        "doctype": conf.DOCTYPE_VEHICULO, "cliente": cliente,
        **{c: orden.get(c) for c in ("placas", "vin", "marca", "modelo", "anio", "color")},
    }).insert(ignore_permissions=True).name
