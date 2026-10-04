"""
Fase 0: deja la compañía de ERPNext lista para facturar el taller.

Es idempotente; se puede correr las veces que haga falta:

    bench --site <sitio> execute taller.erp.configuracion_empresa.configurar --kwargs "{'company': 'StarExpress'}"

Las cuentas se indican sin el sufijo " - <abreviatura>" de la compañía; revísalas
con tu contador antes de usarlas en otra compañía o plan de cuentas.
"""

import frappe

# Cuentas de la compañía (sin sufijo de abreviatura)
CUENTAS = {
    "default_receivable_account": "CUENTAS POR COBRAR CLIENTES",
    "default_payable_account": "CUENTAS POR PAGAR PROVEEDORES",
    "default_income_account": "VENTAS NACIONALES",
    "round_off_account": "OTROS EGRESOS",
    "default_bank_account": "BANCO X MXN",
}
CUENTA_INGRESO_SERVICIOS = "INGRESOS POR SERVICIOS 1"
CUENTA_INGRESO_MATERIALES = "VENTAS NACIONALES"
CUENTA_COSTO = "COSTO DE VENTAS"  # costo de materiales vendidos y consumidos
CUENTA_CAJA = "CAJA PRINCIPAL"
CUENTA_BANCO = "BANCO X MXN"

# Formas de pago estándar de ERPNext -> cuenta
FORMAS_PAGO = {
    "Cash": CUENTA_CAJA,
    "Wire Transfer": CUENTA_BANCO,
    "Credit Card": CUENTA_BANCO,
    "Cheque": CUENTA_BANCO,
    "Bank Draft": CUENTA_BANCO,
}

CENTRO_COSTO_TALLER = "Taller"
ALMACEN_TALLER = "Almacén Taller"
LISTA_PRECIOS = "Standard Selling"
TERRITORIO = "Mexico"

GRUPOS_CLIENTE = ["Particular", "Agencia", "Aseguradora"]
GRUPO_CLIENTE_DEFAULT = "Particular"

GRUPO_SERVICIOS = "Servicios Taller"
GRUPO_MATERIALES = "Materiales Taller"

# Catálogo básico: (código, nombre, grupo, unidad, precio sin IVA, inventariable)
# Los precios son de referencia; ajústalos en la lista de precios.
ARTICULOS = [
    ("MO-HOJ", "Mano de obra hojalatería", GRUPO_SERVICIOS, "Hour", 450, 0),
    ("MO-PREP", "Mano de obra preparación", GRUPO_SERVICIOS, "Hour", 350, 0),
    ("MO-PINT", "Mano de obra pintura", GRUPO_SERVICIOS, "Hour", 450, 0),
    ("MO-ARM", "Mano de obra armado", GRUPO_SERVICIOS, "Hour", 350, 0),
    ("SRV-PUL", "Pulido y abrillantado", GRUPO_SERVICIOS, "Unit", 800, 0),
    ("SRV-LAV", "Lavado y detallado", GRUPO_SERVICIOS, "Unit", 250, 0),
    ("SRV-REC", "Recolección / grúa", GRUPO_SERVICIOS, "Unit", 600, 0),
    ("DEDUCIBLE", "Deducible de seguro", GRUPO_SERVICIOS, "Unit", 0, 0),
    ("MAT-PRIMER", "Primer", GRUPO_MATERIALES, "Litre", 380, 1),
    ("MAT-BASE", "Pintura base color", GRUPO_MATERIALES, "Litre", 950, 1),
    ("MAT-BARNIZ", "Barniz transparente", GRUPO_MATERIALES, "Litre", 720, 1),
    ("MAT-MASILLA", "Masilla automotriz", GRUPO_MATERIALES, "Nos", 180, 1),
]
ARTICULO_DEDUCIBLE = "DEDUCIBLE"

# Artículos que reciben las partidas de la valuación (taller/valuacion) al pasarlas a
# los conceptos de la orden. No son de inventario: la descripción y el precio vienen
# de la valuación, y el consumo real se registra aparte (Consumo de materiales).
# (código, nombre, grupo, cuenta de ingreso)
ARTICULOS_VALUACION = [
    ("VAL-REF", "Refacción (según valuación)", GRUPO_MATERIALES, CUENTA_INGRESO_MATERIALES),
    ("VAL-MATP", "Materiales de pintura (según valuación)", GRUPO_MATERIALES, CUENTA_INGRESO_MATERIALES),
    ("VAL-MATR", "Materiales de reparación (según valuación)", GRUPO_MATERIALES, CUENTA_INGRESO_MATERIALES),
    ("VAL-OTRO", "Otros cargos (según valuación)", GRUPO_SERVICIOS, CUENTA_INGRESO_SERVICIOS),
]
# Tipo de partida de la valuación -> artículo del concepto
ARTICULO_POR_TIPO = {
    "Refacción": "VAL-REF",
    "Mano de obra hojalatería": "MO-HOJ",
    "Mano de obra pintura": "MO-PINT",
    "Material de pintura": "VAL-MATP",
    "Material de reparación": "VAL-MATR",
    "Otro": "VAL-OTRO",
}

# Consumibles: se usan en la reparación pero no se facturan (salida de material
# contra el proyecto de la orden). (código, nombre, unidad)
GRUPO_CONSUMIBLES = "Consumibles Taller"
CONSUMIBLES = [
    ("CONS-LIJA", "Lija de agua", "Nos"),
    ("CONS-CINTA", "Cinta de enmascarar", "Nos"),
    ("CONS-THINNER", "Thinner", "Litre"),
]

# Costo por hora de la mano de obra de cada paso (Activity Type "Taller - <paso>").
# Son de referencia: ajústalos en Activity Type, o por empleado en Activity Cost.
COSTO_HORA = {
    "Recolección": 90,
    "Recepción": 0,
    "Carrocería": 150,
    "Preparación": 120,
    "Pintura": 150,
    "Armado": 120,
    "Pulido": 110,
    "Control de calidad": 120,
    "Lavado": 80,
    "Entrega": 0,
    "Cobro": 0,
    "Facturación": 0,
}


def actividad(paso):
    return f"Taller - {paso}"


def configurar(company="StarExpress"):
    abbr = frappe.db.get_value("Company", company, "abbr")
    if not abbr:
        frappe.throw(f"No existe la compañía {company}")

    def cuenta(nombre):
        nombre_completo = f"{nombre} - {abbr}"
        if not frappe.db.exists("Account", {"name": nombre_completo, "company": company}):
            frappe.throw(f"No existe la cuenta {nombre_completo}")
        return nombre_completo

    frappe.db.set_value("Account", cuenta(CUENTA_BANCO), "account_type", "Bank")

    centro_costo = crear_centro_costo(company, abbr)
    almacen = crear_almacen(company, abbr)

    empresa = frappe.get_doc("Company", company)
    for campo, nombre in CUENTAS.items():
        empresa.set(campo, cuenta(nombre))
    empresa.round_off_cost_center = empresa.round_off_cost_center or empresa.cost_center
    empresa.save(ignore_permissions=True)

    frappe.db.set_default("company", company)
    frappe.db.set_single_value("Global Defaults", "default_company", company)
    # CFDI usa totales con centavos: sin redondeo al peso
    frappe.db.set_single_value("Global Defaults", "disable_rounded_total", 1)
    frappe.db.set_single_value("Stock Settings", "default_warehouse", almacen)

    for forma, nombre in FORMAS_PAGO.items():
        asignar_cuenta_forma_pago(forma, company, cuenta(nombre))

    plantilla = frappe.db.get_value("Sales Taxes and Charges Template",
                                    {"company": company, "disabled": 0}, "name")
    if plantilla:
        frappe.db.set_value("Sales Taxes and Charges Template", plantilla, "is_default", 1)

    for grupo in GRUPOS_CLIENTE:
        if not frappe.db.exists("Customer Group", grupo):
            frappe.get_doc({"doctype": "Customer Group", "customer_group_name": grupo,
                            "parent_customer_group": "All Customer Groups"}).insert(ignore_permissions=True)
    frappe.db.set_single_value("Selling Settings", "customer_group", GRUPO_CLIENTE_DEFAULT)
    frappe.db.set_single_value("Selling Settings", "territory", TERRITORIO)
    frappe.db.set_single_value("Selling Settings", "selling_price_list", LISTA_PRECIOS)

    for grupo in (GRUPO_SERVICIOS, GRUPO_MATERIALES, GRUPO_CONSUMIBLES):
        if not frappe.db.exists("Item Group", grupo):
            frappe.get_doc({"doctype": "Item Group", "item_group_name": grupo,
                            "parent_item_group": "All Item Groups"}).insert(ignore_permissions=True)

    costo = cuenta(CUENTA_COSTO)
    for codigo, nombre, grupo, uom, precio, inventariable in ARTICULOS:
        ingreso = cuenta(CUENTA_INGRESO_MATERIALES if inventariable else CUENTA_INGRESO_SERVICIOS)
        crear_articulo(codigo, nombre, grupo, uom, precio, inventariable, company,
                       ingreso, centro_costo, almacen, costo)
    for codigo, nombre, grupo, cuenta_ingreso in ARTICULOS_VALUACION:
        crear_articulo(codigo, nombre, grupo, "Nos", 0, 0, company, cuenta(cuenta_ingreso),
                       centro_costo, almacen, costo)
    for codigo, nombre, uom in CONSUMIBLES:
        crear_articulo(codigo, nombre, GRUPO_CONSUMIBLES, uom, 0, 1, company,
                       cuenta(CUENTA_INGRESO_MATERIALES), centro_costo, almacen, costo, venta=0)

    for paso, costo_hora in COSTO_HORA.items():
        crear_actividad(paso, costo_hora)
    # Un trabajador puede llevar varias órdenes a la vez (p. ej. mientras seca la pintura)
    frappe.db.set_single_value("Projects Settings", "ignore_employee_time_overlap", 1)
    frappe.db.set_single_value("Projects Settings", "ignore_user_time_overlap", 1)

    frappe.db.commit()
    print(f"Compañía {company} configurada para el taller.")


def crear_centro_costo(company, abbr):
    nombre = f"{CENTRO_COSTO_TALLER} - {abbr}"
    if not frappe.db.exists("Cost Center", nombre):
        padre = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1,
                                                    "parent_cost_center": ["is", "not set"]})
        frappe.get_doc({"doctype": "Cost Center", "cost_center_name": CENTRO_COSTO_TALLER,
                        "company": company, "parent_cost_center": padre}).insert(ignore_permissions=True)
    return nombre


def crear_almacen(company, abbr):
    nombre = f"{ALMACEN_TALLER} - {abbr}"
    if not frappe.db.exists("Warehouse", nombre):
        padre = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1,
                                                  "parent_warehouse": ["is", "not set"]})
        frappe.get_doc({"doctype": "Warehouse", "warehouse_name": ALMACEN_TALLER,
                        "company": company, "parent_warehouse": padre}).insert(ignore_permissions=True)
    return nombre


def asignar_cuenta_forma_pago(forma, company, cuenta):
    if not frappe.db.exists("Mode of Payment", forma):
        return
    mp = frappe.get_doc("Mode of Payment", forma)
    fila = next((a for a in mp.accounts if a.company == company), None)
    if fila:
        fila.default_account = cuenta
    else:
        mp.append("accounts", {"company": company, "default_account": cuenta})
    mp.save(ignore_permissions=True)


def crear_actividad(paso, costo_hora):
    nombre = actividad(paso)
    if frappe.db.exists("Activity Type", nombre):
        return
    frappe.get_doc({"doctype": "Activity Type", "activity_type": nombre,
                    "costing_rate": costo_hora}).insert(ignore_permissions=True)


def crear_articulo(codigo, nombre, grupo, uom, precio, inventariable, company, ingreso,
                   centro_costo, almacen, costo, venta=1):
    if frappe.db.exists("Item", codigo):
        item = frappe.get_doc("Item", codigo)
    else:
        item = frappe.get_doc({"doctype": "Item", "item_code": codigo, "item_name": nombre,
                               "item_group": grupo, "stock_uom": uom,
                               "is_stock_item": inventariable, "is_sales_item": venta,
                               "include_item_in_manufacturing": 0})
    fila = next((d for d in item.item_defaults if d.company == company), None)
    if not fila:
        fila = item.append("item_defaults", {"company": company})
    fila.income_account = ingreso
    fila.selling_cost_center = centro_costo
    fila.buying_cost_center = centro_costo
    fila.expense_account = costo
    fila.default_warehouse = almacen if inventariable else None
    item.save(ignore_permissions=True)

    if precio and not frappe.db.exists("Item Price", {"item_code": codigo, "price_list": LISTA_PRECIOS}):
        frappe.get_doc({"doctype": "Item Price", "item_code": codigo, "price_list": LISTA_PRECIOS,
                        "price_list_rate": precio}).insert(ignore_permissions=True)
