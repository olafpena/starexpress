// Botón para regresar a la Orden Taller desde los documentos de ERPNext que genera
// (taller/erp/documentos.py). Se carga en Quotation, Sales Order y Sales Invoice (hooks.py).
["Quotation", "Sales Order", "Sales Invoice"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			if (frm.doc.orden_taller) {
				frm.add_custom_button(__("Orden de taller"), () =>
					frappe.set_route("Form", "Orden Taller", frm.doc.orden_taller)
				);
			}
		},
	});
});
