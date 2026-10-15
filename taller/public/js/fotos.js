// Visor de fotos de la unidad (tabla Foto Orden Taller) para Orden Taller e Inventario.
// Muestra una cuadrícula de miniaturas por etapa; al tocar una, la foto completa con
// su comentario y botones Anterior / Siguiente.
window.taller_fotos = {
	pintar(frm, campo_html = "fotos_html", campo_tabla = "fotos") {
		const field = frm.get_field(campo_html);
		if (!field) return;
		const esc = frappe.utils.escape_html;
		const fotos = (frm.doc[campo_tabla] || []).filter((f) => f.imagen);
		const etapas = [...new Set(fotos.map((f) => f.etapa || ""))];
		const html =
			etapas
				.map(
					(etapa) => `
			<h6 class="mt-3">${esc(etapa || __("Sin etapa"))}</h6>
			<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px">
				${fotos
					.filter((f) => (f.etapa || "") === etapa)
					.map(
						(f) => `
					<figure style="margin:0">
						<img src="${esc(f.miniatura || f.imagen)}" data-name="${esc(f.name)}" loading="lazy"
							style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px;cursor:pointer">
						<figcaption class="small text-muted ellipsis">${esc(f.angulo || f.zona || "")}</figcaption>
					</figure>`
					)
					.join("")}
			</div>`
				)
				.join("") || `<p class="text-muted">${__("Sin fotos")}</p>`;
		field.$wrapper.html(html);
		field.$wrapper.find("img").on("click", (e) => {
			const i = fotos.findIndex((f) => f.name === e.currentTarget.dataset.name);
			taller_fotos.abrir(fotos, i);
		});
	},
	abrir(fotos, i) {
		const f = fotos[i];
		const esc = frappe.utils.escape_html;
		const d = new frappe.ui.Dialog({
			title: [f.etapa, f.angulo, f.zona].filter(Boolean).join(" · ") || __("Foto"),
			size: "extra-large",
		});
		d.$body.html(`<img src="${esc(f.imagen)}" style="max-width:100%;max-height:75vh;display:block;margin:auto">
			<p class="mt-2">${esc(f.comentario || "")}</p>`);
		if (i < fotos.length - 1) {
			d.set_primary_action(__("Siguiente"), () => {
				d.hide();
				taller_fotos.abrir(fotos, i + 1);
			});
		}
		if (i > 0) {
			d.set_secondary_action_label(__("Anterior"));
			d.set_secondary_action(() => {
				d.hide();
				taller_fotos.abrir(fotos, i - 1);
			});
		}
		d.show();
	},
};

frappe.ui.form.on("Foto Orden Taller", {
	imagen(frm) {
		taller_fotos.pintar(frm);
	},
	fotos_remove(frm) {
		taller_fotos.pintar(frm);
	},
});
