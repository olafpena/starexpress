from frappe.model.document import Document

from taller.vehiculo.vin import revisar_vin


class VehiculoTaller(Document):
    def validate(self):
        revisar_vin(self)
