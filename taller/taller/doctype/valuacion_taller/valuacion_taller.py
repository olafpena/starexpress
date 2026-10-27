"""
Valuación de la Orden Taller.

Agencia y Aseguradora: se adjunta el "Reporte Completo" de Audatex y `leer_pdf`
llena expediente, vehículo, partidas y los totales del documento. Para aprobarla
(enviar), el subtotal de las partidas debe cuadrar con el del PDF.

Particular: la misma forma con las partidas capturadas a mano.

La orden liga su valuación (`valuacion`) desde que se crea, igual que el
inventario; al cancelarla o borrarla la orden queda sin valuación.

Al enviarla:
  * la orden queda con `valuacion_aprobada` (necesaria para completar Recepción),
  * se llenan en la orden los datos vacíos del vehículo y, en Aseguradora,
    los del siniestro y la autorización,
  * las partidas pasan a los conceptos de la orden si aún no hay orden de venta.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from taller.erp.configuracion_empresa import ARTICULO_POR_TIPO
from taller.erp.documentos import tasa_impuestos
from taller.flujo.configuracion import DOCTYPE_INVENTARIO, TIPOS_CON_VALUACION
from taller.valuacion import audatex
from taller.vehiculo.vin import revisar_vin

DOCTYPE_ORDEN = "Orden Taller"
TOLERANCIA = 1.0  # pesos de diferencia aceptados contra el PDF (redondeos)

TOTAL_POR_TIPO = {
    audatex.REFACCION: "total_refacciones",
    audatex.MO_HOJALATERIA: "total_mano_obra",
    audatex.MO_PINTURA: "total_mano_obra",
    audatex.MATERIAL_PINTURA: "total_materiales",
    audatex.MATERIAL_REPARACION: "total_materiales",
    audatex.OTRO: "total_otros",
}
CAMPOS_VEHICULO = ["marca", "modelo", "anio", "color", "placas", "vin"]


class ValuacionTaller(Document):
    def validate(self):
        tipo_orden = frappe.db.get_value(DOCTYPE_ORDEN, self.orden_taller, "tipo_orden")
        if tipo_orden and tipo_orden not in TIPOS_CON_VALUACION:
            frappe.throw(_("La valuación es parte del flujo de Hojalatería y Pintura; la orden {0} es de {1}.")
                         .format(self.orden_taller, tipo_orden))
        # El VIN de Audatex lo captura la aseguradora o agencia: solo se advierte
        revisar_vin(self, estricto=self.origen != "Audatex")
        self.validar_unica()
        self.calcular_totales()

    def before_submit(self):
        if not self.partidas:
            frappe.throw(_("Agrega al menos una partida a la valuación."))
        if self.origen == "Audatex":
            if not self.archivo_pdf:
                frappe.throw(_("Adjunta el PDF de Audatex."))
            if abs(flt(self.diferencia)) > TOLERANCIA:
                frappe.throw(_("Las partidas suman {0} y el PDF de Audatex {1} (diferencia {2}). "
                               "Corrige las partidas antes de aprobar la valuación.").format(
                    frappe.format(self.subtotal, "Currency"), frappe.format(self.subtotal_documento, "Currency"),
                    frappe.format(self.diferencia, "Currency")))
        if self.tipo_flujo in ("Agencia", "Aseguradora") and self.origen != "Audatex":
            frappe.msgprint(_("La orden es de {0}; normalmente su valuación viene de Audatex.")
                            .format(self.tipo_flujo), indicator="orange", alert=True)

    def on_submit(self):
        aplicar_a_orden(self)

    def after_insert(self):
        # Como el inventario: la orden muestra el link desde que la valuación existe. Cambia el
        # modified de la orden para que un formulario abierto se recargue y no borre el link al guardar
        frappe.db.set_value(DOCTYPE_ORDEN, self.orden_taller, {"valuacion": self.name, "valuacion_total": self.total})

    def on_update(self):
        # El total de la orden sigue al borrador mientras se captura
        if frappe.db.get_value(DOCTYPE_ORDEN, self.orden_taller, "valuacion") == self.name:
            frappe.db.set_value(DOCTYPE_ORDEN, self.orden_taller, "valuacion_total", self.total, update_modified=False)

    def on_cancel(self):
        self.desligar_de_la_orden()

    def on_trash(self):
        self.desligar_de_la_orden()

    def desligar_de_la_orden(self):
        if frappe.db.get_value(DOCTYPE_ORDEN, self.orden_taller, "valuacion") == self.name:
            frappe.db.set_value(DOCTYPE_ORDEN, self.orden_taller,
                                {"valuacion": None, "valuacion_aprobada": 0, "valuacion_total": 0})
            # Sus conceptos quedan como capturados a mano hasta que se apruebe otra valuación
            desligar_conceptos(self.orden_taller)

    def validar_unica(self):
        otra = frappe.db.get_value("Valuacion Taller", {
            "orden_taller": self.orden_taller, "docstatus": ["<", 2], "name": ["!=", self.name]})
        if otra:
            frappe.throw(_("La orden {0} ya tiene la valuación {1}. Cancélala para cargar otra.")
                         .format(self.orden_taller, otra))

    def calcular_totales(self):
        for campo in set(TOTAL_POR_TIPO.values()) | {"total_deducciones"}:
            self.set(campo, 0)
        for p in self.partidas:
            bruto = flt(flt(p.cantidad) * flt(p.precio_unitario), 2)
            deduccion = flt(bruto * flt(p.descuento) / 100, 2)
            p.importe = bruto - deduccion
            p.item_code = p.item_code or ARTICULO_POR_TIPO.get(p.tipo)
            campo = TOTAL_POR_TIPO.get(p.tipo, "total_otros")
            self.set(campo, flt(self.get(campo)) + p.importe)
            self.total_deducciones = flt(self.total_deducciones) + deduccion
        self.subtotal = sum(flt(p.importe) for p in self.partidas)
        tasa = tasa_impuestos(self.company) if self.company else 0
        self.iva = flt(self.subtotal * tasa, 2)
        self.total = self.subtotal + self.iva
        self.diferencia = flt(self.subtotal - flt(self.subtotal_documento), 2) if self.subtotal_documento else 0

    def cargar_datos_audatex(self, datos):
        enc, veh, tot = datos["encabezado"], datos["vehiculo"], datos["totales"]
        self.update({
            "origen": "Audatex",
            "estado_valuacion": enc.get("estado"),
            "numero_reclamo": enc.get("numero_reclamo"),
            "numero_expediente": enc.get("numero_expediente"),
            "numero_poliza": enc.get("numero_poliza"),
            "version_valuacion": enc.get("version"),
            "proveedor": enc.get("proveedor"),
            "causa": enc.get("causa"),
            "fecha_accidente": enc.get("fecha_accidente"),
            "fecha_inspeccion": enc.get("fecha_inspeccion"),
            "fecha_autorizacion": enc.get("fecha_autorizacion"),
            "autorizado_por": enc.get("autorizado_por"),
            "taller_reparacion": enc.get("taller"),
            "submodelo": veh.get("submodelo"),
            "valor_mercado": veh.get("valor_mercado"),
            "ut_por_hora": datos.get("ut_por_hora"),
            "tarifa_hora": datos.get("tarifa_hora"),
            "subtotal_documento": tot.get("suma_sin_iva") or tot.get("subtotal"),
            "total_documento": tot.get("gran_total") or tot.get("total_con_iva"),
            "notas": datos.get("notas"),
            **{c: veh.get(c) for c in CAMPOS_VEHICULO},
        })
        self.set("partidas", [])
        for p in datos["partidas"]:
            self.append("partidas", p)


@frappe.whitelist()
def leer_pdf(valuacion):
    doc = frappe.get_doc("Valuacion Taller", valuacion)
    doc.check_permission("write")
    if doc.docstatus != 0:
        frappe.throw(_("Solo se puede leer el PDF en una valuación en borrador."))
    if not doc.archivo_pdf:
        frappe.throw(_("Adjunta primero el PDF de Audatex."))

    archivo = frappe.get_doc("File", {"file_url": doc.archivo_pdf})
    try:
        datos = audatex.leer_pdf(archivo.get_content())
    except audatex.ErrorValuacion as e:
        frappe.throw(str(e), title=_("No se pudo leer la valuación"))
    except Exception:
        frappe.log_error(f"Lectura de valuación Audatex {doc.name}")
        frappe.throw(_("No se pudo leer el PDF. ¿Es el Reporte Completo de Audatex?"),
                     title=_("No se pudo leer la valuación"))

    doc.cargar_datos_audatex(datos)
    doc.save()
    return {"partidas": len(doc.partidas), "subtotal": doc.subtotal, "diferencia": doc.diferencia}


# ==========================================================================
# Efectos en la orden al aprobar la valuación
# ==========================================================================
def aplicar_a_orden(val):
    orden = frappe.get_doc(DOCTYPE_ORDEN, val.orden_taller)
    if orden.docstatus != 0:
        frappe.db.set_value(DOCTYPE_ORDEN, orden.name, {"valuacion": val.name, "valuacion_aprobada": 1})
        return

    orden.valuacion = val.name
    orden.valuacion_aprobada = 1
    completar_inventario(val, orden)

    if orden.tipo_flujo == "Aseguradora":
        orden.numero_siniestro = orden.numero_siniestro or val.numero_reclamo or val.numero_expediente
        orden.numero_poliza = orden.numero_poliza or val.numero_poliza
        if (val.estado_valuacion or "").strip().lower() == "autorizado":
            orden.autorizacion_aseguradora = 1
        orden.monto_autorizado = val.total

    if frappe.db.get_value("Sales Order", orden.orden_venta, "docstatus") in (0, 1):
        frappe.msgprint(_("La orden ya tiene orden de venta; sus conceptos no se cambiaron."),
                        indicator="orange", alert=True)
    else:
        orden.set("conceptos", [])
        for p in partidas_cobrables(val):
            orden.append("conceptos", concepto_de_partida(p))

    orden.save()


def partidas_cobrables(val):
    return [p for p in val.partidas if flt(p.importe)]


def concepto_de_partida(p):
    cantidad = flt(p.cantidad) or 1
    return {
        "item_code": p.item_code or ARTICULO_POR_TIPO[audatex.OTRO],
        "descripcion": " ".join(filter(None, [p.descripcion, p.numero_pieza and f"({p.numero_pieza})"])),
        "qty": cantidad,
        "rate": flt(p.importe) / cantidad,
        "de_valuacion": 1,
        "partida_valuacion": p.name,
    }


CAMPOS_LIGADOS = ("item_code", "descripcion", "qty", "rate")


def validar_conceptos_de_valuacion(orden):
    """Los conceptos que vienen de la valuación aprobada no se cambian ni se quitan desde la orden.

    Se pueden agregar otros (hallazgos, complementos). Para cambiar lo autorizado se
    cancela y corrige la valuación; al aprobarse de nuevo reemplaza sus conceptos.
    """
    ligados = {c.partida_valuacion: c for c in orden.conceptos if c.partida_valuacion}
    if not ligados:
        return
    if not (orden.valuacion and orden.valuacion_aprobada):
        frappe.throw(_("Hay conceptos de una valuación que ya no está aprobada en la orden."))
    val = frappe.get_doc("Valuacion Taller", orden.valuacion)
    cambiados = []
    for p in partidas_cobrables(val):
        esperado = concepto_de_partida(p)
        fila = ligados.pop(p.name, None)
        if not fila:
            cambiados.append(_("se quitó «{0}»").format(esperado["descripcion"] or esperado["item_code"]))
            continue
        fila.de_valuacion = 1
        for campo in CAMPOS_LIGADOS:
            actual, valor = fila.get(campo), esperado[campo]
            igual = flt(actual, 2) == flt(valor, 2) if campo in ("qty", "rate") else (actual or "") == (valor or "")
            if not igual:
                cambiados.append(_("renglón {0}: cambió {1}").format(fila.idx, _(fila.meta.get_label(campo))))
    for fila in ligados.values():
        cambiados.append(_("renglón {0}: no es de la valuación {1}").format(fila.idx, val.name))
    if cambiados:
        frappe.throw(_("Los conceptos que vienen de la valuación no se pueden cambiar ni quitar ({0}). "
                       "Para corregirlos cancela y corrige la valuación; los extras agrégalos en renglones nuevos.")
                     .format("; ".join(cambiados)), title=_("Conceptos de la valuación"))


def desligar_conceptos(orden_taller):
    frappe.db.sql("""update `tabConcepto Orden Taller` set de_valuacion = 0, partida_valuacion = null
                     where parenttype = %s and parent = %s and ifnull(partida_valuacion, '') != ''""",
                  (DOCTYPE_ORDEN, orden_taller))


def completar_inventario(val, orden):
    """El vehículo de la valuación llena lo vacío del inventario de la orden (ahí se captura)."""
    if not orden.inventario:
        return
    inv = frappe.get_doc(DOCTYPE_INVENTARIO, orden.inventario)
    cambios = {c: val.get(c) for c in CAMPOS_VEHICULO if not inv.get(c) and val.get(c)}
    if not inv.vehiculo and (val.vin or val.placas):
        cambios["vehiculo"] = vehiculo_de(val, orden)
    if not cambios:
        return
    if inv.docstatus == 0:
        inv.update(cambios)
        inv.flags.vin_externo = val.origen == "Audatex"
        inv.save(ignore_permissions=True)
    else:
        frappe.db.set_value(DOCTYPE_INVENTARIO, inv.name, cambios)
    # La orden toma el vehículo y las placas del inventario al guardarse (aplicar_a_orden)


def vehiculo_de(val, orden):
    for campo in ("vin", "placas"):
        if val.get(campo):
            existente = frappe.db.get_value("Vehiculo Taller", {campo: val.get(campo)})
            if existente:
                return existente
    vehiculo = frappe.get_doc({
        "doctype": "Vehiculo Taller",
        "cliente": orden.cliente if orden.tipo_flujo == "Particular" else None,
        **{c: val.get(c) for c in CAMPOS_VEHICULO},
    })
    vehiculo.flags.vin_externo = val.origen == "Audatex"
    return vehiculo.insert(ignore_permissions=True).name
