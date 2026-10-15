// Inventario de la unidad. El visor de fotos viene de public/js/fotos.js (hooks.py).
frappe.ui.form.on("Inventario", {
	refresh(frm) {
		taller_fotos.pintar(frm);
		if (frm.doc.orden_taller) {
			frm.add_custom_button(__("Orden de taller"), () =>
				frappe.set_route("Form", "Orden Taller", frm.doc.orden_taller)
			);
		}
		if (frm.doc.docstatus === 0) {
			const faltan = angulos_faltantes(frm);
			if (faltan.length) {
				frm.set_intro(__("Fotos que faltan: {0}", [faltan.map((a) => __(a)).join(", ")]), "orange");
			} else {
				frm.set_intro("");
			}
		}
	},
	momento(frm) {
		frm.trigger("refresh");
	},
});

frappe.ui.form.on("Foto Orden Taller", {
	angulo(frm) {
		frm.trigger("refresh");
	},
	fotos_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "etapa", frm.doc.momento);
	},
});

// Ángulos obligatorios: las opciones del campo, sin el de daños de cerca (último)
function angulos_faltantes(frm) {
	const df = frappe.meta.get_docfield("Foto Orden Taller", "angulo", frm.doc.name);
	const opciones = (df.options || "").split("\n").filter(Boolean).slice(0, -1);
	const tomadas = new Set((frm.doc.fotos || []).filter((f) => f.imagen).map((f) => f.angulo));
	return opciones.filter((a) => !tomadas.has(a));
}
