import frappe
from frappe import _
from frappe.model.document import Document


class EstatusOrdenTaller(Document):
    def on_trash(self):
        if self.sistema:
            frappe.throw(_("El estatus {0} lo usa la app y no se puede borrar.").format(self.estatus))
