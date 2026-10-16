"""
Tabla de pasos de la Orden Taller.

La tabla `pasos` (DocType hijo "Paso Orden Taller") tiene una fila por cada paso
del flujo de la orden y la mantiene el servidor a partir de `workflow_state`:

  * Al crear la orden (o cambiar el tipo mientras está en Nueva) se generan las
    filas según la secuencia de su tipo de orden y tipo de flujo, con las horas
    de HORAS_ESTIMADAS.
  * Al entrar a un paso, su fila queda En Proceso; los pasos anteriores que no
    se tocaron (p. ej. Recolección cuando no se requiere) quedan Anulados y los
    posteriores se limpian (retrabajo desde Control de calidad).
  * Al salir de En Proceso se suman las horas transcurridas a "Hrs reales" y el
    tramo se registra como Timesheet (taller/erp/costeo.py).
  * Cancelada anula el paso en curso; Reactivar (volver a Nueva) limpia los
    estados pero conserva las horas reales acumuladas.
  * Recolección y Recepción no se completan ni se anulan sin el Inventario de la
    orden enviado (validar_inventario).
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_hours

from taller.flujo.configuracion import (
    ANULADO,
    CAMPO_ESTADO,
    CAMPO_PASOS,
    CAMPO_TIPO_ORDEN,
    COMPLETADO,
    DOCTYPE_INVENTARIO,
    EN_PROCESO,
    ESTADO_CANCELADA,
    ESTADO_INICIAL,
    HORAS_ESTIMADAS,
    PASOS_INVENTARIO,
    paso_de_estado,
    secuencia,
    sufijo_de_estado,
    tipo_orden_de,
    usa_flujo,
)


def sincronizar_pasos(doc):
    anterior = doc.get_doc_before_save()
    destino = doc.get(CAMPO_ESTADO)

    # Un tipo de orden sin secuencia definida no tiene pasos
    if not usa_flujo(doc):
        doc.set(CAMPO_PASOS, [])
        return

    cambio_tipo = anterior and (anterior.tipo_flujo != doc.tipo_flujo
                                or anterior.get(CAMPO_TIPO_ORDEN) != doc.get(CAMPO_TIPO_ORDEN))
    if doc.tipo_flujo and (not doc.get(CAMPO_PASOS)
                           or (cambio_tipo and destino in (None, "", ESTADO_INICIAL))):
        generar_pasos(doc)

    origen = anterior.get(CAMPO_ESTADO) if anterior else None
    if destino and origen != destino:
        aplicar_estado(doc, destino)


def validar_inventario(doc):
    """La orden no sale de su primer paso (Recolección o Recepción) sin el inventario enviado."""
    anterior = doc.get_doc_before_save()
    destino = doc.get(CAMPO_ESTADO)
    if not destino or (anterior and anterior.get(CAMPO_ESTADO) == destino):
        return
    if paso_de_estado(destino) not in PASOS_INVENTARIO or sufijo_de_estado(destino) not in (COMPLETADO, ANULADO):
        return
    if doc.get("inventario") and frappe.db.get_value(DOCTYPE_INVENTARIO, doc.inventario, "docstatus") == 1:
        return
    enlace = frappe.utils.get_link_to_form(DOCTYPE_INVENTARIO, doc.inventario) if doc.get("inventario") else ""
    frappe.throw(_("Envía el inventario de la unidad {0} (firmas y fotos) antes de salir de {1}.")
                 .format(enlace, paso_de_estado(destino)), title=_("Falta el inventario"))


def validar_horas(doc):
    for fila in doc.get(CAMPO_PASOS) or []:
        if flt(fila.horas_reales) < 0 or flt(fila.horas_estimadas) < 0:
            frappe.throw(_("Las horas del paso {0} no pueden ser negativas.").format(fila.paso))


def totalizar_horas(doc):
    """Totales informativos debajo de la tabla de pasos."""
    filas = doc.get(CAMPO_PASOS) or []
    doc.total_horas_estimadas = flt(sum(flt(f.horas_estimadas) for f in filas), 2)
    doc.total_horas_reales = flt(sum(flt(f.horas_reales) for f in filas), 2)


def generar_pasos(doc):
    doc.set(CAMPO_PASOS, [])
    for paso in secuencia(tipo_orden_de(doc), doc.tipo_flujo):
        doc.append(CAMPO_PASOS, {"paso": paso, "horas_estimadas": HORAS_ESTIMADAS.get(paso, 0)})


def aplicar_estado(doc, destino, ahora=None, usuario=None):
    ahora = get_datetime(ahora) if ahora else now_datetime()
    usuario = usuario or frappe.session.user
    filas = doc.get(CAMPO_PASOS) or []

    if destino == ESTADO_INICIAL:
        for fila in filas:
            _cerrar(fila, ahora)
            _limpiar(fila)
        return

    if destino == ESTADO_CANCELADA:
        for fila in filas:
            if fila.estado == EN_PROCESO:
                _marcar(fila, ANULADO, ahora, usuario)
        return

    paso, sufijo = paso_de_estado(destino), sufijo_de_estado(destino)
    actual = next((f for f in filas if f.paso == paso), None)
    if not actual or not sufijo:
        return

    for fila in filas:
        if fila.idx < actual.idx:
            if not fila.estado:
                _marcar(fila, ANULADO, ahora, usuario)
            elif fila.estado == EN_PROCESO:
                _marcar(fila, COMPLETADO, ahora, usuario)
        elif fila.idx > actual.idx and fila.estado:
            _cerrar(fila, ahora)
            _limpiar(fila)

    _marcar(actual, sufijo, ahora, usuario)


def _marcar(fila, estado, ahora, usuario):
    _cerrar(fila, ahora)
    fila.estado = estado
    fila.usuario = usuario
    fila.fecha_hora = ahora
    if estado == EN_PROCESO:
        fila.inicio = ahora
        # El empleado que hace el paso; si ya se capturó a mano, se respeta
        fila.empleado = fila.empleado or empleado_de(usuario)


def empleado_de(usuario):
    """Empleado activo ligado al usuario (campo User ID del Employee), o None."""
    if not usuario:
        return None
    return frappe.db.get_value("Employee", {"user_id": usuario, "status": "Active"})


def _cerrar(fila, ahora):
    """Suma a horas_reales el tiempo que la fila lleva En Proceso.

    El tramo queda en flags.tramos_mano_obra de la orden para que costeo lo
    registre como Timesheet cuando el guardado termine bien.
    """
    if fila.estado == EN_PROCESO and fila.inicio:
        horas = max(time_diff_in_hours(ahora, fila.inicio), 0)
        fila.horas_reales = flt(fila.horas_reales) + horas
        orden = getattr(fila, "parent_doc", None)
        if orden is not None:
            orden.flags.setdefault("tramos_mano_obra", []).append({
                "paso": fila.paso, "inicio": get_datetime(fila.inicio), "fin": ahora,
                "horas": horas, "usuario": frappe.session.user, "empleado": fila.get("empleado"),
            })
    fila.inicio = None


def _limpiar(fila):
    fila.estado = None
    fila.usuario = None
    fila.empleado = None
    fila.fecha_hora = None
