"""
El vehículo pasa de la Orden Taller (sección Vehículo, que se quitó) al inventario.

  * Copia el vehículo que ya tenían las órdenes a su inventario, sin pisar lo capturado.
    La orden conserva el vehículo y las placas (solo lectura) para su lista y filtros.
  * La regla "Recepción: identificar el vehículo" ahora lee el inventario.
"""

import frappe

from taller.flujo import configuracion as conf

CAMPOS = ("vehiculo", "marca", "modelo", "anio", "color", "placas", "vin")


def execute():
    for campo in CAMPOS:
        if not frappe.db.has_column(conf.DOCTYPE, campo):
            continue
        frappe.db.sql(f"""
            update `tabInventario` i
            join `tabOrden Taller` o on o.inventario = i.name
            set i.{campo} = o.{campo}
            where ifnull(o.{campo}, '') not in ('', '0') and ifnull(i.{campo}, '') in ('', '0')
        """)

    # Lo capturado en el inventario manda: la copia de la orden queda igual a su inventario
    frappe.db.sql("""
        update `tabOrden Taller` o
        join `tabInventario` i on o.inventario = i.name
        set o.vehiculo = i.vehiculo, o.placas = i.placas
        where ifnull(i.vehiculo, '') != '' or ifnull(i.placas, '') != ''
    """)

    frappe.db.set_value(conf.DOCTYPE_REGLAS, {"condicion": "doc.placas or doc.vin"}, {
        "condicion": conf.CONDICION_VEHICULO,
        "mensaje": "Registra en el inventario las placas o el VIN antes de completar la recepción.",
    })
