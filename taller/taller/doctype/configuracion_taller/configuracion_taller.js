// Configuración de la compañía del taller sin terminal: elige la compañía y sus cuentas
// y corre taller.erp.configuracion_empresa.configurar (botón "Configurar compañía").
const CAMPOS_CUENTA = [
	"cuenta_por_cobrar", "cuenta_por_pagar", "cuenta_ingreso_materiales", "cuenta_ingreso_servicios",
	"cuenta_costo", "cuenta_redondeo", "cuenta_caja", "cuenta_banco",
];

frappe.ui.form.on("Configuracion Taller", {
	setup(frm) {
		CAMPOS_CUENTA.forEach((campo) =>
			frm.set_query(campo, () => ({ filters: { company: frm.doc.company, is_group: 0 } }))
		);
	},
	refresh(frm) {
		frm.add_custom_button(__("Configurar compañía"), () =>
			frappe.confirm(
				__("Se configurará la compañía {0} para el taller (cuentas, almacén, centro de costo, artículos y actividades). ¿Continuar?", [frm.doc.company || ""]),
				() => frm.call({ doc: frm.doc, method: "configurar_compania", freeze: true }).then((r) => {
					frm.reload_doc();
					frappe.msgprint(r.message);
				})
			)
		).addClass("btn-primary");
	},
	company(frm) {
		if (!frm.doc.company) return;
		frappe.call({
			method: "taller.taller.doctype.configuracion_taller.configuracion_taller.cuentas_sugeridas",
			args: { company: frm.doc.company },
		}).then(({ message }) => {
			// Las que no existen con el nombre sugerido quedan vacías para elegirlas
			CAMPOS_CUENTA.forEach((campo) => frm.set_value(campo, message[campo] || ""));
		});
	},
});
