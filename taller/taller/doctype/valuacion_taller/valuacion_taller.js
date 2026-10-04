const ORIGEN_POR_TIPO = { Agencia: "Audatex", Aseguradora: "Audatex", Particular: "Captura manual" };
const METODO_LEER = "taller.taller.doctype.valuacion_taller.valuacion_taller.leer_pdf";

frappe.ui.form.on("Valuacion Taller", {
	setup(frm) {
		frm.set_query("orden_taller", () => ({ filters: { docstatus: 0 } }));
	},
	refresh(frm) {
		if (frm.doc.orden_taller) {
			frm.add_custom_button(__("Orden Taller"), () => frappe.set_route("Form", "Orden Taller", frm.doc.orden_taller), __("Ver"));
		}
		if (frm.doc.docstatus === 0 && frm.doc.origen === "Audatex" && frm.doc.archivo_pdf && !frm.is_new()) {
			frm.add_custom_button(__("Leer PDF de Audatex"), () => leer_pdf(frm)).addClass("btn-primary");
		}
		if (frm.doc.origen === "Audatex" && frm.doc.subtotal_documento) {
			const cuadra = Math.abs(flt(frm.doc.diferencia)) <= 1;
			frm.dashboard.add_indicator(
				cuadra
					? __("Cuadra con Audatex: {0}", [format_currency(frm.doc.subtotal_documento)])
					: __("Diferencia con Audatex: {0}", [format_currency(frm.doc.diferencia)]),
				cuadra ? "green" : "red"
			);
		}
	},
	orden_taller(frm) {
		if (!frm.doc.orden_taller) return;
		frappe.db.get_value("Orden Taller", frm.doc.orden_taller, "tipo_flujo").then(({ message }) => {
			const origen = ORIGEN_POR_TIPO[message && message.tipo_flujo];
			if (origen) frm.set_value("origen", origen);
		});
	},
	archivo_pdf(frm) {
		if (frm.doc.archivo_pdf && frm.doc.origen === "Audatex") {
			frm.save().then(() => leer_pdf(frm));
		}
	},
});

frappe.ui.form.on("Partida Valuacion Taller", {
	tipo(frm, cdt, cdn) {
		const fila = locals[cdt][cdn];
		if (fila.tipo && fila.tipo.startsWith("Mano de obra") && !flt(fila.precio_unitario) && frm.doc.tarifa_hora) {
			frappe.model.set_value(cdt, cdn, "precio_unitario", frm.doc.tarifa_hora);
		}
	},
	cantidad: calcular_importe,
	precio_unitario: calcular_importe,
	descuento: calcular_importe,
});

function calcular_importe(frm, cdt, cdn) {
	const fila = locals[cdt][cdn];
	const bruto = flt(flt(fila.cantidad) * flt(fila.precio_unitario), 2);
	frappe.model.set_value(cdt, cdn, "importe", bruto - flt((bruto * flt(fila.descuento)) / 100, 2));
}

function leer_pdf(frm) {
	frappe.call({
		method: METODO_LEER,
		args: { valuacion: frm.doc.name },
		freeze: true,
		freeze_message: __("Leyendo la valuación de Audatex..."),
		callback({ message }) {
			frm.reload_doc();
			const cuadra = Math.abs(flt(message.diferencia)) <= 1;
			frappe.show_alert({
				message: cuadra
					? __("Se leyeron {0} partidas; cuadran con el PDF.", [message.partidas])
					: __("Se leyeron {0} partidas; hay una diferencia de {1} con el PDF. Revisa las partidas.", [
							message.partidas,
							format_currency(message.diferencia),
					  ]),
				indicator: cuadra ? "green" : "orange",
			});
		},
	});
}
