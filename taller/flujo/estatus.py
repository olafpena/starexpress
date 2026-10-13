"""
Estatus de la Orden Taller (catálogo Estatus Orden Taller).

Toda orden nace Activa. Se puede cambiar a mano en cualquier momento (también en
órdenes ya terminadas), y el workflow lo actualiza solo en tres transiciones:

    Cancelar                     -> Cancelado
    completar el último paso     -> Terminado (la orden queda enviada)
    Reactivar (desde Cancelada)  -> Activo

Fuera de esas transiciones se respeta el estatus que haya capturado el usuario.
"""

from taller.flujo.configuracion import (
    CAMPO_ESTADO,
    CAMPO_ESTATUS,
    ESTADO_CANCELADA,
    ESTATUS_ACTIVO,
    ESTATUS_CANCELADO,
    ESTATUS_TERMINADO,
    estados_finales,
)


def sincronizar_estatus(doc):
    if not doc.get(CAMPO_ESTATUS):
        doc.set(CAMPO_ESTATUS, ESTATUS_ACTIVO)

    anterior = doc.get_doc_before_save()
    origen = anterior.get(CAMPO_ESTADO) if anterior else None
    destino = doc.get(CAMPO_ESTADO)
    if not destino or origen == destino:
        return

    if destino == ESTADO_CANCELADA:
        doc.set(CAMPO_ESTATUS, ESTATUS_CANCELADO)
    elif destino in estados_finales():
        doc.set(CAMPO_ESTATUS, ESTATUS_TERMINADO)
    elif origen == ESTADO_CANCELADA:
        doc.set(CAMPO_ESTATUS, ESTATUS_ACTIVO)
