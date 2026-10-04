frappe.query_reports["Rentabilidad Orden Taller"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Compañía"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "desde",
			label: __("Desde"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{ fieldname: "hasta", label: __("Hasta"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{
			fieldname: "tipo_flujo",
			label: __("Tipo"),
			fieldtype: "Select",
			options: "\nAgencia\nParticular\nAseguradora",
		},
		{ fieldname: "cliente", label: __("Cliente"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "solo_facturadas", label: __("Solo facturadas"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (["margen", "margen_porcentaje"].includes(column.fieldname) && data && flt(data.margen) < 0) {
			value = `<span style="color: var(--red-500)">${value}</span>`;
		}
		return value;
	},
};
