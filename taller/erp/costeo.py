"""
Fase 2: costeo de la Orden Taller.

Cada orden tiene un Project de ERPNext (centro de costo del taller). Todo lo que
genera la orden lleva ese proyecto: cotización, orden de venta, factura, pagos,
consumos de material y horas, así que también se puede ver en los reportes
estándar (Estado de resultados filtrado por proyecto, Project).

    ingresos         facturas enviadas de la orden, sin IVA
    costo materiales salidas de inventario con el proyecto (materiales facturados
                     y consumibles), menos devoluciones
    costo mano obra  Timesheets enviados con el proyecto; se registran solos cada
                     vez que un paso sale de En Proceso (Activity Type "Taller - <paso>")
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, getdate

from taller.erp.configuracion_empresa import CENTRO_COSTO_TALLER, actividad, almacen_predeterminado

DOCTYPE = "Orden Taller"
MINIMO_HORAS = 1 / 60  # tramos de menos de un minuto no generan Timesheet

CAMPOS_COSTEO = ["costo_materiales", "costo_mano_obra", "costo_total", "margen", "margen_porcentaje"]


# ==========================================================================
# Proyecto de la orden
# ==========================================================================
def crear_proyecto(doc):
    if doc.proyecto or not doc.company:
        return
    abbr = frappe.get_cached_value("Company", doc.company, "abbr")
    centro_costo = f"{CENTRO_COSTO_TALLER} - {abbr}"
    proyecto = frappe.get_doc({
        "doctype": "Project",
        "project_name": f"{doc.name} - {doc.cliente_nombre or doc.cliente}",
        "company": doc.company,
        # Sin customer: ERPNext exige que todo documento del proyecto sea de ese
        # cliente, y Aseguradora factura a dos (aseguradora y asegurado).
        "cost_center": centro_costo if frappe.db.exists("Cost Center", centro_costo) else None,
        "expected_start_date": getdate(doc.fecha_ingreso) if doc.fecha_ingreso else None,
        "status": "Open",
    }).insert(ignore_permissions=True)
    doc.db_set("proyecto", proyecto.name, update_modified=False)


def actualizar_estado_proyecto(doc):
    if not doc.proyecto:
        return
    if doc.docstatus == 1:
        estado = "Completed"
    elif doc.workflow_state == "Cancelada":
        estado = "Cancelled"
    else:
        estado = "Open"
    if frappe.db.get_value("Project", doc.proyecto, "status") != estado:
        frappe.db.set_value("Project", doc.proyecto, "status", estado)


# ==========================================================================
# Mano de obra: un Timesheet por cada tramo En Proceso de un paso
# ==========================================================================
def registrar_mano_obra(doc):
    """Crea los Timesheets de los tramos que cerró este guardado (ver flujo/pasos.py)."""
    tramos = doc.flags.pop("tramos_mano_obra", None) or []
    if not doc.proyecto:
        return
    for tramo in tramos:
        if tramo["horas"] < MINIMO_HORAS:
            continue
        frappe.db.savepoint("timesheet_taller")
        try:
            crear_timesheet(doc, tramo)
        except Exception:
            frappe.db.rollback(save_point="timesheet_taller")
            # La mano de obra nunca debe frenar el avance del workflow
            frappe.log_error(f"Timesheet de {doc.name} ({tramo['paso']})")
            frappe.msgprint(_("No se pudo registrar la mano de obra de {0}; revisa el Error Log.")
                            .format(tramo["paso"]), indicator="orange", alert=True)


def crear_timesheet(doc, tramo):
    tipo_actividad = actividad(tramo["paso"])
    empleado = frappe.db.get_value("Employee", {"user_id": tramo["usuario"], "status": "Active"})
    ts = frappe.get_doc({
        "doctype": "Timesheet",
        "company": doc.company,
        "parent_project": doc.proyecto,
        "employee": empleado,
        "note": _("{0}: {1}").format(doc.name, tramo["paso"]),
        "time_logs": [{
            "activity_type": tipo_actividad if frappe.db.exists("Activity Type", tipo_actividad) else None,
            "from_time": tramo["inicio"],
            "to_time": tramo["fin"],
            "hours": flt(tramo["horas"], 4),
            "project": doc.proyecto,
            "is_billable": 0,
            "description": tramo["paso"],
        }],
    })
    ts.insert(ignore_permissions=True)
    ts.submit()
    return ts.name


# ==========================================================================
# Montos de costeo
# ==========================================================================
def calcular_costeo(doc):
    """Requiere doc.ingresos (lo calcula documentos.calcular_montos)."""
    materiales = mano_obra = 0
    if doc.proyecto:
        materiales = -flt(frappe.db.sql(
            """select sum(stock_value_difference) from `tabStock Ledger Entry`
               where project = %s and is_cancelled = 0""", doc.proyecto)[0][0])
        mano_obra = flt(frappe.db.sql(
            """select sum(d.costing_amount) from `tabTimesheet Detail` d
               join `tabTimesheet` t on t.name = d.parent
               where d.project = %s and t.docstatus = 1""", doc.proyecto)[0][0])

    doc.costo_materiales = flt(materiales, 2)
    doc.costo_mano_obra = flt(mano_obra, 2)
    doc.costo_total = doc.costo_materiales + doc.costo_mano_obra
    doc.margen = flt(doc.ingresos) - doc.costo_total
    doc.margen_porcentaje = flt(doc.margen / doc.ingresos * 100, 2) if flt(doc.ingresos) else 0


# ==========================================================================
# Consumo de materiales desde la orden
# ==========================================================================
@frappe.whitelist()
def crear_consumo(orden):
    doc = frappe.get_doc(DOCTYPE, orden)
    doc.check_permission("write")
    if not doc.proyecto:
        frappe.throw(_("La orden no tiene proyecto."))
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Issue"
    se.purpose = "Material Issue"
    se.company = doc.company
    se.project = doc.proyecto
    se.from_warehouse = almacen_predeterminado(doc.company)
    se.remarks = _("Consumo de materiales de la orden {0}").format(doc.name)
    return se


# ==========================================================================
# Eventos (hooks.py -> doc_events)
# ==========================================================================
def al_cambiar_consumo(doc, method=None):
    _actualizar_por_proyectos({doc.get("project")} | {d.get("project") for d in doc.get("items", [])})


def al_cambiar_timesheet(doc, method=None):
    _actualizar_por_proyectos({doc.get("parent_project")} | {d.project for d in doc.time_logs})


def _actualizar_por_proyectos(proyectos):
    from taller.erp.documentos import actualizar_orden

    for proyecto in filter(None, proyectos):
        orden = frappe.db.get_value(DOCTYPE, {"proyecto": proyecto})
        if orden:
            actualizar_orden(orden)
