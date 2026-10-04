const COLORES_TIPO = { Agencia: "blue", Particular: "green", Aseguradora: "purple" };
const COLORES_ESTADO = {
	"En Proceso": "var(--blue-500)",
	Completado: "var(--green-500)",
	Anulado: "var(--gray-400)",
};

const METODOS = "taller.erp.documentos";

frappe.ui.form.on("Orden Taller", {
	setup(frm) {
		frm.set_query("aseguradora", () => ({ filters: { customer_group: "Aseguradora" } }));
		// En Agencia el cliente es la agencia, no el dueño del vehículo: sin filtro
		frm.set_query("vehiculo", () => ({
			filters: frm.doc.cliente && frm.doc.tipo_flujo !== "Agencia" ? { cliente: frm.doc.cliente } : {},
		}));
		frm.set_query("item_code", "conceptos", () => ({ filters: { disabled: 0, is_sales_item: 1 } }));
	},
	refresh(frm) {
		frm.trigger("botones_erpnext");
		frm.set_df_property("conceptos", "read_only", frm.doc.orden_venta ? 1 : 0);
		frm.set_df_property("cliente", "label", frm.doc.tipo_flujo === "Agencia" ? __("Agencia (cliente)") : __("Cliente"));
		if (frm.doc.tipo_flujo) {
			frm.page.set_indicator(
				`${frm.doc.tipo_flujo} · ${frm.doc.paso_actual || "Nueva"}`,
				COLORES_TIPO[frm.doc.tipo_flujo] || "gray"
			);
		}
		frm.trigger("dibujar_flujo");
	},
	tipo_flujo(frm) {
		frm.trigger("refresh");
	},
	dibujar_flujo(frm) {
		const $wrapper = frm.get_field("flujo_html").$wrapper;
		const pasos = frm.doc.pasos || [];
		if (!pasos.length) {
			$wrapper.html(
				`<div class="text-muted small">${__("Elige el tipo de flujo y guarda la orden para ver sus pasos.")}</div>`
			);
			return;
		}

		const esc = frappe.utils.escape_html;
		const tarjetas = pasos.map((p) => {
			const clases = ["taller-paso"];
			if (p.estado === "Anulado") clases.push("anulado");
			if (p.paso === frm.doc.paso_actual) clases.push("actual");
			const color = COLORES_ESTADO[p.estado] || "var(--border-color)";
			return `<div class="${clases.join(" ")}" style="border-left-color: ${color}">
				<div class="taller-paso-num">${p.idx}</div>
				<div class="taller-paso-nombre">${esc(p.paso)}</div>
				<div class="taller-paso-estado">${esc(p.estado || __("Por iniciar"))}</div>
			</div>`;
		});

		$wrapper.html(`
			<style>
				.taller-flujo { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 8px; margin-bottom: 8px; }
				.taller-flecha { color: var(--text-muted); }
				.taller-paso { min-width: 150px; padding: 10px 14px; border-radius: var(--border-radius-md);
					background: var(--subtle-fg); border: 1px solid var(--border-color); border-left-width: 4px; }
				.taller-paso.actual { box-shadow: 0 0 0 2px var(--primary); }
				.taller-paso.anulado { opacity: 0.55; }
				.taller-paso-num { font-size: var(--text-xs); color: var(--text-muted); }
				.taller-paso-nombre { font-size: var(--text-lg); color: var(--heading-color); }
				.taller-paso.anulado .taller-paso-nombre { color: var(--text-muted); }
				.taller-paso-estado { font-size: var(--text-sm); color: var(--text-color); }
			</style>
			<div class="taller-flujo">${tarjetas.join('<span class="taller-flecha">→</span>')}</div>
		`);
	},
	botones_erpnext(frm) {
		if (frm.is_new() || frm.doc.docstatus === 2) return;
		const doc = frm.doc;
		const crear = __("Crear");
		const aseguradora = doc.tipo_flujo === "Aseguradora";
		const tiene_conceptos = (doc.conceptos || []).length > 0;

		if (tiene_conceptos && !doc.cotizacion && !doc.orden_venta) {
			frm.add_custom_button(__("Cotización"), () => crear_documentos(frm, "crear_cotizacion"), crear);
		}
		const falta_so = !doc.orden_venta || (aseguradora && doc.deducible && !doc.orden_venta_deducible);
		if (tiene_conceptos && falta_so) {
			frm.add_custom_button(__("Orden de venta"), () => crear_documentos(frm, "crear_ordenes_venta"), crear);
		}
		const falta_si =
			(doc.orden_venta && !doc.factura_venta) || (doc.orden_venta_deducible && !doc.factura_deducible);
		if (falta_si) {
			frm.add_custom_button(__("Factura"), () => crear_documentos(frm, "crear_facturas"), crear);
		}
		if (doc.orden_venta) {
			const etiqueta = aseguradora ? __("Cobro aseguradora") : __("Cobro");
			frm.add_custom_button(etiqueta, () => crear_pago(frm, 0), crear);
		}
		if (doc.orden_venta_deducible) {
			frm.add_custom_button(__("Cobro deducible"), () => crear_pago(frm, 1), crear);
		}
		if (doc.valuacion) {
			frm.add_custom_button(__("Valuación"), () => frappe.set_route("Form", "Valuacion Taller", doc.valuacion), __("Ver"));
		}
		if (!doc.valuacion_aprobada && doc.docstatus === 0) {
			frm.add_custom_button(
				__("Valuación"),
				() => frappe.new_doc("Valuacion Taller", { orden_taller: doc.name }),
				crear
			);
		}
		if (doc.proyecto) {
			frm.add_custom_button(__("Consumo de materiales"), () => abrir_nuevo(frm, "taller.erp.costeo.crear_consumo"), crear);
			frm.add_custom_button(__("Proyecto"), () => frappe.set_route("Form", "Project", doc.proyecto), __("Ver"));
			frm.add_custom_button(
				__("Timesheets"),
				() => frappe.set_route("List", "Timesheet", { parent_project: doc.proyecto }),
				__("Ver")
			);
		}
		if (doc.costo_total || doc.ingresos) {
			frm.dashboard.add_indicator(
				__("Margen: {0} ({1}%)", [format_currency(doc.margen), flt(doc.margen_porcentaje, 1)]),
				doc.margen >= 0 ? "green" : "red"
			);
		}
	},
});

function crear_documentos(frm, metodo) {
	const continuar = () =>
		frappe.call({
			method: `${METODOS}.${metodo}`,
			args: { orden: frm.doc.name },
			freeze: true,
			callback(r) {
				const nombres = r.message || [];
				frm.reload_doc();
				frappe.show_alert({ message: __("Creado: {0}", [nombres.join(", ")]), indicator: "green" });
				if (nombres.length === 1) {
					const doctype = { crear_cotizacion: "Quotation", crear_ordenes_venta: "Sales Order" }[metodo] || "Sales Invoice";
					frappe.set_route("Form", doctype, nombres[0]);
				}
			},
		});
	frm.is_dirty() ? frm.save().then(continuar) : continuar();
}

function crear_pago(frm, deducible) {
	abrir_nuevo(frm, `${METODOS}.crear_pago`, { deducible });
}

function abrir_nuevo(frm, metodo, args = {}) {
	frappe.call({
		method: metodo,
		args: { orden: frm.doc.name, ...args },
		freeze: true,
		callback(r) {
			const doc = frappe.model.sync(r.message)[0];
			frappe.set_route("Form", doc.doctype, doc.name);
		},
	});
}

frappe.ui.form.on("Concepto Orden Taller", {
	item_code(frm, cdt, cdn) {
		const fila = locals[cdt][cdn];
		if (!fila.item_code) return;
		frappe.call({
			method: `${METODOS}.precio_articulo`,
			args: { item_code: fila.item_code },
			callback: (r) => frappe.model.set_value(cdt, cdn, "rate", r.message || 0),
		});
	},
	qty: calcular_importe,
	rate: calcular_importe,
	conceptos_remove(frm) {
		calcular_subtotal(frm);
	},
});

function calcular_importe(frm, cdt, cdn) {
	const fila = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(fila.qty) * flt(fila.rate));
	calcular_subtotal(frm);
}

function calcular_subtotal(frm) {
	frm.set_value("subtotal", (frm.doc.conceptos || []).reduce((t, c) => t + flt(c.amount), 0));
}

frappe.ui.form.on("Paso Orden Taller", {
	horas_estimadas(frm) {
		frm.trigger("dibujar_flujo");
	},
});
