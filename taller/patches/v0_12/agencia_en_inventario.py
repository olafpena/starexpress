"""
La orden y el asesor de la agencia pasan de la Orden Taller (sección Agencia, que
se quitó) al inventario, en Firmas y conformidad.

  * Copia los valores que ya tenían las órdenes a su inventario, sin pisar lo capturado.
  * La regla "Agencia: orden de la agencia antes de Carrocería" ahora lee el inventario.
  * Los Link a Employee muestran el nombre del empleado (columna Empleado de los pasos).
"""

import frappe

from taller.erp.documentos import crear_propiedades
from taller.flujo import configuracion as conf

CAMPOS = ("orden_agencia", "asesor_agencia")


def execute():
    for campo in CAMPOS:
        if not frappe.db.has_column(conf.DOCTYPE, campo):
            continue
        frappe.db.sql(f"""
            update `tabInventario` i
            join `tabOrden Taller` o on o.inventario = i.name
            set i.{campo} = o.{campo}
            where ifnull(o.{campo}, '') != '' and ifnull(i.{campo}, '') = ''
        """)

    frappe.db.set_value(conf.DOCTYPE_REGLAS, {"condicion": "doc.orden_agencia"}, {
        "condicion": conf.CONDICION_ORDEN_AGENCIA,
        "mensaje": "Captura en el inventario el número de orden de la agencia antes de pasar a Carrocería.",
    })
    crear_propiedades()
