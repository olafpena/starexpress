import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from taller.erp import configuracion_empresa

# Campo del formulario -> clave de la cuenta en configuracion_empresa.CUENTAS_SUGERIDAS
CAMPOS_CUENTA = {
    "cuenta_por_cobrar": "cobrar",
    "cuenta_por_pagar": "pagar",
    "cuenta_ingreso_materiales": "ventas",
    "cuenta_ingreso_servicios": "servicios",
    "cuenta_costo": "costo",
    "cuenta_redondeo": "redondeo",
    "cuenta_caja": "caja",
    "cuenta_banco": "banco",
}


class ConfiguracionTaller(Document):
    def validate(self):
        ajenas = [self.meta.get_label(campo) for campo in CAMPOS_CUENTA
                  if self.get(campo) and frappe.db.get_value("Account", self.get(campo), "company") != self.company]
        if ajenas:
            frappe.throw(_("Estas cuentas no son de la compañía {0}: {1}").format(self.company, ", ".join(ajenas)))

    @frappe.whitelist()
    def configurar_compania(self):
        """Corre configuracion_empresa.configurar con la compañía y las cuentas elegidas."""
        frappe.only_for("System Manager")
        self.save()
        configuracion_empresa.configurar(
            self.company, {clave: self.get(campo) for campo, clave in CAMPOS_CUENTA.items()})
        self.db_set("configurado_el", now_datetime())
        return _("Compañía {0} configurada para el taller.").format(self.company)


@frappe.whitelist()
def cuentas_sugeridas(company):
    """Campo -> cuenta sugerida que existe en la compañía, para prellenar el formulario."""
    frappe.only_for("System Manager")
    sugeridas = configuracion_empresa.cuentas_sugeridas(company)
    return {campo: sugeridas.get(clave) for campo, clave in CAMPOS_CUENTA.items()}
