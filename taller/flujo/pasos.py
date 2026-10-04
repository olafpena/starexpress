"""
Tabla de pasos de la Orden Taller.

La tabla `pasos` (DocType hijo "Paso Orden Taller") tiene una fila por cada paso
del flujo de la orden y la mantiene el servidor a partir de `workflow_state`:

  * Al crear la orden (o cambiar el tipo mientras está en Nueva) se generan las
    filas según FLUJOS[tipo_flujo] con las horas de HORAS_ESTIMADAS.
  * Al entrar a un paso, su fila queda En Proceso; los pasos anteriores que no
    se tocaron (p. ej. Recolección cuando no se requiere) quedan Anulados y los
    posteriores se limpian (retrabajo desde Control de calidad).
  * Al salir de En Proceso se suman las horas transcurridas a "Hrs reales" y el
    tramo se registra como Timesheet (taller/erp/costeo.py).
  * Cancelada anula el paso en curso; Reactivar (volver a Nueva) limpia los
    estados pero conserva las horas reales acumuladas.
"""

import frappe
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_hours

from taller.flujo.configuracion import (
    ANULADO,
    CAMPO_ESTADO,
    CAMPO_PASOS,
    COMPLETADO,
    EN_PROCESO,
    ESTADO_CANCELADA,
    ESTADO_INICIAL,
    FLUJOS,
    HORAS_ESTIMADAS,
    paso_de_estado,
    sufijo_de_estado,
)


def sincronizar_pasos(doc):
    anterior = doc.get_doc_before_save()
    destino = doc.get(CAMPO_ESTADO)

    cambio_tipo = anterior and anterior.tipo_flujo != doc.tipo_flujo
    if doc.tipo_flujo and (not doc.get(CAMPO_PASOS)
                           or (cambio_tipo and destino in (None, "", ESTADO_INICIAL))):
        generar_pasos(doc)

    origen = anterior.get(CAMPO_ESTADO) if anterior else None
    if destino and origen != destino:
        aplicar_estado(doc, destino)


def generar_pasos(doc):
    doc.set(CAMPO_PASOS, [])
    for paso in FLUJOS.get(doc.tipo_flujo) or []:
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
                "horas": horas, "usuario": frappe.session.user,
            })
    fila.inicio = None


def _limpiar(fila):
    fila.estado = None
    fila.usuario = None
    fila.fecha_hora = None
