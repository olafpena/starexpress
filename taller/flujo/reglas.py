"""
Motor de reglas de transición.

Cada vez que una Orden Taller cambia de `workflow_state` (por botón del
workflow o por guardado directo) se evalúan las "Regla Transicion Taller"
activas que apliquen:

  * tipo_orden  : "Todos" o el tipo de orden (Hojalatería y Pintura, Mecánica,
                  Ambos). Una orden Ambos toma también las reglas de Mecánica y
                  de Hojalatería y Pintura (TIPOS_DE_REGLAS)
  * tipo_flujo  : "Todos" o el tipo de la orden
  * estado_origen (opcional): solo si la orden viene de ese estado
  * estado_destino (opcional): solo si la orden va a ese estado
  * paso        : si no hay estado_destino, aplica al entrar a cualquier
                  estado de ese paso ("Todos" = cualquier transición)

La condición es una expresión Python evaluada con safe_eval. Variables:
  doc       -> la orden con los valores nuevos
  anterior  -> la orden antes de guardar (None si es nueva)
  origen    -> estado anterior (str o None)
  destino   -> estado nuevo (str)
  inventario -> el inventario de la orden (dict con sus campos) o None
  frappe.db.get_value, frappe.utils, etc. (globals seguros de Frappe)

Si la condición es falsa:
  * "Bloquear" -> se cancela la transición con el mensaje
  * "Advertir" -> se muestra el mensaje y la transición continúa
"""

import frappe
from frappe import _
from frappe.utils.safe_exec import safe_eval

from taller.flujo.configuracion import (
    CAMPO_ESTADO,
    DOCTYPE_INVENTARIO,
    DOCTYPE_REGLAS,
    TIPOS_DE_REGLAS,
    paso_de_estado,
    tipo_orden_de,
)


def validar_reglas_transicion(doc):
    anterior = doc.get_doc_before_save()
    origen = anterior.get(CAMPO_ESTADO) if anterior else None
    destino = doc.get(CAMPO_ESTADO)
    if not destino or origen == destino:
        return

    bloqueos, advertencias = [], []
    inventario = None
    for regla in obtener_reglas(doc.get("tipo_flujo"), tipo_orden_de(doc)):
        if not aplica(regla, origen, destino):
            continue
        if inventario is None:
            inventario = inventario_de(doc)
        if evaluar(regla, doc, anterior, origen, destino, inventario or None):
            continue
        destino_lista = bloqueos if regla.tipo_regla == "Bloquear" else advertencias
        destino_lista.append(regla.mensaje)

    if advertencias:
        frappe.msgprint(_lista_html(advertencias), title=_("Advertencias"), indicator="orange")
    if bloqueos:
        frappe.throw(_lista_html(bloqueos),
                     title=_("No se puede pasar de {0} a {1}").format(origen or "-", destino))


def obtener_reglas(tipo_flujo, tipo_orden):
    tipos = ["Todos"] + TIPOS_DE_REGLAS.get(tipo_orden, [tipo_orden or ""])
    return frappe.get_all(
        DOCTYPE_REGLAS,
        filters={"activo": 1, "tipo_flujo": ["in", ["Todos", tipo_flujo or ""]],
                 "tipo_orden": ["in", tipos]},
        fields=["name", "paso", "estado_origen", "estado_destino",
                "tipo_regla", "condicion", "mensaje"],
        order_by="prioridad asc, creation asc",
    )


def aplica(regla, origen, destino):
    if regla.estado_origen and regla.estado_origen != origen:
        return False
    if regla.estado_destino:
        return regla.estado_destino == destino
    return regla.paso in (None, "", "Todos") or regla.paso == paso_de_estado(destino)


def inventario_de(doc):
    """Campos del inventario vigente de la orden; {} si no tiene."""
    if not doc.get("inventario"):
        return {}
    return frappe.db.get_value(DOCTYPE_INVENTARIO, doc.inventario, "*", as_dict=True) or {}


def evaluar(regla, doc, anterior, origen, destino, inventario=None):
    contexto = {"doc": doc, "anterior": anterior, "origen": origen, "destino": destino,
                "inventario": inventario}
    try:
        return bool(safe_eval(regla.condicion, None, contexto))
    except Exception as e:
        frappe.throw(_("Error al evaluar la regla {0}: {1}").format(
            frappe.utils.get_link_to_form(DOCTYPE_REGLAS, regla.name), e))


def _lista_html(mensajes):
    if len(mensajes) == 1:
        return mensajes[0]
    return "<ul>" + "".join(f"<li>{m}</li>" for m in mensajes) + "</ul>"
