"""Ingresos, costos y margen por Orden Taller, con horas estimadas contra reales."""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt


def execute(filters=None):
    filters = frappe._dict(filters or {})
    return columnas(), datos(filters), None, grafica(filters)


def columnas():
    def col(fieldname, label, fieldtype="Currency", width=120, **kw):
        return {"fieldname": fieldname, "label": _(label), "fieldtype": fieldtype, "width": width, **kw}

    return [
        col("orden", "Orden", "Link", 140, options="Orden Taller"),
        col("fecha_ingreso", "Ingreso", "Date", 95),
        col("tipo_orden", "Tipo de orden", "Data", 150),
        col("tipo_flujo", "Tipo", "Data", 100),
        col("cliente_nombre", "Cliente", "Data", 160),
        col("paso_actual", "Paso", "Data", 120),
        col("ingresos", "Ingresos"),
        col("costo_materiales", "Materiales"),
        col("costo_mano_obra", "Mano de obra"),
        col("costo_total", "Costo total"),
        col("margen", "Margen"),
        col("margen_porcentaje", "Margen %", "Percent", 90),
        col("horas_estimadas", "Hrs est.", "Float", 85),
        col("horas_reales", "Hrs reales", "Float", 85),
    ]


def datos(filters):
    condiciones = {"docstatus": ["<", 2]}
    for campo in ("company", "tipo_orden", "tipo_flujo", "cliente"):
        if filters.get(campo):
            condiciones[campo] = filters.get(campo)
    if filters.get("desde") and filters.get("hasta"):
        condiciones["fecha_ingreso"] = ["between", [filters.desde, f"{filters.hasta} 23:59:59"]]
    if filters.get("solo_facturadas"):
        condiciones["facturado"] = 1

    ordenes = frappe.get_list("Orden Taller", filters=condiciones, order_by="fecha_ingreso desc", fields=[
        "name as orden", "fecha_ingreso", "tipo_orden", "tipo_flujo", "cliente_nombre", "paso_actual", "ingresos",
        "costo_materiales", "costo_mano_obra", "costo_total", "margen", "margen_porcentaje"])
    if not ordenes:
        return []

    paso = frappe.qb.DocType("Paso Orden Taller")
    horas = (
        frappe.qb.from_(paso)
        .select(paso.parent, Sum(paso.horas_estimadas).as_("estimadas"), Sum(paso.horas_reales).as_("reales"))
        .where((paso.parenttype == "Orden Taller") & paso.parent.isin([o.orden for o in ordenes]))
        .groupby(paso.parent)
    ).run(as_dict=True)
    horas = {h.parent: h for h in horas}
    for o in ordenes:
        h = horas.get(o.orden) or {}
        o.horas_estimadas = flt(h.get("estimadas"), 2)
        o.horas_reales = flt(h.get("reales"), 2)
    return ordenes


def grafica(filters):
    filas = datos(filters)
    por_tipo = {}
    for f in filas:
        t = por_tipo.setdefault(f.tipo_flujo or "-", [0, 0])
        t[0] += flt(f.ingresos)
        t[1] += flt(f.costo_total)
    if not por_tipo:
        return None
    return {
        "data": {
            "labels": list(por_tipo),
            "datasets": [
                {"name": _("Ingresos"), "values": [v[0] for v in por_tipo.values()]},
                {"name": _("Costo total"), "values": [v[1] for v in por_tipo.values()]},
            ],
        },
        "type": "bar",
        "fieldtype": "Currency",
    }
