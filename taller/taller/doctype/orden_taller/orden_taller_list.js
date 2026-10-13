// Lista de Orden Taller: la columna Estatus con el color de su catálogo (Estatus Orden Taller).
// El indicador de la izquierda sigue mostrando el paso del workflow.
frappe.listview_settings["Orden Taller"] = {
	add_fields: ["estatus"],
	onload(listview) {
		frappe.db.get_list("Estatus Orden Taller", { fields: ["name", "color"], limit: 0 }).then((filas) => {
			listview.taller_colores = Object.fromEntries(filas.map((f) => [f.name, (f.color || "gray").toLowerCase()]));
			listview.refresh();
		});
	},
	formatters: {
		estatus(value, df, doc) {
			if (!value) return "";
			const lista = cur_list && cur_list.doctype === "Orden Taller" ? cur_list : null;
			const color = (lista && lista.taller_colores && lista.taller_colores[value]) || "gray";
			const texto = frappe.utils.escape_html(__(value));
			return `<span class="indicator-pill ${color} filterable no-indicator-dot ellipsis"
				data-filter="estatus,=,${frappe.utils.escape_html(value)}" title="${texto}"><span class="ellipsis">${texto}</span></span>`;
		},
	},
};
