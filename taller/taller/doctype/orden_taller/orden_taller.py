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
from taller.flujo.configuracion import CAMPO_TIPO_ORDEN, ESTADO_INICIAL
from taller.flujo.estatus import sincronizar_estatus
from taller.flujo.pasos import sincronizar_pasos, validar_inventario
from taller.flujo.reglas import validar_reglas_transicion
from taller.fotos import procesar_fotos
from taller.taller.doctype.inventario.inventario import actualizar_momento, crear_inventario
from taller.vehiculo.vin import revisar_vin


class OrdenTaller(Document):
    def validate(self):
        self.company = self.company or frappe.defaults.get_user_default("Company")
        self.validar_cambio_tipo_orden()
        revisar_vin(self)
        calcular_conceptos(self)
        calcular_montos(self)
        calcular_costeo(self)
        validar_reglas_transicion(self)
        validar_inventario(self)
        procesar_fotos(self)
        sincronizar_pasos(self)
        sincronizar_estatus(self)

    def validar_cambio_tipo_orden(self):
        anterior = self.get_doc_before_save()
        if (anterior and anterior.get(CAMPO_TIPO_ORDEN)
                and anterior.get(CAMPO_TIPO_ORDEN) != self.get(CAMPO_TIPO_ORDEN)
                and anterior.workflow_state not in (None, "", ESTADO_INICIAL)):
            frappe.throw(_("El tipo de orden solo se puede cambiar mientras la orden está en {0}.")
                         .format(ESTADO_INICIAL))

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
