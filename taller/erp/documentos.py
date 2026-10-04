"""
Fase 1: la Orden Taller usa los documentos estándar de ERPNext.

    Cotización (Quotation) -> Orden de venta (Sales Order) -> Factura (Sales Invoice)
    Anticipos y cobros: Payment Entry contra la orden de venta o la factura.

Quién paga según el tipo de flujo:

    Particular  -> cliente
    Agencia     -> agencia
    Aseguradora -> aseguradora (conceptos menos el deducible) y cliente (deducible)

Todos los documentos llevan el campo `orden_taller`. Al enviarlos, cancelarlos o
borrarlos (y al enviar o cancelar un pago) se recalculan los montos de la orden.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from taller.erp.configuracion_empresa import ARTICULO_DEDUCIBLE

DOCTYPE = "Orden Taller"
CAMPO_ORDEN = "orden_taller"
ASEGURADORA = "Aseguradora"

# (orden de venta, factura) de cada pagador de la orden
PAGADORES = [("orden_venta", "factura_venta"), ("orden_venta_deducible", "factura_deducible")]

CAMPOS_PERSONALIZADOS = {
    "Quotation": [{"fieldname": CAMPO_ORDEN, "label": "Orden Taller", "fieldtype": "Link",
                   "options": DOCTYPE, "insert_after": "party_name", "read_only": 1,
                   "in_standard_filter": 1}],
    "Sales Order": [{"fieldname": CAMPO_ORDEN, "label": "Orden Taller", "fieldtype": "Link",
                     "options": DOCTYPE, "insert_after": "customer", "read_only": 1,
                     "in_standard_filter": 1}],
    "Sales Invoice": [{"fieldname": CAMPO_ORDEN, "label": "Orden Taller", "fieldtype": "Link",
                       "options": DOCTYPE, "insert_after": "customer", "read_only": 1,
                       "in_standard_filter": 1}],
}


def crear_campos_personalizados():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(CAMPOS_PERSONALIZADOS, update=True)


# ==========================================================================
# Datos de la orden
# ==========================================================================
def pagador(doc):
    return {"Agencia": doc.agencia, ASEGURADORA: doc.aseguradora}.get(doc.tipo_flujo, doc.cliente)


def plantilla_impuestos(company):
    return frappe.db.get_value("Sales Taxes and Charges Template",
                               {"company": company, "is_default": 1, "disabled": 0})


def tasa_impuestos(company):
    plantilla = plantilla_impuestos(company)
    if not plantilla:
        return 0
    tasas = frappe.get_all("Sales Taxes and Charges", pluck="rate", filters={
        "parent": plantilla, "parenttype": "Sales Taxes and Charges Template",
        "charge_type": "On Net Total"})
    return sum(flt(t) for t in tasas) / 100


def deducible_neto(doc):
    """El deducible se captura con IVA; las órdenes de venta lo usan sin IVA."""
    return flt(flt(doc.deducible) / (1 + tasa_impuestos(doc.company)), 2)


def calcular_conceptos(doc):
    for c in doc.conceptos:
        if not flt(c.rate) and c.item_code:
            c.rate = precio_articulo(c.item_code)
        c.amount = flt(c.qty) * flt(c.rate)
    doc.subtotal = sum(flt(c.amount) for c in doc.conceptos)


@frappe.whitelist()
def precio_articulo(item_code):
    lista = frappe.db.get_single_value("Selling Settings", "selling_price_list")
    return flt(frappe.db.get_value("Item Price", {"item_code": item_code, "price_list": lista,
                                                  "selling": 1}, "price_list_rate"))


def _enviado(doctype, nombre, campos):
    if not nombre:
        return None
    datos = frappe.db.get_value(doctype, nombre, ["docstatus"] + campos, as_dict=True)
    return datos if datos and datos.docstatus == 1 else None


def _vigente(doctype, nombre):
    """Existe y no está cancelado (borrador o enviado)."""
    return bool(nombre) and frappe.db.get_value(doctype, nombre, "docstatus") in (0, 1)


def calcular_montos(doc):
    """Montos de la orden a partir de sus órdenes de venta, facturas y pagos enviados.

    saldo_pendiente es lo que debe quien paga en el paso Cobro: el cliente (o la
    agencia), o el deducible en Aseguradora. Mientras su orden de venta no esté
    enviada, el saldo es el importe esperado.
    """
    total = pagado = ingresos = 0
    saldos, facturas = {}, []
    for campo_so, campo_si in PAGADORES:
        so = _enviado("Sales Order", doc.get(campo_so), ["grand_total", "advance_paid"])
        si = _enviado("Sales Invoice", doc.get(campo_si),
                      ["grand_total", "outstanding_amount", "posting_date", "base_net_total"])
        if si:
            facturas.append((doc.get(campo_si), si.posting_date))
            ingresos += flt(si.base_net_total)
            total += flt(si.grand_total)
            pagado += flt(si.grand_total) - flt(si.outstanding_amount)
            saldos[campo_so] = flt(si.outstanding_amount)
        elif so:
            total += flt(so.grand_total)
            pagado += flt(so.advance_paid)
            saldos[campo_so] = flt(so.grand_total) - flt(so.advance_paid)

    if doc.tipo_flujo == ASEGURADORA:
        saldo = saldos.get("orden_venta_deducible", flt(doc.deducible))
    else:
        esperado = flt(doc.subtotal) * (1 + tasa_impuestos(doc.company))
        saldo = saldos.get("orden_venta", esperado)

    doc.monto_total = total
    doc.monto_pagado = pagado
    doc.ingresos = ingresos
    doc.saldo_pendiente = flt(saldo, 2)

    requeridas = [campo_si for campo_so, campo_si in PAGADORES if _vigente("Sales Order", doc.get(campo_so))]
    doc.facturado = int(bool(requeridas) and all(
        _enviado("Sales Invoice", doc.get(c), []) for c in requeridas))
    doc.folio_factura = ", ".join(nombre for nombre, _fecha in facturas) or None
    doc.fecha_factura = max(fecha for _nombre, fecha in facturas) if facturas else None
    if _enviado("Sales Order", doc.orden_venta, []):
        doc.presupuesto_aprobado = 1


CAMPOS_MONTOS = ["monto_total", "monto_pagado", "saldo_pendiente", "facturado",
                 "folio_factura", "fecha_factura", "presupuesto_aprobado", "ingresos"]


def actualizar_orden(nombre):
    from taller.erp.costeo import CAMPOS_COSTEO, calcular_costeo

    doc = frappe.get_doc(DOCTYPE, nombre)
    calcular_montos(doc)
    calcular_costeo(doc)
    cambios = {c: doc.get(c) for c in CAMPOS_MONTOS + CAMPOS_COSTEO}
    doc.db_set(cambios, update_modified=False)


# ==========================================================================
# Acciones desde el formulario de la orden
# ==========================================================================
def _orden(nombre):
    doc = frappe.get_doc(DOCTYPE, nombre)
    doc.check_permission("write")
    if not doc.company:
        frappe.throw(_("La orden no tiene compañía."))
    return doc


def _requerir(valor, campo):
    if not valor:
        frappe.throw(_("Captura {0} en la orden.").format(_(campo)))
    return valor


def _agregar_conceptos(destino, doc, entrega=None):
    if not doc.conceptos:
        frappe.throw(_("Agrega al menos un concepto a la orden."))
    almacen = frappe.db.get_single_value("Stock Settings", "default_warehouse")
    for c in doc.conceptos:
        fila = {"item_code": c.item_code, "qty": c.qty, "rate": c.rate}
        if entrega:
            fila["delivery_date"] = entrega
            if frappe.get_cached_value("Item", c.item_code, "is_stock_item"):
                fila["warehouse"] = almacen
        destino.append("items", fila)


def _agregar_impuestos(destino, company):
    plantilla = plantilla_impuestos(company)
    if plantilla:
        destino.taxes_and_charges = plantilla
        destino.set("taxes", [])
        destino.append_taxes_from_master()


def _fecha_entrega(doc):
    fecha = getdate(doc.fecha_entrega) if doc.fecha_entrega else None
    return max(fecha, getdate(nowdate())) if fecha else getdate(nowdate())


@frappe.whitelist()
def crear_cotizacion(orden):
    doc = _orden(orden)
    if _vigente("Quotation", doc.cotizacion):
        frappe.throw(_("La orden ya tiene la cotización {0}.").format(doc.cotizacion))
    cliente = _requerir(pagador(doc), {"Agencia": "Agencia", ASEGURADORA: "Aseguradora"}
                        .get(doc.tipo_flujo, "Cliente"))

    q = frappe.new_doc("Quotation")
    q.quotation_to = "Customer"
    q.party_name = cliente
    q.company = doc.company
    q.transaction_date = nowdate()
    q.set(CAMPO_ORDEN, doc.name)
    q.project = doc.proyecto
    _agregar_conceptos(q, doc)
    _agregar_impuestos(q, doc.company)
    q.insert()
    doc.db_set("cotizacion", q.name)
    return [q.name]


@frappe.whitelist()
def crear_ordenes_venta(orden):
    from erpnext.selling.doctype.quotation.quotation import make_sales_order

    doc = _orden(orden)
    entrega = _fecha_entrega(doc)
    creadas = []

    if not _vigente("Sales Order", doc.orden_venta):
        cliente = _requerir(pagador(doc), {"Agencia": "Agencia", ASEGURADORA: "Aseguradora"}
                            .get(doc.tipo_flujo, "Cliente"))
        if _enviado("Quotation", doc.cotizacion, []):
            so = make_sales_order(doc.cotizacion)
            for item in so.items:
                item.delivery_date = entrega
                if frappe.get_cached_value("Item", item.item_code, "is_stock_item"):
                    item.warehouse = frappe.db.get_single_value("Stock Settings", "default_warehouse")
        else:
            so = frappe.new_doc("Sales Order")
            so.customer = cliente
            _agregar_conceptos(so, doc, entrega)
            _agregar_impuestos(so, doc.company)
        so.company = doc.company
        so.transaction_date = nowdate()
        so.delivery_date = entrega
        so.set(CAMPO_ORDEN, doc.name)
        so.project = doc.proyecto
        if doc.tipo_flujo == ASEGURADORA and flt(doc.deducible):
            so.apply_discount_on = "Net Total"
            so.discount_amount = deducible_neto(doc)
        so.insert()
        doc.db_set("orden_venta", so.name)
        creadas.append(so.name)

    if (doc.tipo_flujo == ASEGURADORA and flt(doc.deducible)
            and not _vigente("Sales Order", doc.orden_venta_deducible)):
        so = frappe.new_doc("Sales Order")
        so.customer = _requerir(doc.cliente, "Cliente")
        so.company = doc.company
        so.transaction_date = nowdate()
        so.delivery_date = entrega
        so.set(CAMPO_ORDEN, doc.name)
        so.project = doc.proyecto
        so.append("items", {"item_code": ARTICULO_DEDUCIBLE, "qty": 1,
                            "rate": deducible_neto(doc), "delivery_date": entrega})
        _agregar_impuestos(so, doc.company)
        so.insert()
        doc.db_set("orden_venta_deducible", so.name)
        creadas.append(so.name)

    if not creadas:
        frappe.throw(_("La orden ya tiene sus órdenes de venta."))
    return creadas


@frappe.whitelist()
def crear_facturas(orden):
    from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

    doc = _orden(orden)
    creadas = []
    for campo_so, campo_si in PAGADORES:
        so = doc.get(campo_so)
        if not _vigente("Sales Order", so) or _vigente("Sales Invoice", doc.get(campo_si)):
            continue
        if not _enviado("Sales Order", so, []):
            frappe.throw(_("Envía la orden de venta {0} antes de facturar.").format(so))
        si = make_sales_invoice(so)
        si.set(CAMPO_ORDEN, doc.name)
        si.project = doc.proyecto
        si.allocate_advances_automatically = 1
        if any(frappe.get_cached_value("Item", i.item_code, "is_stock_item") for i in si.items):
            si.update_stock = 1
        si.insert()
        doc.db_set(campo_si, si.name)
        creadas.append(si.name)

    if not creadas:
        frappe.throw(_("No hay órdenes de venta pendientes de facturar."))
    return creadas


@frappe.whitelist()
def crear_pago(orden, deducible=0):
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    doc = _orden(orden)
    campo_so, campo_si = PAGADORES[1] if int(deducible) else PAGADORES[0]
    if _enviado("Sales Invoice", doc.get(campo_si), []):
        referencia = ("Sales Invoice", doc.get(campo_si))
    elif _enviado("Sales Order", doc.get(campo_so), []):
        referencia = ("Sales Order", doc.get(campo_so))
    else:
        frappe.throw(_("Envía primero la orden de venta para registrar el pago."))
    pe = get_payment_entry(*referencia)
    pe.project = doc.proyecto
    return pe


# ==========================================================================
# Eventos de documentos de ERPNext (hooks.py -> doc_events)
# ==========================================================================
def al_cambiar_documento(doc, method=None):
    nombre = doc.get(CAMPO_ORDEN)
    if not nombre or not frappe.db.exists(DOCTYPE, nombre):
        return
    campo = _campo_de_documento(doc, nombre)
    actual = frappe.db.get_value(DOCTYPE, nombre, campo) if campo else None
    if campo and method == "on_trash":
        if actual == doc.name:
            frappe.db.set_value(DOCTYPE, nombre, campo, None, update_modified=False)
    elif campo and actual != doc.name and not _vigente(doc.doctype, actual):
        # Documento hecho a mano desde ERPNext (p. ej. factura desde la orden de venta)
        frappe.db.set_value(DOCTYPE, nombre, campo, doc.name, update_modified=False)
    actualizar_orden(nombre)


def al_cambiar_pago(doc, method=None):
    ordenes = set()
    for ref in doc.references:
        if ref.reference_doctype in ("Sales Order", "Sales Invoice"):
            orden = frappe.db.get_value(ref.reference_doctype, ref.reference_name, CAMPO_ORDEN)
            if orden:
                ordenes.add(orden)
    for orden in ordenes:
        actualizar_orden(orden)


def _campo_de_documento(doc, orden):
    if doc.doctype == "Quotation":
        return "cotizacion"
    deducible = frappe.db.get_value(DOCTYPE, orden, "orden_venta_deducible")
    if doc.doctype == "Sales Order":
        cliente, tipo = frappe.db.get_value(DOCTYPE, orden, ["cliente", "tipo_flujo"])
        if doc.name == deducible or (tipo == ASEGURADORA and doc.customer == cliente
                                     and any(i.item_code == ARTICULO_DEDUCIBLE for i in doc.items)):
            return "orden_venta_deducible"
        return "orden_venta"
    if doc.doctype == "Sales Invoice":
        if deducible and any(i.sales_order == deducible for i in doc.items):
            return "factura_deducible"
        return "factura_venta"
    return None
