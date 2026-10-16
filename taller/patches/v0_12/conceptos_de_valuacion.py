"""
Liga a su partida los conceptos que se copiaron de una valuación aprobada, para que
la orden ya no permita cambiarlos ni quitarlos.

Solo liga una orden si sus primeros conceptos coinciden exactamente (artículo, detalle,
cantidad y precio) con las partidas de su valuación, en el mismo orden en que se
copiaron. Si alguien ya los editó, la orden se queda sin ligar y sus conceptos siguen
siendo editables.
"""

import frappe
from frappe.utils import flt

from taller.flujo import configuracion as conf
from taller.taller.doctype.valuacion_taller.valuacion_taller import (
    CAMPOS_LIGADOS,
    concepto_de_partida,
    partidas_cobrables,
)


def execute():
    ordenes = frappe.get_all(conf.DOCTYPE, filters={"valuacion_aprobada": 1, "valuacion": ["is", "set"]},
                             fields=["name", "valuacion"])
    for orden in ordenes:
        val = frappe.get_doc("Valuacion Taller", orden.valuacion)
        if val.docstatus != 1:
            continue
        esperados = [concepto_de_partida(p) for p in partidas_cobrables(val)]
        filas = frappe.get_all("Concepto Orden Taller", filters={"parenttype": conf.DOCTYPE, "parent": orden.name},
                               fields=["name", "partida_valuacion", *CAMPOS_LIGADOS], order_by="idx")
        if not esperados or len(filas) < len(esperados) or any(f.partida_valuacion for f in filas):
            continue
        if all(coincide(f, e) for f, e in zip(filas, esperados)):
            for fila, esperado in zip(filas, esperados):
                frappe.db.set_value("Concepto Orden Taller", fila.name, {
                    "de_valuacion": 1, "partida_valuacion": esperado["partida_valuacion"]}, update_modified=False)


def coincide(fila, esperado):
    return all(
        flt(fila.get(c), 2) == flt(esperado[c], 2) if c in ("qty", "rate") else (fila.get(c) or "") == (esperado[c] or "")
        for c in CAMPOS_LIGADOS)
