"""
Regresión de la app taller sobre un sitio real, sin dejar rastro.

Cada caso corre dentro de un savepoint y se revierte al terminar; al final se
hace rollback de todo, así que no queda ningún documento ni movimiento.

    bench --site <sitio> execute taller.tests.regresion.correr
    bench --site <sitio> execute taller.tests.regresion.correr --kwargs "{'pdf': '/ruta/VALUACION.pdf'}"

Requiere la compañía configurada (taller.erp.configuracion_empresa.configurar).
El caso de Audatex solo corre si se pasa la ruta de un PDF de valuación.
"""

import traceback

import frappe
from frappe.model.workflow import apply_workflow, get_transitions
from frappe.utils import add_to_date, flt, now_datetime, nowdate

from taller.erp import costeo, documentos
from taller.flujo import configuracion as conf

HYP, MECANICA = conf.TIPO_ORDEN_FLUJO, conf.TIPO_ORDEN_MECANICA
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


def orden(**campos):
    datos = {"doctype": "Orden Taller", "tipo_orden": HYP, "tipo_flujo": "Particular"}
    datos.update(campos)
    if "cliente" not in datos:
        datos["cliente"] = cliente("Cliente")
    return frappe.get_doc(datos).insert()


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
    for t in wf.transitions:
        if t.action in conf.ACCIONES_GENERALES:
            verifica(conf.CONDICION_TIPO_ORDEN not in (t.condition or ""), f"{t.action} no debe depender del tipo de orden")
        else:
            verifica(conf.CONDICION_TIPO_ORDEN in (t.condition or ""), f"falta la condición de tipo de orden en {t.state} → {t.action}")
    recoleccion = [t.condition for t in wf.transitions if t.state == conf.ESTADO_INICIAL and "recoleccion" in (t.condition or "")]
    verifica(len(recoleccion) == 4, f"se perdieron las condiciones de recolección ({len(recoleccion)} de 4)")
    sin_tipo = frappe.get_all("Orden Taller", filters={"tipo_orden": ["in", ["", None]]}, pluck="name")
    verifica(not sin_tipo, f"órdenes sin tipo de orden: {sin_tipo}")


@caso
def mecanica_no_usa_el_flujo():
    o = orden(tipo_orden=MECANICA, conceptos=[{"item_code": "MO-HOJ", "qty": 1}])
    verifica(o.workflow_state == conf.ESTADO_INICIAL, f"estado inicial {o.workflow_state}")
    verifica(not o.pasos, "una orden de Mecánica no debe tener tabla de pasos")
    acciones = {t.action for t in get_transitions(o)}
    verifica(acciones == {"Cancelar"}, f"acciones disponibles en Mecánica: {acciones}")
    bloquea(lambda: apply_workflow(o, "Enviar a Recepción"))
    bloquea(lambda: frappe.get_doc({"doctype": "Valuacion Taller", "orden_taller": o.name, "origen": "Captura manual",
                                    "partidas": [{"tipo": "Otro", "descripcion": "x", "cantidad": 1,
                                                  "precio_unitario": 1}]}).insert(),
            "flujo de Hojalatería y Pintura")
    so = documentos.crear_ordenes_venta(o.name)[0]
    enviar("Sales Order", so)
    si = documentos.crear_facturas(o.name)[0]
    enviar("Sales Invoice", si)
    o.reload()
    verifica(o.facturado and flt(o.ingresos) == 450, f"Mecánica facturada: facturado={o.facturado} ingresos={o.ingresos}")
    o = avanza(o, "Cancelar")
    verifica(o.workflow_state == conf.ESTADO_CANCELADA, "Mecánica no se pudo cancelar")
    o = avanza(o, "Reactivar")
    verifica(o.workflow_state == conf.ESTADO_INICIAL and not o.pasos, "Mecánica reactivada con pasos o en otro estado")


@caso
def cambio_de_tipo_de_orden():
    o = orden(placas="REG1")
    verifica(len(o.pasos) == 12, f"Hojalatería y Pintura con {len(o.pasos)} pasos")
    o.tipo_orden = MECANICA
    o.save()
    verifica(not o.pasos, "al pasar a Mecánica en Nueva deben quitarse los pasos")
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
    o = avanza(o, "Reactivar")
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
    ALMACEN = frappe.db.get_single_value("Stock Settings", "default_warehouse")
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
