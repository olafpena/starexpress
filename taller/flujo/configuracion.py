"""
Flujo Hojalatería y Pintura
===========================

Este módulo es la ÚNICA fuente de verdad del workflow. Desde aquí se generan:

  * Roles del taller
  * Workflow State (En Proceso / Completado / Anulado por paso + Nueva + Cancelada)
  * Workflow Action Master
  * El Workflow "Flujo Hojalatería y Pintura" sobre el DocType "Orden Taller"
  * Permisos por rol
  * Reglas de transición de ejemplo (DocType "Regla Transicion Taller")

Frappe solo permite UN workflow activo por DocType, así que los tres tipos
(Agencia, Particular, Aseguradora) viven en el mismo workflow y se distinguen
con el campo `tipo_flujo`: cada tipo tiene su propia secuencia en FLUJOS y las
transiciones que no son comunes a todos llevan la condición
`doc.tipo_flujo == "..."`.

Uso:
    bench --site <sitio> execute taller.flujo.configuracion.instalar
    bench --site <sitio> execute taller.flujo.configuracion.instalar --kwargs "{'reconstruir': True}"

Con reconstruir=True se regeneran estados y transiciones, pero se CONSERVAN las
condiciones que hayas escrito a mano en las transiciones desde el Desk.
"""

from collections import OrderedDict

SEPARADOR = " - "

NOMBRE_WORKFLOW = "Flujo Hojalatería y Pintura"
DOCTYPE = "Orden Taller"
DOCTYPE_REGLAS = "Regla Transicion Taller"
DOCTYPE_VEHICULO = "Vehiculo Taller"
CAMPO_ESTADO = "workflow_state"
CAMPO_PASO = "paso_actual"
CAMPO_PASOS = "pasos"

ROL_SUPERVISOR = "Jefe de Taller"
ROL_RECEPCION = "Asesor de Servicio"

# --------------------------------------------------------------------------
# Pasos del proceso y rol responsable de cada uno
# --------------------------------------------------------------------------
PASOS = OrderedDict([
    ("Recolección", "Chofer"),
    ("Recepción", "Asesor de Servicio"),
    ("Carrocería", "Hojalatero"),
    ("Preparación", "Preparador"),
    ("Pintura", "Pintor"),
    ("Armado", "Armador"),
    ("Pulido", "Pulidor"),
    ("Control de calidad", "Inspector de Calidad"),
    ("Lavado", "Lavador"),
    ("Entrega", "Asesor de Servicio"),
    ("Cobro", "Cajero"),
    ("Facturación", "Facturista"),
])

TODOS_LOS_PASOS = list(PASOS)

# --------------------------------------------------------------------------
# Secuencia de pasos por tipo de flujo.
# Para que un tipo se salte un paso, quítalo de su lista; para cambiar el
# orden (p. ej. Agencias que facturan antes de cobrar), reordénala.
# Recolección es opcional en tiempo de ejecución: depende del campo
# `requiere_recoleccion` de la orden.
# --------------------------------------------------------------------------
FLUJOS = OrderedDict([
    ("Agencia", list(TODOS_LOS_PASOS)),
    ("Particular", list(TODOS_LOS_PASOS)),
    ("Aseguradora", list(TODOS_LOS_PASOS)),
])

# Horas estimadas por paso; llenan la columna "Hrs est." de la tabla de pasos
HORAS_ESTIMADAS = {
    "Recolección": 0.5,
    "Recepción": 0.5,
    "Carrocería": 8,
    "Preparación": 4,
    "Pintura": 4,
    "Armado": 3,
    "Pulido": 2,
    "Control de calidad": 1,
    "Lavado": 1,
    "Entrega": 0.5,
    "Cobro": 0.5,
    "Facturación": 0.5,
}

# --------------------------------------------------------------------------
# Estados que tiene CADA paso (sufijo -> estilo de color).
# Un paso entra En Proceso y sale Completado o Anulado (paso omitido); desde
# cualquiera de los dos la orden avanza al siguiente paso.
# --------------------------------------------------------------------------
EN_PROCESO = "En Proceso"
COMPLETADO = "Completado"
ANULADO = "Anulado"

ESTADOS_PREDETERMINADOS = OrderedDict([
    (EN_PROCESO, "Primary"),
    (COMPLETADO, "Success"),
    (ANULADO, "Inverse"),
])

# Movimientos dentro de un mismo paso: (estado origen, acción, estado destino)
TRANSICIONES_INTERNAS = [
    (EN_PROCESO, "Completar", COMPLETADO),
    (EN_PROCESO, "Anular", ANULADO),
]

ESTADO_INICIAL = "Nueva"
ESTADO_CANCELADA = "Cancelada"
PASO_RECOLECCION = "Recolección"
PASO_CALIDAD = "Control de calidad"
# Pasos a los que Control de calidad puede regresar la unidad (retrabajo)
PASOS_RETRABAJO = ["Carrocería", "Preparación", "Pintura", "Armado", "Pulido"]

# Permisos sobre Orden Taller; los roles no listados reciben PERMISOS_BASE
PERMISOS_BASE = ["read", "write", "print", "report"]
PERMISOS = {
    ROL_SUPERVISOR: ["read", "write", "create", "submit", "cancel", "amend",
                     "delete", "print", "report", "export", "share"],
    ROL_RECEPCION: ["read", "write", "create", "print", "report"],
    "Facturista": ["read", "write", "submit", "print", "report", "export"],
}


# ==========================================================================
# Construcción pura (sin tocar la base de datos)
# ==========================================================================
def estado(paso, sufijo):
    return f"{paso}{SEPARADOR}{sufijo}"


def paso_de_estado(nombre_estado):
    return (nombre_estado or "").split(SEPARADOR)[0]


def sufijo_de_estado(nombre_estado):
    partes = (nombre_estado or "").split(SEPARADOR, 1)
    return partes[1] if len(partes) > 1 else None


def pasos_usados():
    usados = OrderedDict()
    for paso in PASOS:
        if any(paso in seq for seq in FLUJOS.values()):
            usados[paso] = True
    return list(usados)


def roles():
    return list(OrderedDict.fromkeys(list(PASOS.values()) + [ROL_SUPERVISOR]))


def condicion_tipos(tipos):
    """None si aplica a todos los tipos; si no, una expresión sobre tipo_flujo."""
    tipos = [t for t in FLUJOS if t in tipos]
    if len(tipos) == len(FLUJOS):
        return None
    if len(tipos) == 1:
        return f'doc.tipo_flujo == "{tipos[0]}"'
    return "doc.tipo_flujo in (" + ", ".join(f'"{t}"' for t in tipos) + ")"


def y(*condiciones):
    condiciones = [c for c in condiciones if c]
    if not condiciones:
        return None
    if len(condiciones) == 1:
        return condiciones[0]
    return " and ".join(f"({c})" for c in condiciones)


def tipos_que_anulan(paso):
    """Tipos de flujo en los que el paso se puede anular (nunca el último paso)."""
    return [t for t, seq in FLUJOS.items() if paso in seq and seq[-1] != paso]


def sufijos_de_paso(paso):
    return [s for s in ESTADOS_PREDETERMINADOS if s != ANULADO or tipos_que_anulan(paso)]


def estados_finales():
    """Último paso de cada flujo en Completado => documento enviado (docstatus 1)."""
    return {estado(seq[-1], COMPLETADO) for seq in FLUJOS.values()}


def construir_estados():
    finales = estados_finales()

    def fila(nombre, doc_status, rol, paso):
        return {
            "state": nombre,
            "doc_status": doc_status,
            "allow_edit": rol,
            "update_field": CAMPO_PASO,
            "update_value": paso,
        }

    filas = [fila(ESTADO_INICIAL, "0", ROL_RECEPCION, ESTADO_INICIAL)]
    for paso in pasos_usados():
        for sufijo in sufijos_de_paso(paso):
            nombre = estado(paso, sufijo)
            if nombre in finales:
                filas.append(fila(nombre, "1", ROL_SUPERVISOR, paso))
            else:
                filas.append(fila(nombre, "0", PASOS[paso], paso))
    filas.append(fila(ESTADO_CANCELADA, "0", ROL_SUPERVISOR, ESTADO_CANCELADA))
    return filas


def estilos_estados():
    estilos = OrderedDict([(ESTADO_INICIAL, ""), (ESTADO_CANCELADA, "Danger")])
    for paso in pasos_usados():
        for sufijo in sufijos_de_paso(paso):
            estilos[estado(paso, sufijo)] = ESTADOS_PREDETERMINADOS[sufijo]
    return estilos


def construir_transiciones():
    filas = []

    def agregar(origen, accion, destino, roles_permitidos, condicion=None):
        for rol in OrderedDict.fromkeys(roles_permitidos):
            filas.append({
                "state": origen,
                "action": accion,
                "next_state": destino,
                "allowed": rol,
                "allow_self_approval": 1,
                "condition": condicion,
            })

    # 1) Arranque: Nueva -> Recolección (si requiere) o directo al siguiente paso
    arranques = OrderedDict()
    for tipo, seq in FLUJOS.items():
        if seq[0] == PASO_RECOLECCION and len(seq) > 1:
            arranques.setdefault((seq[0], "doc.requiere_recoleccion"), []).append(tipo)
            arranques.setdefault((seq[1], "not doc.requiere_recoleccion"), []).append(tipo)
        else:
            arranques.setdefault((seq[0], None), []).append(tipo)
    for (paso, cond_recoleccion), tipos in arranques.items():
        accion = "Programar Recolección" if paso == PASO_RECOLECCION else f"Enviar a {paso}"
        agregar(ESTADO_INICIAL, accion, estado(paso, EN_PROCESO),
                [ROL_RECEPCION, ROL_SUPERVISOR],
                y(condicion_tipos(tipos), cond_recoleccion))

    # 2) Movimientos internos de cada paso (En Proceso -> Completado / Anulado)
    for paso in pasos_usados():
        for origen, accion, destino in TRANSICIONES_INTERNAS:
            condicion = None
            if destino == ANULADO:
                if not tipos_que_anulan(paso):
                    continue
                condicion = condicion_tipos(tipos_que_anulan(paso))
            agregar(estado(paso, origen), accion, estado(paso, destino),
                    [PASOS[paso], ROL_SUPERVISOR], condicion)

    # 3) Avance al siguiente paso (desde Completado o Anulado) según cada tipo
    avances = OrderedDict()
    for tipo, seq in FLUJOS.items():
        for actual, siguiente in zip(seq, seq[1:]):
            avances.setdefault((actual, siguiente), []).append(tipo)
    for (actual, siguiente), tipos in avances.items():
        for sufijo in (COMPLETADO, ANULADO):
            agregar(estado(actual, sufijo), f"Enviar a {siguiente}",
                    estado(siguiente, EN_PROCESO),
                    [PASOS[actual], ROL_SUPERVISOR], condicion_tipos(tipos))

    # 4) Retrabajo desde Control de calidad
    for paso in PASOS_RETRABAJO:
        tipos = [t for t, seq in FLUJOS.items() if paso in seq and PASO_CALIDAD in seq]
        if tipos:
            agregar(estado(PASO_CALIDAD, EN_PROCESO), f"Retrabajo a {paso}",
                    estado(paso, EN_PROCESO),
                    [PASOS[PASO_CALIDAD], ROL_SUPERVISOR], condicion_tipos(tipos))

    # 5) Cancelación (desde cualquier estado no enviado) y reactivación
    for fila in construir_estados():
        if fila["doc_status"] == "0" and fila["state"] != ESTADO_CANCELADA:
            agregar(fila["state"], "Cancelar", ESTADO_CANCELADA, [ROL_SUPERVISOR])
    agregar(ESTADO_CANCELADA, "Reactivar", ESTADO_INICIAL, [ROL_SUPERVISOR])

    return filas


def acciones():
    return list(OrderedDict.fromkeys(t["action"] for t in construir_transiciones()))


def validar_configuracion():
    errores = []
    for tipo, seq in FLUJOS.items():
        if not seq:
            errores.append(f"El flujo '{tipo}' no tiene pasos.")
        for paso in seq:
            if paso not in PASOS:
                errores.append(f"El paso '{paso}' del flujo '{tipo}' no existe en PASOS.")
        if len(seq) != len(set(seq)):
            errores.append(f"El flujo '{tipo}' repite pasos.")
    # Un estado final (docstatus 1) no puede tener avances posteriores
    finales = estados_finales()
    for t in construir_transiciones():
        if t["state"] in finales:
            errores.append(f"'{t['state']}' es final en un flujo pero tiene salida '{t['action']}'.")
    if errores:
        raise ValueError("\n".join(OrderedDict.fromkeys(errores)))


# ==========================================================================
# Reglas de transición de ejemplo (editables / desactivables desde el Desk)
# ==========================================================================
REGLAS_EJEMPLO = [
    {
        "descripcion": "Recepción: identificar el vehículo",
        "tipo_flujo": "Todos", "estado_destino": estado("Recepción", "Completado"),
        "condicion": "doc.placas or doc.vin",
        "mensaje": "Registra las placas o el VIN antes de completar la recepción.",
    },
    {
        "descripcion": "Aseguradora: siniestro autorizado antes de Carrocería",
        "tipo_flujo": "Aseguradora", "paso": "Carrocería",
        "condicion": "doc.numero_siniestro and doc.autorizacion_aseguradora",
        "mensaje": "No se puede pasar a Carrocería sin número de siniestro y autorización de la aseguradora.",
    },
    {
        "descripcion": "Agencia: orden de la agencia antes de Carrocería",
        "tipo_flujo": "Agencia", "paso": "Carrocería",
        "condicion": "doc.orden_agencia",
        "mensaje": "Captura el número de orden de la agencia antes de pasar a Carrocería.",
    },
    {
        "descripcion": "Particular: presupuesto aprobado antes de Carrocería",
        "tipo_flujo": "Particular", "paso": "Carrocería",
        "condicion": "doc.presupuesto_aprobado",
        "mensaje": "El cliente debe aprobar el presupuesto antes de pasar a Carrocería.",
    },
    {
        "descripcion": "Calidad: checklist aprobado",
        "tipo_flujo": "Todos", "estado_destino": estado("Control de calidad", "Completado"),
        "condicion": "doc.checklist_calidad_ok",
        "mensaje": "Marca el checklist de calidad como aprobado, o envía la unidad a retrabajo.",
    },
    {
        "descripcion": "Entrega: quién recibe y cuándo",
        "tipo_flujo": "Todos", "estado_destino": estado("Entrega", "Completado"),
        "condicion": "doc.recibido_por and doc.fecha_entrega",
        "mensaje": "Indica quién recibió la unidad y la fecha de entrega.",
    },
    {
        "descripcion": "Particular: cobro liquidado",
        "tipo_flujo": "Particular", "estado_destino": estado("Cobro", "Completado"),
        "condicion": "doc.saldo_pendiente <= 0",
        "mensaje": "El cliente aún tiene saldo pendiente.",
    },
    {
        "descripcion": "Aseguradora: deducible cobrado",
        "tipo_flujo": "Aseguradora", "estado_destino": estado("Cobro", "Completado"),
        "condicion": "doc.saldo_pendiente <= 0",
        "mensaje": "El deducible no se ha cobrado por completo.",
    },
    {
        "descripcion": "Agencia: aviso de saldo a crédito",
        "tipo_flujo": "Agencia", "estado_destino": estado("Cobro", "Completado"),
        "tipo_regla": "Advertir",
        "condicion": "doc.saldo_pendiente <= 0 or doc.forma_pago == 'Crédito'",
        "mensaje": "La agencia tiene saldo pendiente y la forma de pago no es Crédito.",
    },
    {
        "descripcion": "Facturación: facturas enviadas",
        "tipo_flujo": "Todos", "estado_destino": estado("Facturación", "Completado"),
        "condicion": "doc.facturado",
        "mensaje": "Envía la(s) factura(s) de venta de la orden antes de cerrarla.",
    },
]


# ==========================================================================
# Instalación en Frappe
# ==========================================================================
def instalar(reconstruir=False):
    import frappe

    from taller.erp.documentos import crear_campos_personalizados

    validar_configuracion()
    crear_campos_personalizados()
    crear_roles()
    crear_estados_workflow()
    crear_acciones()
    asignar_permisos()
    crear_workflow(reconstruir=reconstruir)
    crear_reglas_ejemplo()
    frappe.db.commit()
    frappe.clear_cache(doctype=DOCTYPE)
    print(f"Workflow '{NOMBRE_WORKFLOW}' listo: "
          f"{len(construir_estados())} estados, {len(construir_transiciones())} transiciones.")


def crear_roles():
    import frappe

    for rol in roles():
        if not frappe.db.exists("Role", rol):
            frappe.get_doc({"doctype": "Role", "role_name": rol, "desk_access": 1}).insert(
                ignore_permissions=True)


def crear_estados_workflow():
    import frappe

    for nombre, estilo in estilos_estados().items():
        if frappe.db.exists("Workflow State", nombre):
            frappe.db.set_value("Workflow State", nombre, "style", estilo)
        else:
            frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": nombre,
                            "style": estilo}).insert(ignore_permissions=True)


def crear_acciones():
    import frappe

    for accion in acciones():
        if not frappe.db.exists("Workflow Action Master", accion):
            frappe.get_doc({"doctype": "Workflow Action Master",
                            "workflow_action_name": accion}).insert(ignore_permissions=True)


def asignar_permisos():
    from frappe.permissions import add_permission, update_permission_property

    for rol in roles():
        add_permission(DOCTYPE, rol, 0)
        for ptype in PERMISOS.get(rol, PERMISOS_BASE):
            update_permission_property(DOCTYPE, rol, 0, ptype, 1)

    add_permission(DOCTYPE_REGLAS, ROL_SUPERVISOR, 0)
    for ptype in ["read", "write", "create", "delete", "report"]:
        update_permission_property(DOCTYPE_REGLAS, ROL_SUPERVISOR, 0, ptype, 1)

    for rol in roles():
        add_permission(DOCTYPE_VEHICULO, rol, 0)
        ptypes = ["read", "write", "create", "report", "print"] if rol in (ROL_SUPERVISOR, ROL_RECEPCION) else ["read"]
        for ptype in ptypes:
            update_permission_property(DOCTYPE_VEHICULO, rol, 0, ptype, 1)


def crear_workflow(reconstruir=False):
    import frappe

    condiciones_previas = {}
    if frappe.db.exists("Workflow", NOMBRE_WORKFLOW):
        if not reconstruir:
            return
        wf = frappe.get_doc("Workflow", NOMBRE_WORKFLOW)
        for t in wf.transitions:
            if t.condition:
                condiciones_previas[(t.state, t.action, t.next_state, t.allowed)] = t.condition
        wf.set("states", [])
        wf.set("transitions", [])
    else:
        wf = frappe.new_doc("Workflow")
        wf.workflow_name = NOMBRE_WORKFLOW

    wf.document_type = DOCTYPE
    wf.workflow_state_field = CAMPO_ESTADO
    wf.is_active = 1
    wf.send_email_alert = 0

    for fila in construir_estados():
        wf.append("states", fila)
    for fila in construir_transiciones():
        clave = (fila["state"], fila["action"], fila["next_state"], fila["allowed"])
        if clave in condiciones_previas:
            fila["condition"] = condiciones_previas[clave]
        wf.append("transitions", fila)

    wf.save(ignore_permissions=True)


def crear_reglas_ejemplo():
    import frappe

    for regla in REGLAS_EJEMPLO:
        if frappe.db.exists(DOCTYPE_REGLAS, {"descripcion": regla["descripcion"]}):
            continue
        datos = {"doctype": DOCTYPE_REGLAS, "activo": 1, "tipo_regla": "Bloquear",
                 "paso": "Todos", "prioridad": 10}
        datos.update(regla)
        frappe.get_doc(datos).insert(ignore_permissions=True)
