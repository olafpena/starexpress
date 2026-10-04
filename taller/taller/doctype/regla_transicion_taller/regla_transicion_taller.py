import frappe
from frappe import _
from frappe.model.document import Document

from taller.flujo.configuracion import SEPARADOR


class ReglaTransicionTaller(Document):
    def validate(self):
        self.condicion = (self.condicion or "").strip()
        try:
            compile(self.condicion, "<regla>", "eval")
        except SyntaxError as e:
            frappe.throw(_("La condición no es una expresión Python válida: {0}").format(e))

        if (self.estado_destino and self.paso and self.paso != "Todos"
                and not self.estado_destino.startswith(self.paso + SEPARADOR)):
            frappe.msgprint(
                _("El Estado destino tiene prioridad sobre el Paso; el Paso '{0}' se ignorará.").format(self.paso),
                indicator="orange",
            )
