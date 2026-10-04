"""
Cambia el catálogo de estados por paso de
Pendiente / En Proceso / En Espera / Completado a En Proceso / Completado / Anulado:

  * reconstruye el workflow,
  * mueve las órdenes en Pendiente o En Espera a En Proceso del mismo paso,
  * genera la tabla de pasos de las órdenes existentes,
  * borra los Workflow State y acciones que ya no se usan.
"""

import frappe

from taller.flujo import configuracion as conf
from taller.flujo.pasos import aplicar_estado, generar_pasos

ESTADOS_OBSOLETOS = ["Pendiente", "En Espera"]
ACCIONES_OBSOLETAS = ["Iniciar", "Pausar", "Reanudar"]


def execute():
    conf.instalar(reconstruir=True)

    for nombre in frappe.get_all(conf.DOCTYPE, pluck="name"):
        migrar_orden(frappe.get_doc(conf.DOCTYPE, nombre))

    for paso in conf.PASOS:
        for sufijo in ESTADOS_OBSOLETOS:
            borrar("Workflow State", conf.estado(paso, sufijo))
    for accion in ACCIONES_OBSOLETAS:
        borrar("Workflow Action Master", accion)


def migrar_orden(doc):
    estado = doc.get(conf.CAMPO_ESTADO)
    if conf.sufijo_de_estado(estado) in ESTADOS_OBSOLETOS:
        estado = conf.estado(conf.paso_de_estado(estado), conf.EN_PROCESO)

    generar_pasos(doc)
    # Los pasos anteriores al actual ya se recorrieron: se dan por completados,
    # salvo Recolección cuando la orden no la requería.
    actual = next((f for f in doc.pasos if f.paso == conf.paso_de_estado(estado)), None)
    for fila in doc.pasos:
        if actual and fila.idx < actual.idx:
            if fila.paso == conf.PASO_RECOLECCION and not doc.requiere_recoleccion:
                continue
            fila.estado = conf.COMPLETADO
    if estado:
        aplicar_estado(doc, estado, ahora=doc.modified, usuario=doc.modified_by)

    doc.db_set(conf.CAMPO_ESTADO, estado, update_modified=False)
    frappe.db.delete("Paso Orden Taller", {"parent": doc.name, "parenttype": conf.DOCTYPE})
    for fila in doc.pasos:
        fila.db_insert()


def borrar(doctype, nombre):
    if not frappe.db.exists(doctype, nombre):
        return
    try:
        frappe.delete_doc(doctype, nombre, ignore_permissions=True)
    except frappe.LinkExistsError:
        # Alguna regla o documento lo sigue usando: se deja.
        frappe.clear_last_message()
