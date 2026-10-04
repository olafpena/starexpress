import frappe
from frappe.model.document import Document

from taller.erp.costeo import (
    CAMPOS_COSTEO,
    actualizar_estado_proyecto,
    calcular_costeo,
    crear_proyecto,
    registrar_mano_obra,
)
from taller.erp.documentos import calcular_conceptos, calcular_montos
from taller.flujo.pasos import sincronizar_pasos
from taller.flujo.reglas import validar_reglas_transicion


class OrdenTaller(Document):
    def validate(self):
        self.company = self.company or frappe.defaults.get_user_default("Company")
        calcular_conceptos(self)
        calcular_montos(self)
        calcular_costeo(self)
        validar_reglas_transicion(self)
        sincronizar_pasos(self)

    def after_insert(self):
        crear_proyecto(self)

    def on_update(self):
        self.despues_de_guardar()

    def on_submit(self):
        self.despues_de_guardar()

    def despues_de_guardar(self):
        registrar_mano_obra(self)
        actualizar_estado_proyecto(self)
        calcular_costeo(self)
        self.db_set({c: self.get(c) for c in CAMPOS_COSTEO}, update_modified=False)
