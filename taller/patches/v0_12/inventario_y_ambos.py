"""
Inventario de la unidad, tipo de orden Ambos y fotos.

  * Regenera el workflow con la secuencia de Ambos (conserva las condiciones
    escritas a mano), crea las 19 zonas de carrocería y los permisos nuevos
    (Inventario, Zona de Carroceria y la sección Costeo con nivel 1).
  * Crea el inventario de cada orden que no tiene uno, con los accesorios y
    documentos de la hoja precargados. Las órdenes que aún están en Recolección o
    Recepción deberán enviarlo para completar ese paso.
"""

import frappe

from taller.flujo import configuracion as conf
from taller.taller.doctype.inventario.inventario import crear_inventario


def execute():
    conf.instalar(reconstruir=True)

    for nombre in frappe.get_all(conf.DOCTYPE, filters={"inventario": ["in", ["", None]]}, pluck="name"):
        orden = frappe.get_doc(conf.DOCTYPE, nombre)
        crear_inventario(orden)
