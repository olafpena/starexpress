// VIN: dígito verificador al capturar (offline) y prellenado con ultravin (servidor).
// Se carga en Vehiculo Taller, Inventario y Valuacion Taller (hooks.py -> doctype_js);
// la bandera evita registrar los eventos más de una vez.
if (!window.taller_vin) {
	const VALORES = {};
	"0123456789".split("").forEach((c, i) => (VALORES[c] = i));
	"ABCDEFGH".split("").forEach((c, i) => (VALORES[c] = i + 1));
	"JKLMN".split("").forEach((c, i) => (VALORES[c] = i + 1));
	VALORES.P = 7;
	VALORES.R = 9;
	"STUVWXYZ".split("").forEach((c, i) => (VALORES[c] = i + 2));
	const PESOS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2];
	const CAMPOS = ["marca", "modelo", "anio", "version", "carroceria", "pais_fabricacion"];

	const revisar = (vin) => {
		if (vin.length !== 17) return { ok: false, texto: __("El VIN debe tener 17 caracteres (tiene {0}).", [vin.length]) };
		if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) return { ok: false, texto: __("El VIN solo admite letras y números, sin I, O ni Q.") };
		const residuo = vin.split("").reduce((t, c, i) => t + VALORES[c] * PESOS[i], 0) % 11;
		const esperado = residuo === 10 ? "X" : String(residuo);
		if (vin[8] === esperado) return { ok: true, texto: __("Dígito verificador correcto.") };
		const nota = "12345".includes(vin[0]) ? "" : " " + __("(VIN no norteamericano: puede no usar dígito verificador)");
		return { ok: false, texto: __("Dígito verificador {0}, debería ser {1}.", [vin[8], esperado]) + nota };
	};

	window.taller_vin = {
		// Avisa si la marca capturada no es la del VIN (el servidor también avisa al guardar)
		comparar_marca(frm, marca_vin) {
			if (!marca_vin || !frm.doc.marca) return;
			frappe
				.call({ method: "taller.vehiculo.vin.comparar_marca", args: { marca: frm.doc.marca, marca_vin } })
				.then(({ message }) => {
					if (message === false) {
						frappe.show_alert(
							{ message: __("La marca capturada es {0}, pero el VIN corresponde a {1}.", [frm.doc.marca, marca_vin]), indicator: "orange" },
							8
						);
					}
				});
		},
		al_cambiar(frm) {
			const original = frm.doc.vin || "";
			const vin = original.replace(/[\s-]/g, "").toUpperCase();
			if (vin !== original) {
				frm.set_value("vin", vin);
				return;
			}
			if (!vin) {
				frm.set_df_property("vin", "description", "");
				return;
			}
			const r = revisar(vin);
			const color = r.ok ? "var(--green-600)" : "var(--red-600)";
			frm.set_df_property("vin", "description", `<span style="color: ${color}">${frappe.utils.escape_html(r.texto)}</span>`);
			if (vin.length !== 17 || frm.doc.docstatus !== 0) return;
			frappe.call({ method: "taller.vehiculo.vin.consultar_vin", args: { vin } }).then(({ message }) => {
				if (!message || frm.doc.vin !== vin || message.bloquea) return;
				const llenados = [];
				CAMPOS.forEach((campo) => {
					const valor = (message.datos || {})[campo];
					if (valor && frm.fields_dict[campo] && !frm.doc[campo]) {
						frm.set_value(campo, valor);
						llenados.push(valor);
					}
				});
				if (llenados.length) {
					frappe.show_alert({ message: __("Datos del VIN: {0}", [llenados.join(" · ")]), indicator: "green" });
				}
				window.taller_vin.comparar_marca(frm, (message.datos || {}).marca);
			});
		},
	};

	["Vehiculo Taller", "Inventario", "Valuacion Taller"].forEach((doctype) =>
		frappe.ui.form.on(doctype, { vin: (frm) => window.taller_vin.al_cambiar(frm) })
	);
}
