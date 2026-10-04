"""
Flujo de Mecánica: pasos nuevos (Diagnóstico, Cotización, Autorización del cliente,
Refacciones, Reparación, Hallazgo adicional, Control de calidad y ruta) que comparten
Recepción, Lavado, Entrega, Cobro y Facturación con Hojalatería y Pintura.

  * Las reglas que solo aplican a Hojalatería y Pintura quedan con ese tipo de orden
    (la de valuación en Recepción bloquearía a Mecánica).
  * Se reconstruye el workflow (roles Mecánico y Almacenista, estados y transiciones)
    y se crean las reglas de Mecánica.
  * Activity Type con costo por hora para los pasos nuevos.
"""

import frappe

from taller.erp.configuracion_empresa import COSTO_HORA, crear_actividad
from taller.flujo import configuracion as conf


def execute():
    for regla in conf.REGLAS_EJEMPLO:
        if regla.get("tipo_orden") == conf.TIPO_ORDEN_FLUJO:
            frappe.db.set_value(conf.DOCTYPE_REGLAS, {"descripcion": regla["descripcion"],
                                                      "tipo_orden": ["in", ["", "Todos"]]},
                                "tipo_orden", conf.TIPO_ORDEN_FLUJO)

    conf.instalar(reconstruir=True)

    for paso in conf.SECUENCIA_MECANICA:
        if paso in COSTO_HORA:
            crear_actividad(paso, COSTO_HORA[paso])
