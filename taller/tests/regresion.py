"""
Regresión de la app taller sobre un sitio real, sin dejar rastro.

Cada caso corre dentro de un savepoint y se revierte al terminar; al final se
hace rollback de todo, así que no queda ningún documento ni movimiento.

    bench --site <sitio> execute taller.tests.regresion.correr
    bench --site <sitio> execute taller.tests.regresion.correr --kwargs "{'pdf': '/ruta/VALUACION.pdf'}"

Requiere la compañía configurada (taller.erp.configuracion_empresa.configurar).
El caso de Audatex solo corre si se pasa la ruta de un PDF de valuación.
"""

import base64
import io
import traceback

import frappe
from frappe.model.workflow import apply_workflow, get_transitions
from frappe.utils import add_to_date, flt, now_datetime, nowdate

from taller import fotos as fotos_unidad
from taller.erp import costeo, documentos
from taller.flujo import configuracion as conf

HYP, MECANICA, AMBOS = conf.TIPO_ORDEN_FLUJO, conf.TIPO_ORDEN_MECANICA, conf.TIPO_ORDEN_AMBOS
VIN_TOYOTA = "2T3J1RFV6SW586811"  # RAV4 2025, dígito verificador 6
ALMACEN = None
CASOS = []


def caso(funcion):
    CASOS.append(funcion)
    return funcion


class Fallo(AssertionError):
    pass


def verifica(condicion, mensaje):
    if not condicion:
        raise Fallo(mensaje)


def bloquea(funcion, texto=None):
    """La llamada debe fallar con ValidationError (y el mensaje contener `texto`)."""
    frappe.local.message_log = []
    try:
        funcion()
    except frappe.ValidationError as e:
        mensajes = " ".join(str(m.get("message") if isinstance(m, dict) else m) for m in frappe.local.message_log)
        frappe.local.message_log = []
        if texto:
            verifica(texto in mensajes or texto in str(e), f"bloqueó, pero sin el mensaje esperado ({texto!r}): {mensajes or e}")
        return
    raise Fallo("se esperaba un bloqueo y la operación pasó")


def avisos():
    mensajes = [str(m.get("message") if isinstance(m, dict) else m) for m in frappe.local.message_log]
    frappe.local.message_log = []
    return " ".join(mensajes)


# ==========================================================================
# Ayudantes
# ==========================================================================
def cliente(nombre, grupo="Particular"):
    return frappe.get_doc({"doctype": "Customer", "customer_name": f"REG {nombre}",
                           "customer_group": grupo}).insert().name


def orden(inventario=True, **campos):
    """Orden nueva; con inventario=True además levanta y envía su inventario."""
    datos = {"doctype": "Orden Taller", "tipo_orden": HYP, "tipo_flujo": "Particular"}
    datos.update(campos)
    if "cliente" not in datos:
        datos["cliente"] = cliente("Cliente")
    o = frappe.get_doc(datos).insert()
    if inventario:
        levantar_inventario(o)
        o.reload()
    return o


def jpeg(color=(200, 30, 30), lado=1200):
    from PIL import Image

    salida = io.BytesIO()
    Image.new("RGB", (lado, lado), color).save(salida, format="JPEG", quality=95)
    return salida.getvalue()


def foto_de_celular():
    """JPEG con ruido de unos 1.5 MB, como una foto de celular sin optimizar."""
    import os

    from PIL import Image

    salida = io.BytesIO()
    Image.frombytes("RGB", (1200, 1200), os.urandom(1200 * 1200 * 3)).save(salida, format="JPEG", quality=95)
    return salida.getvalue()


def firma():
    from PIL import Image

    salida = io.BytesIO()
    Image.new("RGB", (40, 20), (0, 0, 0)).save(salida, format="PNG")
    return "data:image/png;base64," + base64.b64encode(salida.getvalue()).decode()


def subir_foto(doctype, nombre, contenido=None, privado=0):
    """Sube una foto como lo haría la API (por omisión pública, para probar que se vuelve privada)."""
    return frappe.get_doc({"doctype": "File", "file_name": f"reg_{frappe.generate_hash(length=6)}.jpg",
                           "attached_to_doctype": doctype, "attached_to_name": nombre, "is_private": privado,
                           "content": contenido or jpeg()}).insert().file_url


def levantar_inventario(o, enviar=True, **campos):
    inv = frappe.get_doc(conf.DOCTYPE_INVENTARIO, o.inventario)
    url = subir_foto(inv.doctype, inv.name)
    for angulo in conf.ANGULOS_OBLIGATORIOS:
        inv.append("fotos", {"imagen": url, "angulo": angulo})
    inv.update({"firma_entrega": firma(), "firma_recibe": firma(), "nombre_entrega": "Cliente REG"})
    inv.update(campos)
    inv.save()
    if enviar:
        inv.submit()
    return inv


def valuacion_manual(o, partidas=None):
    v = frappe.get_doc({
        "doctype": "Valuacion Taller", "orden_taller": o.name, "origen": "Captura manual",
        "partidas": partidas or [
            {"tipo": "Mano de obra hojalatería", "descripcion": "Reparar facia", "cantidad": 2, "precio_unitario": 450},
            {"tipo": "Otro", "descripcion": "Lavado", "cantidad": 1, "precio_unitario": 250},
        ],
    }).insert()
    v.submit()
    o.reload()
    return v


def avanza(o, *acciones):
    for accion in acciones:
        o = apply_workflow(o, accion)
    return o


def retrocede_inicio(o, paso, horas):
    fila = next(f for f in o.pasos if f.paso == paso)
    frappe.db.set_value("Paso Orden Taller", fila.name, "inicio", add_to_date(now_datetime(), hours=-horas))
    o.reload()


def enviar(doctype, nombre):
    d = frappe.get_doc(doctype, nombre)
    d.submit()
    return d


def pagar(o, monto=None, deducible=0):
    pe = frappe.get_doc(documentos.crear_pago(o.name, deducible))
    if monto:
        pe.paid_amount = pe.received_amount = monto
        pe.references[0].allocated_amount = monto
    pe.reference_no, pe.reference_date = "REG", nowdate()
    pe.insert()
    pe.submit()
    return pe


def recibir_inventario(item_code, qty, tarifa):
    frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
                    "company": frappe.defaults.get_global_default("company"),
                    "items": [{"item_code": item_code, "qty": qty, "t_warehouse": ALMACEN,
                               "basic_rate": tarifa}]}).insert().submit()


def gl(voucher):
    filas = frappe.get_all("GL Entry", filters={"voucher_no": voucher, "is_cancelled": 0},
                           fields=["account", "debit", "credit"])
    return {f.account.rsplit(" - ", 1)[0]: flt(f.debit) - flt(f.credit) for f in filas}


def hasta_cobro(o):
    """Recorre el flujo de Hojalatería y Pintura desde Nueva hasta Cobro - En Proceso."""
    return avanza(o, "Enviar a Recepción", "Completar", "Enviar a Carrocería", "Completar",
                  "Enviar a Preparación", "Completar", "Enviar a Pintura", "Completar", "Enviar a Armado",
                  "Completar", "Enviar a Pulido", "Completar", "Enviar a Control de calidad", "Completar",
                  "Enviar a Lavado", "Completar", "Enviar a Entrega", "Completar", "Enviar a Cobro")


# ==========================================================================
# Casos
# ==========================================================================
@caso
def configuracion_del_workflow():
    wf = frappe.get_doc("Workflow", conf.NOMBRE_WORKFLOW)
    verifica(wf.is_active and wf.document_type == conf.DOCTYPE, "el workflow no está activo en Orden Taller")
    # Con developer_mode el DocType se edita en el Desk: el campo del workflow debe seguir ahí
    verifica(frappe.get_meta(conf.DOCTYPE).get_field(conf.CAMPO_ESTADO),
             f"falta el campo {conf.CAMPO_ESTADO} en {conf.DOCTYPE}: el workflow no puede asignar estados")
    for t in wf.transitions:
        if t.action in conf.ACCIONES_GENERALES:
            verifica("tipo_orden" not in (t.condition or ""), f"{t.action} no debe depender del tipo de orden")
        else:
            verifica("doc.tipo_orden" in (t.condition or ""), f"falta la condición de tipo de orden en {t.state} → {t.action}")
    generadas = {(t["state"], t["action"], t["next_state"], t["allowed"]): t["condition"] for t in conf.construir_transiciones()}
    distintas = [(t.state, t.action) for t in wf.transitions
                 if generadas.get((t.state, t.action, t.next_state, t.allowed), "falta") != t.condition]
    verifica(not distintas, f"el workflow del sitio no coincide con el generador: {distintas[:3]}")
    recoleccion = [t.condition for t in wf.transitions if t.state == conf.ESTADO_INICIAL and "recoleccion" in (t.condition or "")]
    verifica(len(recoleccion) == 4, f"se perdieron las condiciones de recolección ({len(recoleccion)} de 4)")
    redondeo = {dt: frappe.new_doc(dt).disable_rounded_total for dt in ("Quotation", "Sales Order", "Sales Invoice")}
    verifica(all(redondeo.values()), f"los documentos de venta deben nacer sin redondeo al peso: {redondeo}")
    sin_tipo = frappe.get_all("Orden Taller", filters={"tipo_orden": ["in", ["", None]]}, pluck="name")
    verifica(not sin_tipo, f"órdenes sin tipo de orden: {sin_tipo}")


def estado_paso(o):
    return {p.paso: p.estado for p in o.pasos}


def acciones(o):
    return {t.action for t in get_transitions(o)}


@caso
def pasos_compartidos_entre_tipos_de_orden():
    hyp = avanza(orden(placas="REG10"), "Enviar a Recepción")
    mec = avanza(orden(tipo_orden=MECANICA, placas="REG11"), "Enviar a Recepción")
    verifica(hyp.workflow_state == mec.workflow_state == "Recepción - En Proceso", "Recepción debe ser el mismo estado")
    verifica([p.paso for p in mec.pasos] == conf.SECUENCIA_MECANICA, f"pasos de Mecánica {[p.paso for p in mec.pasos]}")
    verifica(estado_paso(mec)["Recepción"] == "En Proceso", "la tabla de pasos de Mecánica no avanzó")
    valuacion_manual(hyp)
    hyp = avanza(hyp, "Completar")
    mec = avanza(mec, "Completar")  # Mecánica no requiere valuación
    verifica(acciones(hyp) >= {"Enviar a Carrocería"} and "Enviar a Diagnóstico" not in acciones(hyp), f"HyP: {acciones(hyp)}")
    verifica("Enviar a Diagnóstico" in acciones(mec) and "Enviar a Carrocería" not in acciones(mec), f"Mecánica: {acciones(mec)}")
    bloquea(lambda: apply_workflow(mec, "Enviar a Carrocería"))
    bloquea(lambda: frappe.get_doc({"doctype": "Valuacion Taller", "orden_taller": mec.name, "origen": "Captura manual",
                                    "partidas": [{"tipo": "Otro", "descripcion": "x", "cantidad": 1,
                                                  "precio_unitario": 1}]}).insert(),
            "flujo de Hojalatería y Pintura")


@caso
def mecanica_flujo_completo_con_contabilidad():
    recibir_inventario("MAT-PRIMER", 5, 200)
    o = orden(tipo_orden=MECANICA, vin=VIN_TOYOTA, conceptos=[{"item_code": "MO-HOJ", "qty": 2},
                                                              {"item_code": "MAT-PRIMER", "qty": 1}])
    verifica(o.marca == "TOYOTA", "el VIN no prellenó la marca en Mecánica")
    o = avanza(o, "Enviar a Recepción", "Completar", "Enviar a Diagnóstico")
    retrocede_inicio(o, "Diagnóstico", 1)
    bloquea(lambda: apply_workflow(o, "Completar"), "diagnóstico")
    o.reload()
    o.diagnostico = "Falla en balatas delanteras"
    o.save()
    o = avanza(o, "Completar", "Enviar a Cotización")
    bloquea(lambda: apply_workflow(o, "Completar"), "cotización")
    o.reload()
    enviar("Quotation", documentos.crear_cotizacion(o.name)[0])
    o = avanza(o, "Completar", "Enviar a Autorización del cliente")
    bloquea(lambda: apply_workflow(o, "Completar"), "autorizar")
    o.reload()
    so = enviar("Sales Order", documentos.crear_ordenes_venta(o.name)[0])
    o.reload()
    verifica(o.presupuesto_aprobado, "la orden de venta enviada debe marcar Presupuesto aprobado")
    pagar(o, 500)
    o = avanza(o, "Completar", "Enviar a Refacciones", "Completar", "Enviar a Reparación")
    retrocede_inicio(o, "Reparación", 2)
    o = avanza(o, "Completar", "Enviar a Hallazgo adicional")

    # Hallazgo: se agrega trabajo a la orden de venta enviada con "Actualizar artículos"
    bloquea(lambda: apply_workflow(o, "Completar"), "hallazgo")
    o.reload()
    o.hallazgo_adicional = "Disco delantero rayado"
    o.save()
    from erpnext.controllers.accounts_controller import update_child_qty_rate
    so.reload()
    filas = [{"docname": i.name, "item_code": i.item_code, "qty": i.qty, "rate": i.rate} for i in so.items]
    filas.append({"item_code": "SRV-PUL", "qty": 1, "rate": 800, "delivery_date": nowdate()})
    update_child_qty_rate("Sales Order", frappe.as_json(filas), so.name)
    o.reload()
    esperado = flt((900 + 380 + 800) * 1.16, 2)
    verifica(flt(o.monto_total) == esperado, f"total tras el hallazgo {o.monto_total}, esperado {esperado}")
    o = avanza(o, "Completar", "Enviar a Control de calidad y ruta")
    bloquea(lambda: apply_workflow(o, "Completar"), "prueba de ruta")
    o.reload()
    o = avanza(o, "Retrabajo a Reparación")
    verifica(estado_paso(o)["Hallazgo adicional"] is None and estado_paso(o)["Reparación"] == "En Proceso",
             f"retrabajo: {estado_paso(o)}")
    o = avanza(o, "Completar", "Enviar a Hallazgo adicional", "Anular", "Enviar a Control de calidad y ruta")
    o.reload()
    o.update({"checklist_calidad_ok": 1, "recibido_por": "Cliente", "fecha_entrega": now_datetime()})
    o.save()
    o = avanza(o, "Completar", "Enviar a Lavado", "Completar", "Enviar a Entrega", "Completar", "Enviar a Cobro")
    bloquea(lambda: apply_workflow(o, "Completar"), "saldo pendiente")
    o.reload()
    si = enviar("Sales Invoice", documentos.crear_facturas(o.name)[0])
    verifica(flt(si.grand_total) == esperado and si.update_stock, f"factura {si.grand_total} update_stock={si.update_stock}")
    asiento = gl(si.name)
    verifica(asiento.get("CUENTAS POR COBRAR CLIENTES") == esperado and asiento.get("COSTO DE VENTAS") == 200,
             f"asiento {asiento}")
    pagar(o)
    o.reload()
    o = avanza(o, "Completar", "Enviar a Facturación", "Completar")
    verifica(o.workflow_state == "Facturación - Completado" and o.docstatus == 1, f"final {o.workflow_state}")
    verifica(o.estatus == conf.ESTATUS_TERMINADO, f"estatus al terminar Mecánica: {o.estatus}")
    verifica(frappe.db.get_value("Project", o.proyecto, "status") == "Completed", "proyecto sin cerrar")
    verifica(flt(o.costo_mano_obra) >= 450 and flt(o.costo_materiales) == 200,
             f"costeo: mano de obra {o.costo_mano_obra}, materiales {o.costo_materiales}")
    verifica(flt(o.ingresos) == flt(esperado / 1.16, 2) and flt(o.margen) == flt(o.ingresos - o.costo_total, 2),
             f"margen {o.ingresos} - {o.costo_total} = {o.margen}")
    actividades = set(frappe.get_all("Timesheet Detail", filters={"project": o.proyecto}, pluck="activity_type"))
    verifica({"Taller - Diagnóstico", "Taller - Reparación"} <= actividades, f"timesheets {actividades}")


@caso
def mecanica_aseguradora_y_agencia():
    o = orden(tipo_orden=MECANICA, tipo_flujo="Aseguradora", aseguradora=cliente("Aseg Mec", "Aseguradora"),
              deducible=1160, conceptos=[{"item_code": "MO-HOJ", "qty": 4}])
    sos = documentos.crear_ordenes_venta(o.name)
    verifica(len(sos) == 2, f"Aseguradora de Mecánica debe generar 2 órdenes de venta ({sos})")
    for so in sos:
        enviar("Sales Order", so)
    total = sum(flt(enviar("Sales Invoice", si).grand_total) for si in documentos.crear_facturas(o.name))
    verifica(flt(total, 2) == flt(1800 * 1.16, 2), f"facturas {total}")
    agencia = cliente("Agencia Mec", "Agencia")
    a = orden(tipo_orden=MECANICA, tipo_flujo="Agencia", cliente=agencia, conceptos=[{"item_code": "SRV-LAV", "qty": 1}])
    verifica(frappe.get_doc("Sales Order", documentos.crear_ordenes_venta(a.name)[0]).customer == agencia,
             "la orden de venta de Agencia debe ir a la agencia")


@caso
def mecanica_cancelar_y_reactivar():
    o = avanza(orden(tipo_orden=MECANICA), "Enviar a Recepción", "Cancelar")
    verifica(o.workflow_state == conf.ESTADO_CANCELADA and estado_paso(o)["Recepción"] == "Anulado", "cancelar")
    o = avanza(o, "Reactivar")
    verifica(o.workflow_state == conf.ESTADO_INICIAL and len(o.pasos) == 12, "reactivar")


@caso
def cambio_de_tipo_de_orden():
    o = orden(placas="REG1")
    verifica(len(o.pasos) == 12, f"Hojalatería y Pintura con {len(o.pasos)} pasos")
    o.tipo_orden = MECANICA
    o.save()
    verifica([p.paso for p in o.pasos] == conf.SECUENCIA_MECANICA, "al pasar a Mecánica deben generarse sus pasos")
    o.tipo_orden = HYP
    o.save()
    verifica(len(o.pasos) == 12, "al volver a Hojalatería y Pintura deben regenerarse los pasos")
    o = avanza(o, "Enviar a Recepción")
    o.tipo_orden = MECANICA
    bloquea(lambda: o.save(), "solo se puede cambiar")


@caso
def recepcion_pide_vehiculo_y_valuacion():
    o = avanza(orden(), "Enviar a Recepción")
    bloquea(lambda: apply_workflow(o, "Completar"), "valuación")
    o.reload()
    o.placas = "REG2"
    o.save()
    valuacion_manual(o)
    o = avanza(o, "Completar")
    verifica(o.workflow_state == "Recepción - Completado", o.workflow_state)
    verifica([c.item_code for c in o.conceptos] == ["MO-HOJ", "VAL-OTRO"], f"conceptos {[c.item_code for c in o.conceptos]}")


@caso
def flujo_completo_particular_con_contabilidad():
    recibir_inventario("MAT-BASE", 5, 600)
    o = orden(placas="REG3", checklist_calidad_ok=1, recibido_por="Cliente", fecha_entrega=now_datetime())
    valuacion_manual(o)
    o.append("conceptos", {"item_code": "MAT-BASE", "qty": 1})
    o.save()
    q = documentos.crear_cotizacion(o.name)[0]
    enviar("Quotation", q)
    so = enviar("Sales Order", documentos.crear_ordenes_venta(o.name)[0])
    verifica(flt(so.grand_total) == flt((900 + 250 + 950) * 1.16, 2), f"orden de venta {so.grand_total}")
    pagar(o, 1000)
    o.reload()
    verifica(flt(o.saldo_pendiente) == flt(so.grand_total - 1000, 2), f"saldo tras anticipo {o.saldo_pendiente}")
    si = enviar("Sales Invoice", documentos.crear_facturas(o.name)[0])
    verifica(si.update_stock and si.advances and flt(si.advances[0].allocated_amount) == 1000, "anticipo o inventario no aplicados")
    asiento = gl(si.name)
    verifica(asiento.get("CUENTAS POR COBRAR CLIENTES") == flt(si.grand_total), f"CxC {asiento}")
    verifica(asiento.get("IVA") == -flt(si.total_taxes_and_charges), f"IVA {asiento}")
    verifica(asiento.get("COSTO DE VENTAS") == 600 and asiento.get("INVENTARIOS") == -600, f"costo {asiento}")
    pagar(o)
    o.reload()
    verifica(o.facturado and flt(o.saldo_pendiente) == 0, f"facturado={o.facturado} saldo={o.saldo_pendiente}")

    o = avanza(o, "Enviar a Recepción", "Completar", "Enviar a Carrocería")
    retrocede_inicio(o, "Carrocería", 3)
    o = avanza(o, "Completar", "Enviar a Preparación", "Anular", "Enviar a Pintura", "Completar",
               "Enviar a Armado", "Completar", "Enviar a Pulido", "Completar", "Enviar a Control de calidad",
               "Retrabajo a Pintura", "Completar", "Enviar a Armado", "Completar", "Enviar a Pulido", "Completar",
               "Enviar a Control de calidad", "Completar", "Enviar a Lavado", "Completar", "Enviar a Entrega",
               "Completar", "Enviar a Cobro", "Completar", "Enviar a Facturación", "Completar")
    verifica(o.workflow_state == "Facturación - Completado" and o.docstatus == 1, f"final {o.workflow_state} {o.docstatus}")
    verifica(o.estatus == conf.ESTATUS_TERMINADO, f"estatus al terminar: {o.estatus}")
    estados = {p.paso: p.estado for p in o.pasos}
    verifica(estados["Recolección"] == "Anulado" and estados["Preparación"] == "Anulado"
             and estados["Pintura"] == "Completado", f"pasos {estados}")
    verifica(frappe.db.get_value("Project", o.proyecto, "status") == "Completed", "el proyecto no quedó Completed")
    verifica(flt(o.costo_mano_obra) >= 450, f"mano de obra de Carrocería no registrada ({o.costo_mano_obra})")
    verifica(flt(o.costo_materiales) == 600, f"costo de materiales {o.costo_materiales}")


@caso
def cancelar_y_reactivar_hyp():
    o = orden(tipo_flujo="Agencia", requiere_recoleccion=1, cliente=cliente("Agencia", "Agencia"))
    o = avanza(o, "Programar Recolección")
    verifica(o.workflow_state == "Recolección - En Proceso", o.workflow_state)
    o = avanza(o, "Cancelar")
    verifica(o.pasos[0].estado == "Anulado", "Cancelar debe anular el paso en curso")
    verifica(o.estatus == conf.ESTATUS_CANCELADO, f"estatus al cancelar: {o.estatus}")
    o = avanza(o, "Reactivar")
    verifica(o.estatus == conf.ESTATUS_ACTIVO, f"estatus al reactivar: {o.estatus}")
    verifica(o.workflow_state == conf.ESTADO_INICIAL and not any(p.estado for p in o.pasos), "Reactivar no limpió los pasos")


@caso
def aseguradora_dos_facturas():
    o = orden(tipo_flujo="Aseguradora", aseguradora=cliente("Aseguradora", "Aseguradora"), deducible=2320,
              conceptos=[{"item_code": "MO-HOJ", "qty": 10}, {"item_code": "MO-PINT", "qty": 6}])
    verifica(flt(o.saldo_pendiente) == 2320, f"saldo esperado = deducible ({o.saldo_pendiente})")
    sos = documentos.crear_ordenes_venta(o.name)
    verifica(len(sos) == 2, f"se esperaban 2 órdenes de venta ({sos})")
    for so in sos:
        enviar("Sales Order", so)
    total = sum(flt(enviar("Sales Invoice", si).grand_total) for si in documentos.crear_facturas(o.name))
    verifica(flt(total, 2) == flt(7200 * 1.16, 2), f"suma de facturas {total}")
    pagar(o, deducible=1)
    o.reload()
    verifica(o.facturado and flt(o.saldo_pendiente) == 0, f"deducible pendiente {o.saldo_pendiente}")


@caso
def agencia_factura_al_cliente():
    agencia = cliente("Agencia Factura", "Agencia")
    o = orden(tipo_flujo="Agencia", cliente=agencia, conceptos=[{"item_code": "SRV-LAV", "qty": 1}])
    so = enviar("Sales Order", documentos.crear_ordenes_venta(o.name)[0])
    verifica(so.customer == agencia and so.project == o.proyecto, f"orden de venta a {so.customer}")


@caso
def costeo_y_reporte():
    recibir_inventario("CONS-LIJA", 20, 12)
    o = orden(placas="REG4")
    consumo = frappe.get_doc(costeo.crear_consumo(o.name))
    consumo.append("items", {"item_code": "CONS-LIJA", "qty": 10, "s_warehouse": ALMACEN})
    consumo.insert()
    consumo.submit()
    o.reload()
    verifica(flt(o.costo_materiales) == 120, f"consumo de lija {o.costo_materiales}")
    from taller.taller.report.rentabilidad_orden_taller.rentabilidad_orden_taller import execute
    columnas, filas, _, _ = execute({"tipo_orden": HYP})
    verifica(any(c["fieldname"] == "tipo_orden" for c in columnas), "el reporte no tiene la columna Tipo de orden")
    verifica(any(f.orden == o.name for f in filas), "la orden no aparece en el reporte")
    _, filas_mec, _, _ = execute({"tipo_orden": MECANICA})
    verifica(all(f.tipo_orden == MECANICA for f in filas_mec), "el filtro de tipo de orden no funciona")


@caso
def vin():
    from taller.vehiculo.vin import consultar_vin

    datos = consultar_vin("2t3j-1rfv6 sw586811")
    verifica(datos["valido"] and datos["datos"].get("marca") == "TOYOTA", f"consultar_vin {datos}")
    v = frappe.get_doc({"doctype": "Vehiculo Taller", "placas": "REG5", "vin": "2t3j1rfv6sw586811"}).insert()
    verifica((v.vin, v.marca, v.modelo, v.anio) == (VIN_TOYOTA, "TOYOTA", "RAV4", 2025), f"prellenado {v.vin} {v.marca} {v.modelo} {v.anio}")
    bloquea(lambda: frappe.get_doc({"doctype": "Vehiculo Taller", "vin": "2T3J1RFV7SW586811"}).insert(), "debería ser 6")
    bloquea(lambda: orden(vin="2T3J1RFV6SW58681"), "17 caracteres")
    frappe.get_doc({"doctype": "Vehiculo Taller", "vin": "WVWZZZ1KZAW000001"}).insert()
    verifica("no es de Norteamérica" in avisos(), "el VIN europeo debe avisar, no bloquear")
    frappe.get_doc({"doctype": "Vehiculo Taller", "marca": "NISSAN", "vin": "3VWFE21C04M000001"}).insert()
    verifica("VOLKSWAGEN" in avisos(), "falta el aviso de marca distinta al VIN")


@caso
def valuacion_manual_y_candados():
    o = orden(placas="REG6")
    v = valuacion_manual(o, [
        {"tipo": "Refacción", "descripcion": "Calavera", "numero_pieza": "81560", "cantidad": 1,
         "precio_unitario": 2500, "descuento": 5},
        {"tipo": "Mano de obra pintura", "descripcion": "Pintar", "cantidad": 1.5, "precio_unitario": 400}])
    verifica(flt(v.subtotal) == 2975 and flt(v.total_deducciones) == 125, f"totales {v.subtotal} {v.total_deducciones}")
    verifica(o.valuacion_aprobada and flt(o.subtotal) == 2975, f"orden: aprobada={o.valuacion_aprobada} subtotal={o.subtotal}")
    bloquea(lambda: frappe.get_doc({"doctype": "Valuacion Taller", "orden_taller": o.name, "origen": "Captura manual",
                                    "partidas": [{"tipo": "Otro", "descripcion": "x", "cantidad": 1,
                                                  "precio_unitario": 1}]}).insert(), "ya tiene la valuación")


@caso
def estatus_catalogo_y_valor_inicial():
    catalogo = {e.name: e for e in frappe.get_all(conf.DOCTYPE_ESTATUS, fields=["name", "color", "sistema"])}
    for nombre, _color, _descripcion in conf.CATALOGO_ESTATUS:
        verifica(nombre in catalogo and catalogo[nombre].sistema, f"falta el estatus de sistema {nombre}")
    bloquea(lambda: frappe.delete_doc(conf.DOCTYPE_ESTATUS, conf.ESTATUS_ACTIVO), "no se puede borrar")
    sin_estatus = frappe.get_all(conf.DOCTYPE, filters={conf.CAMPO_ESTATUS: ["in", ["", None]]}, pluck="name")
    verifica(not sin_estatus, f"órdenes sin estatus: {sin_estatus}")
    for tipo in conf.TIPOS_ORDEN:
        verifica(orden(tipo_orden=tipo, inventario=False).estatus == conf.ESTATUS_ACTIVO, f"una orden nueva de {tipo} debe nacer Activa")
    campo = frappe.get_meta(conf.DOCTYPE).get_field(conf.CAMPO_ESTATUS)
    verifica(campo.in_standard_filter and campo.in_list_view and campo.allow_on_submit,
             "el estatus debe estar en filtros y lista, y ser editable en órdenes terminadas")


@caso
def estatus_manual_y_filtro():
    o = orden(placas="REG20")
    o.estatus = conf.ESTATUS_INACTIVO
    o.save()
    o = avanza(o, "Enviar a Recepción")
    verifica(o.estatus == conf.ESTATUS_INACTIVO, "avanzar un paso no debe cambiar un estatus capturado a mano")
    visibles = frappe.get_list(conf.DOCTYPE, filters={conf.CAMPO_ESTATUS: conf.ESTATUS_INACTIVO}, pluck="name")
    verifica(o.name in visibles, "el filtro por estatus de la lista no encuentra la orden")
    from taller.taller.report.rentabilidad_orden_taller.rentabilidad_orden_taller import execute
    _, filas, _, _ = execute({"estatus": conf.ESTATUS_INACTIVO})
    verifica(filas and all(f.estatus == conf.ESTATUS_INACTIVO for f in filas), "el filtro de estatus del reporte no funciona")
    bloquea(lambda: frappe.get_doc(conf.DOCTYPE, o.name).update({"estatus": "No existe"}).save(), "No existe")


@caso
def estatus_en_orden_terminada():
    o = orden(tipo_orden=MECANICA, vin=VIN_TOYOTA, conceptos=[{"item_code": "SRV-LAV", "qty": 1}],
              diagnostico="Revisión", hallazgo_adicional="", checklist_calidad_ok=1, recibido_por="Cliente",
              fecha_entrega=now_datetime())
    enviar("Quotation", documentos.crear_cotizacion(o.name)[0])
    enviar("Sales Order", documentos.crear_ordenes_venta(o.name)[0])
    enviar("Sales Invoice", documentos.crear_facturas(o.name)[0])
    pagar(o)
    o.reload()
    o = avanza(o, "Enviar a Recepción", "Completar", "Enviar a Diagnóstico", "Completar", "Enviar a Cotización",
               "Completar", "Enviar a Autorización del cliente", "Completar", "Enviar a Refacciones", "Completar",
               "Enviar a Reparación", "Completar", "Enviar a Hallazgo adicional", "Anular",
               "Enviar a Control de calidad y ruta", "Completar", "Enviar a Lavado", "Completar", "Enviar a Entrega",
               "Completar", "Enviar a Cobro", "Completar", "Enviar a Facturación", "Completar")
    verifica(o.docstatus == 1 and o.estatus == conf.ESTATUS_TERMINADO, f"terminada: {o.docstatus} {o.estatus}")
    o.estatus = conf.ESTATUS_INACTIVO
    o.save()  # actualización después de enviar (allow_on_submit)
    verifica(frappe.db.get_value(conf.DOCTYPE, o.name, conf.CAMPO_ESTATUS) == conf.ESTATUS_INACTIVO,
             "no se pudo cambiar el estatus de una orden terminada")


@caso
def inventario_obligatorio_en_recepcion():
    o = orden(placas="REG30", inventario=False)
    inv = frappe.get_doc(conf.DOCTYPE_INVENTARIO, o.inventario)
    verifica(inv.orden_taller == o.name and inv.momento == conf.MOMENTO_RECEPCION and inv.docstatus == 0,
             f"inventario al crear la orden: {inv.orden_taller} {inv.momento} {inv.docstatus}")
    verifica(len(inv.accesorios) == len(conf.ACCESORIOS_INVENTARIO) == 28, f"accesorios precargados {len(inv.accesorios)}")
    verifica(inv.placas == "REG30" and inv.cliente == o.cliente, "el inventario no trajo los datos de la orden")
    bloquea(lambda: frappe.get_doc({"doctype": conf.DOCTYPE_INVENTARIO, "orden_taller": o.name}).insert(),
            "ya tiene el inventario")
    o = avanza(o, "Enviar a Recepción")
    valuacion_manual(o)
    bloquea(lambda: apply_workflow(o, "Completar"), "inventario")
    o.reload()
    bloquea(lambda: apply_workflow(o, "Anular"), "inventario")
    o.reload()

    sin_firmas = levantar_inventario(o, enviar=False, firma_entrega=None)
    bloquea(lambda: sin_firmas.submit(), "firma de quien entrega")
    sin_firmas.reload()
    sin_firmas.fotos = [f for f in sin_firmas.fotos if f.angulo != "Placas"]
    sin_firmas.firma_entrega = firma()
    sin_firmas.save()
    bloquea(lambda: sin_firmas.submit(), "Placas")
    sin_firmas.reload()
    sin_firmas.append("fotos", {"imagen": sin_firmas.fotos[0].imagen, "angulo": "Placas"})
    sin_firmas.append("danos", {"zona": "Cofre", "codigo": "G", "tamano_cm": 10})
    sin_firmas.save()
    bloquea(lambda: sin_firmas.submit(), "daños 1")
    sin_firmas.reload()
    sin_firmas.danos[0].foto = subir_foto(sin_firmas.doctype, sin_firmas.name)
    sin_firmas.update({"kilometraje": 45210, "numero_motor": "MOT123", "transmision": "Automática"})
    sin_firmas.save()
    sin_firmas.submit()

    foto = sin_firmas.fotos[0]
    verifica(foto.imagen.startswith("/private/") and foto.miniatura and foto.miniatura.startswith("/private/"),
             f"la foto debe quedar privada y con miniatura: {foto.imagen} {foto.miniatura}")
    verifica(foto.etapa == conf.MOMENTO_RECEPCION and foto.tomada_por and foto.fecha, "faltan etapa, autor o fecha de la foto")
    verifica(sin_firmas.danos[0].foto.startswith("/private/"), f"foto del daño pública: {sin_firmas.danos[0].foto}")
    o = avanza(frappe.get_doc(conf.DOCTYPE, o.name), "Completar")
    verifica(o.workflow_state == "Recepción - Completado", o.workflow_state)
    verifica(o.kilometraje == 45210, f"kilometraje en la orden {o.kilometraje}")
    if o.vehiculo:
        verifica(frappe.db.get_value(conf.DOCTYPE_VEHICULO, o.vehiculo, "numero_motor") == "MOT123",
                 "el número de motor no pasó al vehículo")


@caso
def inventario_en_recoleccion():
    o = orden(tipo_flujo="Agencia", requiere_recoleccion=1, cliente=cliente("Agencia Inv", "Agencia"),
              direccion_recoleccion="Av. Siempre Viva 742", inventario=False)
    inv = frappe.get_doc(conf.DOCTYPE_INVENTARIO, o.inventario)
    verifica(inv.momento == conf.MOMENTO_RECOLECCION and inv.direccion_recoleccion, f"momento {inv.momento}")
    o = avanza(o, "Programar Recolección")
    bloquea(lambda: apply_workflow(o, "Completar"), "inventario")
    inv = levantar_inventario(o, tipo_traslado="Grúa")
    o = avanza(frappe.get_doc(conf.DOCTYPE, o.name), "Completar", "Enviar a Recepción")
    verifica(o.workflow_state == "Recepción - En Proceso", o.workflow_state)
    llegada = add_to_date(now_datetime(), hours=-1)
    inv.reload()
    inv.update({"recibido_por": "Administrator", "fecha_recepcion": llegada, "firma_recepcion": firma()})
    inv.save()  # después de enviar (allow_on_submit)
    verifica(str(frappe.db.get_value(conf.DOCTYPE, o.name, "fecha_ingreso"))[:16] == str(llegada)[:16],
             "la llegada al taller no pasó a la fecha de ingreso de la orden")
    otra = orden(inventario=False)
    otra.requiere_recoleccion = 1
    otra.save()
    verifica(frappe.db.get_value(conf.DOCTYPE_INVENTARIO, otra.inventario, "momento") == conf.MOMENTO_RECOLECCION,
             "al pedir recolección, el inventario sin enviar debe pasar a Recolección")


@caso
def ambos_mecanica_y_carroceria():
    o = orden(tipo_orden=AMBOS, placas="REG31")
    verifica([p.paso for p in o.pasos] == conf.SECUENCIA_AMBOS, f"pasos de Ambos {[p.paso for p in o.pasos]}")
    o = avanza(o, "Enviar a Recepción")
    bloquea(lambda: apply_workflow(o, "Completar"), "valuación")  # regla de Hojalatería y Pintura
    o.reload()
    valuacion_manual(o)
    o = avanza(o, "Completar", "Enviar a Diagnóstico")
    bloquea(lambda: apply_workflow(o, "Completar"), "diagnóstico")  # regla de Mecánica
    o.reload()
    o.diagnostico = "Suspensión y golpe en cofre"
    o.save()
    o = avanza(o, "Completar", "Enviar a Cotización")
    enviar("Quotation", documentos.crear_cotizacion(o.name)[0])
    o.reload()
    o.presupuesto_aprobado = 1
    o.save()
    o = avanza(o, "Completar", "Enviar a Autorización del cliente", "Completar", "Enviar a Refacciones",
               "Completar", "Enviar a Reparación", "Completar", "Enviar a Hallazgo adicional", "Anular",
               "Enviar a Carrocería", "Completar", "Enviar a Preparación", "Completar", "Enviar a Pintura",
               "Completar", "Enviar a Armado", "Completar", "Enviar a Pulido", "Completar",
               "Enviar a Control de calidad y ruta")
    verifica({"Retrabajo a Reparación", "Retrabajo a Carrocería", "Retrabajo a Pintura"} <= acciones(o),
             f"retrabajo de Ambos: {acciones(o)}")
    o = avanza(o, "Retrabajo a Carrocería")
    verifica(estado_paso(o)["Carrocería"] == "En Proceso" and estado_paso(o)["Pulido"] is None,
             f"retrabajo a Carrocería: {estado_paso(o)}")
    from taller.flujo.reglas import obtener_reglas
    tipos = {r.name: frappe.db.get_value(conf.DOCTYPE_REGLAS, r.name, "tipo_orden") for r in obtener_reglas("Particular", AMBOS)}
    verifica({HYP, MECANICA, "Todos"} <= set(tipos.values()), f"reglas de Ambos {set(tipos.values())}")
    hyp = avanza(orden(placas="REG32"), "Enviar a Recepción")
    valuacion_manual(hyp)
    hyp = avanza(hyp, "Completar")
    verifica("Enviar a Diagnóstico" not in acciones(hyp), "Hojalatería y Pintura no debe pasar a Diagnóstico")


@caso
def costeo_solo_jefe_y_facturista():
    meta = frappe.get_meta(conf.DOCTYPE)
    for campo in costeo.CAMPOS_COSTEO + ["ingresos"]:
        verifica(meta.get_field(campo).permlevel == 1, f"{campo} debe tener nivel de permiso 1")
    con_nivel_1 = set(frappe.get_all("Custom DocPerm", filters={"parent": conf.DOCTYPE, "permlevel": 1, "read": 1},
                                     pluck="role"))
    verifica(set(conf.ROLES_COSTEO) <= con_nivel_1, f"roles con nivel 1: {con_nivel_1}")
    verifica("Hojalatero" not in con_nivel_1 and "Asesor de Servicio" not in con_nivel_1,
             f"técnicos y asesores no deben ver el costeo: {con_nivel_1}")


@caso
def zonas_y_fotos_de_la_orden():
    zonas = frappe.get_all(conf.DOCTYPE_ZONA, fields=["numero", "zona"], order_by="numero asc")
    verifica([z.numero for z in zonas] == list(range(1, 20)), f"zonas de carrocería {[z.numero for z in zonas]}")
    o = orden(placas="REG33")
    o = avanza(o, "Enviar a Recepción")
    original = foto_de_celular()
    o.append("fotos", {"imagen": subir_foto(o.doctype, o.name, original), "zona": "Cofre",
                       "comentario": "Golpe antes de reparar"})
    o.save()
    f = o.fotos[0]
    verifica(f.imagen.startswith("/private/") and f.miniatura and f.etapa == "Recepción" and f.paso == "Recepción",
             f"foto de la orden: {f.imagen} {f.miniatura} {f.etapa} {f.paso}")
    grande = frappe.get_doc("File", {"file_url": f.imagen})
    verifica(grande.is_private, "el File de la foto debe ser privado")
    verifica(len(original) > fotos_unidad.LIMITE_BYTES and grande.file_size < len(original) / 2,
             f"la foto grande no se optimizó: {len(original)} -> {grande.file_size} bytes")


def valuacion_audatex(pdf):
    from taller.taller.doctype.valuacion_taller.valuacion_taller import leer_pdf

    o = orden(tipo_flujo="Aseguradora", aseguradora=cliente("Aseguradora PDF", "Aseguradora"))
    v = frappe.get_doc({"doctype": "Valuacion Taller", "orden_taller": o.name, "origen": "Audatex"})
    v.flags.ignore_mandatory = True
    v.insert()
    archivo = frappe.get_doc({"doctype": "File", "file_name": "VALUACION.pdf", "is_private": 1,
                              "attached_to_doctype": "Valuacion Taller", "attached_to_name": v.name,
                              "content": open(pdf, "rb").read()}).insert()
    v.archivo_pdf = archivo.file_url
    v.save()
    leer_pdf(v.name)
    v.reload()
    verifica(len(v.partidas) > 0 and abs(flt(v.diferencia)) <= 1, f"partidas={len(v.partidas)} diferencia={v.diferencia}")
    original = v.partidas[0].precio_unitario
    v.partidas[0].precio_unitario = flt(original) + 100
    v.save()
    bloquea(lambda: v.submit(), "Corrige las partidas")
    v.reload()
    v.partidas[0].precio_unitario = original
    v.save()
    v.submit()
    o.reload()
    verifica(o.valuacion_aprobada and o.numero_siniestro and o.vehiculo, "la valuación no llenó la orden")
    so = enviar("Sales Order", documentos.crear_ordenes_venta(o.name)[0])
    verifica(abs(flt(so.grand_total) - flt(v.total_documento)) <= 1, f"orden de venta {so.grand_total} vs PDF {v.total_documento}")


# ==========================================================================
# Ejecución
# ==========================================================================
def correr(pdf=None):
    global ALMACEN
    frappe.set_user("Administrator")
    frappe.get_doc("User", "Administrator").add_roles(conf.ROL_SUPERVISOR)
    from taller.erp.configuracion_empresa import almacen_predeterminado
    ALMACEN = almacen_predeterminado()
    casos = list(CASOS) + ([lambda: valuacion_audatex(pdf)] if pdf else [])
    nombres = [c.__name__ for c in CASOS] + (["valuacion_audatex"] if pdf else [])

    resultados = []
    try:
        for nombre, funcion in zip(nombres, casos):
            frappe.db.savepoint("regresion")
            frappe.local.message_log = []
            try:
                funcion()
                resultados.append((nombre, "OK", ""))
            except Fallo as e:
                resultados.append((nombre, "FALLA", str(e)))
            except Exception:
                resultados.append((nombre, "ERROR", traceback.format_exc(limit=3).strip().splitlines()[-1]))
            finally:
                frappe.db.rollback(save_point="regresion")
                frappe.local.message_log = []
    finally:
        frappe.db.rollback()

    for nombre, estado, detalle in resultados:
        print(f"{estado:6} {nombre}" + (f"  ->  {detalle}" if detalle else ""))
    ok = sum(1 for _, estado, _ in resultados if estado == "OK")
    print(f"\n{ok}/{len(resultados)} casos correctos" + ("" if pdf else " (sin PDF: se omitió valuacion_audatex)"))
    return ok == len(resultados)
