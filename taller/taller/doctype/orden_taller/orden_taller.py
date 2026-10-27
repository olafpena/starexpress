import re

import frappe
from frappe import _
from frappe.model.document import Document

from taller.erp.costeo import (
    CAMPOS_COSTEO,
    actualizar_estado_proyecto,
    calcular_costeo,
    crear_proyecto,
    registrar_mano_obra,
)
from taller.erp.documentos import calcular_conceptos, calcular_montos
from taller.flujo.configuracion import CAMPO_TIPO_ORDEN, DOCTYPE_INVENTARIO, ESTADO_INICIAL, recolecta
from taller.flujo.estatus import sincronizar_estatus
from taller.flujo.pasos import sincronizar_pasos, totalizar_horas, validar_horas, validar_inventario
from taller.flujo.reglas import validar_reglas_transicion
from taller.fotos import procesar_fotos
from taller.taller.doctype.inventario.inventario import CAMPOS_A_LA_ORDEN, actualizar_momento, crear_inventario
from taller.taller.doctype.valuacion_taller.valuacion_taller import validar_conceptos_de_valuacion


class OrdenTaller(Document):
    def validate(self):
        self.company = self.company or frappe.defaults.get_user_default("Company")
        self.validar_cambio_tipo_orden()
        self.traer_vehiculo_del_inventario()
        self.llenar_direccion_recoleccion()
        validar_horas(self)
        validar_conceptos_de_valuacion(self)
        calcular_conceptos(self)
        calcular_montos(self)
        calcular_costeo(self)
        validar_reglas_transicion(self)
        validar_inventario(self)
        procesar_fotos(self)
        sincronizar_pasos(self)
        totalizar_horas(self)
        sincronizar_estatus(self)

    def before_update_after_submit(self):
        # Las horas de los pasos se pueden corregir con la orden terminada
        validar_horas(self)
        totalizar_horas(self)

    def validar_cambio_tipo_orden(self):
        anterior = self.get_doc_before_save()
        if (anterior and anterior.get(CAMPO_TIPO_ORDEN)
                and anterior.get(CAMPO_TIPO_ORDEN) != self.get(CAMPO_TIPO_ORDEN)
                and anterior.workflow_state not in (None, "", ESTADO_INICIAL)):
            frappe.throw(_("El tipo de orden solo se puede cambiar mientras la orden está en {0}.")
                         .format(ESTADO_INICIAL))

    def traer_vehiculo_del_inventario(self):
        """El vehículo se captura en el inventario; la orden guarda su copia (lista, filtros, búsqueda)."""
        if self.inventario:
            self.update(frappe.db.get_value(DOCTYPE_INVENTARIO, self.inventario, CAMPOS_A_LA_ORDEN, as_dict=True) or {})

    def llenar_direccion_recoleccion(self):
        """En Agencia, la recolección es en la agencia: su dirección registrada, si no se capturó otra."""
        if (self.tipo_flujo == "Agencia" and self.cliente and recolecta(self)
                and not (self.direccion_recoleccion or "").strip()):
            self.direccion_recoleccion = direccion_de_cliente(self.cliente, revisar_permiso=False)

    def after_insert(self):
        crear_proyecto(self)
        crear_inventario(self)

    def on_update(self):
        actualizar_momento(self)
        self.despues_de_guardar()

    def on_submit(self):
        self.despues_de_guardar()

    def despues_de_guardar(self):
        registrar_mano_obra(self)
        actualizar_estado_proyecto(self)
        calcular_costeo(self)
        self.db_set({c: self.get(c) for c in CAMPOS_COSTEO}, update_modified=False)


@frappe.whitelist()
def direccion_de_cliente(cliente, revisar_permiso=True):
    """Dirección principal del cliente (o la predeterminada), en texto de varias líneas."""
    from frappe.contacts.doctype.address.address import get_default_address, render_address

    if not cliente:
        return ""
    if revisar_permiso:
        frappe.has_permission("Customer", "read", cliente, throw=True)
    nombre = (frappe.db.get_value("Customer", cliente, "customer_primary_address")
              or get_default_address("Customer", cliente))
    if not nombre:
        return ""
    html = render_address(nombre, check_permissions=False) or ""
    lineas = (re.sub(r"<[^>]+>", "", linea).strip() for linea in re.split(r"<br\s*/?>|\n", html))
    return "\n".join(linea for linea in lineas if linea)
