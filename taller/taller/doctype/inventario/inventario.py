"""
Inventario de la unidad: la hoja de inventario de recolección capturada en el ERP.

Toda Orden Taller tiene uno (lo crea la orden al guardarse, ver crear_inventario).
Se levanta en Recolección si la orden la requiere y si no en Recepción; la orden
no completa ni anula esos pasos sin el inventario enviado (taller/flujo/pasos.py).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from taller.flujo.configuracion import (
    ACCESORIOS_INVENTARIO,
    ANGULOS_OBLIGATORIOS,
    DOCTYPE,
    DOCTYPE_INVENTARIO,
    DOCTYPE_VEHICULO,
    MOMENTO_RECEPCION,
    MOMENTO_RECOLECCION,
)
from taller.fotos import procesar_fotos

# Datos que el inventario trae de la orden (además de los fetch_from del JSON,
# que en el servidor solo corren al cambiar el Link)
CAMPOS_DE_LA_ORDEN = ["tipo_orden", "tipo_flujo", "cliente", "cliente_nombre", "telefono", "email",
                      "aseguradora", "direccion_recoleccion", "asesor_agencia", "orden_agencia",
                      "numero_siniestro", "vehiculo", "marca", "modelo", "anio", "color", "placas", "vin"]
CAMPOS_AL_VEHICULO = ["numero_motor", "transmision"]


class Inventario(Document):
    def validate(self):
        self.validar_unico()
        self.validar_folio()
        self.traer_de_la_orden()
        procesar_fotos(self, etapa=self.momento)

    def validar_unico(self):
        otro = frappe.db.get_value(DOCTYPE_INVENTARIO, {
            "orden_taller": self.orden_taller, "docstatus": ["<", 2], "name": ["!=", self.name]})
        if otro:
            frappe.throw(_("La orden {0} ya tiene el inventario {1}.").format(
                self.orden_taller, frappe.utils.get_link_to_form(DOCTYPE_INVENTARIO, otro)))

    def validar_folio(self):
        if not self.folio_hoja:
            return
        otro = frappe.db.get_value(DOCTYPE_INVENTARIO, {
            "folio_hoja": self.folio_hoja, "docstatus": ["<", 2], "name": ["!=", self.name]})
        if otro:
            frappe.throw(_("El folio de hoja {0} ya está en el inventario {1}.").format(self.folio_hoja, otro))

    def traer_de_la_orden(self):
        orden = frappe.db.get_value(DOCTYPE, self.orden_taller, CAMPOS_DE_LA_ORDEN + ["requiere_recoleccion"],
                                    as_dict=True)
        if not orden:
            return
        for campo in CAMPOS_DE_LA_ORDEN:
            self.set(campo, orden.get(campo))
        if self.docstatus == 0:
            self.momento = MOMENTO_RECOLECCION if orden.requiere_recoleccion else MOMENTO_RECEPCION
        if self.vehiculo:
            vehiculo = frappe.db.get_value(DOCTYPE_VEHICULO, self.vehiculo, CAMPOS_AL_VEHICULO, as_dict=True) or {}
            for campo in CAMPOS_AL_VEHICULO:
                self.set(campo, self.get(campo) or vehiculo.get(campo))

    def before_submit(self):
        faltan = []
        if not self.firma_entrega:
            faltan.append(_("la firma de quien entrega la unidad"))
        if not self.firma_recibe:
            faltan.append(_("la firma de quien la recibe"))
        tomadas = {f.angulo for f in self.fotos if f.imagen}
        sin_foto = [a for a in ANGULOS_OBLIGATORIOS if a not in tomadas]
        if sin_foto:
            faltan.append(_("las fotos de: {0}").format(", ".join(sin_foto)))
        danos_sin_foto = [str(d.idx) for d in self.danos if not d.foto]
        if danos_sin_foto:
            faltan.append(_("la foto de los daños {0}").format(", ".join(danos_sin_foto)))
        if faltan:
            frappe.throw(_("Sin hoja firmada y sin fotos no se mueve la unidad. Falta {0}.").format(
                "; ".join(faltan)), title=_("Inventario incompleto"))
        ahora = now_datetime()
        self.fecha_firma_entrega = self.fecha_firma_entrega or ahora
        self.fecha_firma_recibe = self.fecha_firma_recibe or ahora

    def after_insert(self):
        # Al modificar (amend) un inventario cancelado, la orden apunta al nuevo
        frappe.db.set_value(DOCTYPE, self.orden_taller, "inventario", self.name, update_modified=False)

    def on_submit(self):
        self.copiar_al_vehiculo()
        cambios = {}
        if self.momento == MOMENTO_RECEPCION:
            if self.kilometraje:
                cambios["kilometraje"] = self.kilometraje
            cambios["fecha_ingreso"] = self.fecha_inventario
        cambios.update(self.datos_de_recepcion())
        if cambios:
            frappe.db.set_value(DOCTYPE, self.orden_taller, cambios)

    def on_update_after_submit(self):
        cambios = self.datos_de_recepcion()
        if cambios:
            frappe.db.set_value(DOCTYPE, self.orden_taller, cambios)

    def datos_de_recepcion(self):
        """Recepción en taller de una unidad recolectada: su llegada es el ingreso de la orden."""
        if self.momento == MOMENTO_RECOLECCION and self.fecha_recepcion:
            return {"fecha_ingreso": self.fecha_recepcion}
        return {}

    def copiar_al_vehiculo(self):
        if not self.vehiculo:
            return
        actuales = frappe.db.get_value(DOCTYPE_VEHICULO, self.vehiculo, CAMPOS_AL_VEHICULO, as_dict=True) or {}
        cambios = {c: self.get(c) for c in CAMPOS_AL_VEHICULO if self.get(c) and not actuales.get(c)}
        if cambios:
            frappe.db.set_value(DOCTYPE_VEHICULO, self.vehiculo, cambios)


def crear_inventario(orden):
    """Crea el inventario de una orden nueva, con los accesorios y documentos de la hoja precargados."""
    if orden.get("inventario") and frappe.db.exists(DOCTYPE_INVENTARIO, orden.inventario):
        return orden.inventario
    inventario = frappe.new_doc(DOCTYPE_INVENTARIO)
    inventario.orden_taller = orden.name
    inventario.momento = MOMENTO_RECOLECCION if orden.get("requiere_recoleccion") else MOMENTO_RECEPCION
    for grupo, concepto in ACCESORIOS_INVENTARIO:
        inventario.append("accesorios", {"grupo": grupo, "concepto": concepto})
    inventario.insert(ignore_permissions=True)
    orden.db_set("inventario", inventario.name, update_modified=False)
    return inventario.name


def actualizar_momento(orden):
    """Si la orden cambia Requiere recolección, el inventario aún sin enviar cambia de momento."""
    if not orden.get("inventario"):
        return
    momento = MOMENTO_RECOLECCION if orden.get("requiere_recoleccion") else MOMENTO_RECEPCION
    actual = frappe.db.get_value(DOCTYPE_INVENTARIO, orden.inventario, ["docstatus", "momento"], as_dict=True)
    if actual and actual.docstatus == 0 and actual.momento != momento:
        frappe.db.set_value(DOCTYPE_INVENTARIO, orden.inventario, "momento", momento)
