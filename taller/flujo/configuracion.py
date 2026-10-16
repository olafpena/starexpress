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

El workflow cubre los tres tipos de orden (Hojalatería y Pintura, Mecánica y
Ambos): todas sus transiciones, salvo Cancelar y Reactivar, llevan la condición
`doc.tipo_orden == "..."` (o `in (...)` si el paso se comparte), así que un tipo de
orden sin secuencia no hereda pasos.

Frappe solo permite UN workflow activo por DocType, así que los tres tipos
(Agencia, Particular, Aseguradora) viven en el mismo workflow y se distinguen
con el campo `tipo_flujo`: cada tipo tiene su propia secuencia en FLUJOS y las
transiciones que no son comunes a todos llevan la condición
`doc.tipo_flujo == "..."`.

Uso:
    bench --site <sitio> execute taller.flujo.configuracion.instalar
    bench --site <sitio> execute taller.flujo.configuracion.instalar --kwargs "{'reconstruir': True}"

Con reconstruir=True se regeneran estados y transiciones, pero se CONSERVAN las
condiciones que hayas escrito a mano en las transiciones desde el Desk (se
agregan con "and" a la condición generada).
"""

import re
from collections import OrderedDict

SEPARADOR = " - "

NOMBRE_WORKFLOW = "Flujo Hojalatería y Pintura"
DOCTYPE = "Orden Taller"
DOCTYPE_REGLAS = "Regla Transicion Taller"
# La orden y el asesor de la agencia se capturan en el inventario (Firmas y conformidad)
CONDICION_ORDEN_AGENCIA = "inventario and inventario.orden_agencia"
DOCTYPE_VEHICULO = "Vehiculo Taller"
DOCTYPE_VALUACION = "Valuacion Taller"
DOCTYPE_ESTATUS = "Estatus Orden Taller"
DOCTYPE_INVENTARIO = "Inventario"
DOCTYPE_ZONA = "Zona de Carroceria"
DOCTYPE_DANO = "Danio de Carroceria"
CAMPO_ESTADO = "workflow_state"
CAMPO_PASO = "paso_actual"
CAMPO_PASOS = "pasos"
CAMPO_TIPO_ORDEN = "tipo_orden"

# Tipos de orden. El workflow y la tabla de pasos son de TIPO_ORDEN_FLUJO.
TIPO_ORDEN_FLUJO = "Hojalatería y Pintura"
TIPO_ORDEN_MECANICA = "Mecánica"
# Mecánica y luego hojalatería y pintura en una sola orden
TIPO_ORDEN_AMBOS = "Ambos"
TIPOS_ORDEN = [TIPO_ORDEN_FLUJO, TIPO_ORDEN_MECANICA, TIPO_ORDEN_AMBOS]
# Tipos de orden que llevan valuación (Valuacion Taller) y sección de mecánica
TIPOS_CON_VALUACION = (TIPO_ORDEN_FLUJO, TIPO_ORDEN_AMBOS)
TIPOS_CON_MECANICA = (TIPO_ORDEN_MECANICA, TIPO_ORDEN_AMBOS)
# Reglas de transición que toma cada tipo de orden, además de las de "Todos"
TIPOS_DE_REGLAS = {
    TIPO_ORDEN_FLUJO: [TIPO_ORDEN_FLUJO],
    TIPO_ORDEN_MECANICA: [TIPO_ORDEN_MECANICA],
    TIPO_ORDEN_AMBOS: [TIPO_ORDEN_AMBOS, TIPO_ORDEN_FLUJO, TIPO_ORDEN_MECANICA],
}
CONDICION_TIPO_ORDEN = f'doc.{CAMPO_TIPO_ORDEN} == "{TIPO_ORDEN_FLUJO}"'
# Acciones de la orden completa, disponibles para cualquier tipo de orden
ACCIONES_GENERALES = ("Cancelar", "Reactivar")

# Estatus de la orden (catálogo Estatus Orden Taller). Los de sistema los usa la
# app: alta de órdenes (Activo) y sincronización con el workflow (taller/flujo/estatus.py).
CAMPO_ESTATUS = "estatus"
ESTATUS_ACTIVO = "Activo"
ESTATUS_INACTIVO = "Inactivo"
ESTATUS_CANCELADO = "Cancelado"
ESTATUS_TERMINADO = "Terminado"
CATALOGO_ESTATUS = [
    (ESTATUS_ACTIVO, "Green", "Orden en trabajo. Estatus inicial de toda orden."),
    (ESTATUS_INACTIVO, "Gray", "Orden detenida temporalmente (p. ej. en espera del cliente)."),
    (ESTATUS_CANCELADO, "Red", "Orden cancelada. Se asigna al cancelar la orden en el workflow."),
    (ESTATUS_TERMINADO, "Blue", "Orden cerrada. Se asigna al completar el último paso del flujo."),
]

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
    # Mecánica (Recepción, Lavado, Entrega, Cobro y Facturación se comparten)
    ("Diagnóstico", "Mecánico"),
    ("Cotización", "Asesor de Servicio"),
    ("Autorización del cliente", "Asesor de Servicio"),
    ("Refacciones", "Almacenista"),
    ("Reparación", "Mecánico"),
    ("Hallazgo adicional", "Mecánico"),
    ("Control de calidad y ruta", "Inspector de Calidad"),
    ("Lavado", "Lavador"),
    ("Entrega", "Asesor de Servicio"),
    ("Cobro", "Cajero"),
    ("Facturación", "Facturista"),
])

SECUENCIA_HYP = ["Recolección", "Recepción", "Carrocería", "Preparación", "Pintura", "Armado",
                 "Pulido", "Control de calidad", "Lavado", "Entrega", "Cobro", "Facturación"]
SECUENCIA_MECANICA = ["Recepción", "Diagnóstico", "Cotización", "Autorización del cliente",
                      "Refacciones", "Reparación", "Hallazgo adicional", "Control de calidad y ruta",
                      "Lavado", "Entrega", "Cobro", "Facturación"]
# Ambos: primero la mecánica y después la carrocería; un solo control de calidad y ruta
SECUENCIA_AMBOS = ["Recolección", "Recepción", "Diagnóstico", "Cotización", "Autorización del cliente",
                   "Refacciones", "Reparación", "Hallazgo adicional", "Carrocería", "Preparación",
                   "Pintura", "Armado", "Pulido", "Control de calidad y ruta", "Lavado", "Entrega",
                   "Cobro", "Facturación"]

# --------------------------------------------------------------------------
# Secuencia de pasos por tipo de flujo.
# Para que un tipo se salte un paso, quítalo de su lista; para cambiar el
# orden (p. ej. Agencias que facturan antes de cobrar), reordénala.
# Recolección es opcional en tiempo de ejecución: depende del campo
# `requiere_recoleccion` de la orden.
# --------------------------------------------------------------------------
FLUJOS = OrderedDict([
    ("Agencia", list(SECUENCIA_HYP)),
    ("Particular", list(SECUENCIA_HYP)),
    ("Aseguradora", list(SECUENCIA_HYP)),
])

# Secuencias por tipo de orden y tipo de flujo. FLUJOS es la de Hojalatería y
# Pintura. Un paso con el mismo nombre en dos tipos de orden es el mismo paso:
# comparte sus estados del workflow (y las reglas que los usan).
FLUJOS_POR_ORDEN = OrderedDict([
    (TIPO_ORDEN_FLUJO, FLUJOS),
    (TIPO_ORDEN_MECANICA, OrderedDict((t, list(SECUENCIA_MECANICA)) for t in FLUJOS)),
    (TIPO_ORDEN_AMBOS, OrderedDict((t, list(SECUENCIA_AMBOS)) for t in FLUJOS)),
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
    "Diagnóstico": 1,
    "Cotización": 0.5,
    "Autorización del cliente": 0,
    "Refacciones": 0.5,
    "Reparación": 3,
    "Hallazgo adicional": 0.5,
    "Control de calidad y ruta": 0.5,
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
# Por tipo de orden: (paso de calidad, pasos a los que puede regresar la unidad)
RETRABAJO = {
    TIPO_ORDEN_FLUJO: (PASO_CALIDAD, PASOS_RETRABAJO),
    TIPO_ORDEN_MECANICA: ("Control de calidad y ruta", ["Reparación"]),
    TIPO_ORDEN_AMBOS: ("Control de calidad y ruta", ["Reparación"] + PASOS_RETRABAJO),
}

# --------------------------------------------------------------------------
# Inventario de la unidad (DocType Inventario): toda orden tiene uno. Se levanta
# en Recolección si la orden la requiere y si no en Recepción; la orden no puede
# completar ni anular esos pasos sin el inventario enviado.
# --------------------------------------------------------------------------
PASOS_INVENTARIO = ("Recolección", "Recepción")
MOMENTO_RECOLECCION = "Recolección"
MOMENTO_RECEPCION = "Recepción"

# Zonas de carrocería de la hoja de inventario: (número, zona, lado)
ZONAS_CARROCERIA = [
    (1, "Defensa delantera", "Frente"),
    (2, "Cofre", "Frente"),
    (3, "Parrilla / faros", "Frente"),
    (4, "Salpicadera delantera izquierda", "Izquierdo"),
    (5, "Puerta delantera izquierda", "Izquierdo"),
    (6, "Puerta trasera izquierda", "Izquierdo"),
    (7, "Costado / salpicadera trasera izquierda", "Izquierdo"),
    (8, "Salpicadera delantera derecha", "Derecho"),
    (9, "Puerta delantera derecha", "Derecho"),
    (10, "Puerta trasera derecha", "Derecho"),
    (11, "Costado / salpicadera trasera derecha", "Derecho"),
    (12, "Toldo", "Techo"),
    (13, "Cajuela / puerta trasera", "Trasera"),
    (14, "Defensa trasera / calaveras", "Trasera"),
    (15, "Parabrisas", "Cristales"),
    (16, "Medallón", "Cristales"),
    (17, "Cristales laterales", "Cristales"),
    (18, "Rines y llantas (4)", "Llantas"),
    (19, "Interiores (asientos, tablero, vestiduras)", "Interior"),
]

# Renglones que se precargan en el inventario: (grupo, concepto)
GRUPO_ACCESORIO = "Accesorio"
GRUPO_DOCUMENTO = "Documento y llave"
ACCESORIOS_INVENTARIO = [(GRUPO_ACCESORIO, c) for c in (
    "Llanta de refacción", "Gato", "Llave de cruz / birlos", "Birlo de seguridad (llave)",
    "Triángulos / señalamientos", "Extintor", "Cables pasacorriente", "Tapetes", "Radio / pantalla",
    "Antena", "Encendedor / toma 12 V", "Espejos laterales (2)", "Espejo interior", "Tapones de rines",
    "Tapón de gasolina", "Limpiaparabrisas", "Emblemas", "Cubrecarga / cortina de cajuela",
    "Portaplacas / placas (2)", "Objetos personales (describir)")] + [(GRUPO_DOCUMENTO, c) for c in (
    "Tarjeta de circulación", "Póliza de seguro", "Orden de admisión / valuación de la aseguradora",
    "Manual del propietario", "Llave principal", "Llave de repuesto", "Control de alarma",
    "Tarjeta o tag de peaje")]

# Ángulos de la evidencia fotográfica; al enviar el inventario se exige una foto
# de cada ángulo obligatorio (las fotos de cada daño van en su renglón de daños)
ANGULO_DANO = "Daño de cerca"
ANGULOS_OBLIGATORIOS = [
    "Frente completo", "Trasera completa", "Costado izquierdo", "Costado derecho",
    "Esquinas en diagonal", "Tablero encendido", "VIN", "Placas", "Interior",
    "Cajuela con refacción y herramienta"]
ANGULOS_FOTO = ANGULOS_OBLIGATORIOS + [ANGULO_DANO]

# Permisos sobre Orden Taller; los roles no listados reciben PERMISOS_BASE
PERMISOS_BASE = ["read", "write", "print", "report"]
PERMISOS = {
    ROL_SUPERVISOR: ["read", "write", "create", "submit", "cancel", "amend",
                     "delete", "print", "report", "export", "share"],
    ROL_RECEPCION: ["read", "write", "create", "print", "report"],
    "Facturista": ["read", "write", "submit", "print", "report", "export"],
}
# Roles que ven la sección Costeo (campos con permlevel 1)
ROLES_COSTEO = [ROL_SUPERVISOR, "Facturista", "System Manager"]


# ==========================================================================
# Construcción pura (sin tocar la base de datos)
# ==========================================================================
def estado(paso, sufijo):
    return f"{paso}{SEPARADOR}{sufijo}"


def tipo_orden_de(doc):
    return doc.get(CAMPO_TIPO_ORDEN) or TIPO_ORDEN_FLUJO


def secuencia(tipo_orden, tipo_flujo):
    """Pasos de la orden según su tipo de orden y tipo de flujo ([] si no hay)."""
    return list(FLUJOS_POR_ORDEN.get(tipo_orden or TIPO_ORDEN_FLUJO, {}).get(tipo_flujo) or [])


def recolecta(doc):
    """True si la orden pide recolección y su secuencia tiene el paso Recolección (Mecánica no)."""
    return bool(doc.get("requiere_recoleccion")) and PASO_RECOLECCION in secuencia(
        tipo_orden_de(doc), doc.get("tipo_flujo"))


def usa_flujo(doc):
    """True si el tipo de orden tiene flujo de pasos (sin tipo = Hojalatería y Pintura)."""
    return tipo_orden_de(doc) in FLUJOS_POR_ORDEN


def combinaciones():
    """(tipo de orden, tipo de flujo, secuencia) de todos los flujos."""
    for orden, flujos in FLUJOS_POR_ORDEN.items():
        for flujo, seq in flujos.items():
            yield orden, flujo, seq


def paso_de_estado(nombre_estado):
    return (nombre_estado or "").split(SEPARADOR)[0]


def sufijo_de_estado(nombre_estado):
    partes = (nombre_estado or "").split(SEPARADOR, 1)
    return partes[1] if len(partes) > 1 else None


def pasos_usados():
    return [paso for paso in PASOS if any(paso in seq for _o, _f, seq in combinaciones())]


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


def condicion_orden(ordenes):
    """Expresión sobre tipo_orden; siempre presente para que un tipo sin flujo no herede pasos."""
    ordenes = [o for o in FLUJOS_POR_ORDEN if o in ordenes]
    if len(ordenes) == 1:
        return f'doc.{CAMPO_TIPO_ORDEN} == "{ordenes[0]}"'
    return f"doc.{CAMPO_TIPO_ORDEN} in (" + ", ".join(f'"{o}"' for o in ordenes) + ")"


def condicion_combos(combos):
    """Condición de una transición que aplica a varias (tipo de orden, tipo de flujo, extra)."""
    por_orden = OrderedDict()
    for orden, flujo, extra in combos:
        por_orden.setdefault((orden, extra), []).append(flujo)
    grupos = OrderedDict()
    for (orden, extra), flujos in por_orden.items():
        grupos.setdefault((extra, tuple(flujos)), []).append(orden)
    partes = [y(condicion_orden(ordenes), condicion_tipos(flujos), extra)
              for (extra, flujos), ordenes in grupos.items()]
    return partes[0] if len(partes) == 1 else " or ".join(f"({p})" for p in partes)


def y(*condiciones):
    condiciones = [c for c in condiciones if c]
    if not condiciones:
        return None
    if len(condiciones) == 1:
        return condiciones[0]
    return " and ".join(f"({c})" for c in condiciones)


# Lo que escribe el generador; una condición con algo más la escribió alguien en el Desk
_VOCABULARIO_GENERADO = re.compile(
    r'doc\.(?:tipo_orden|tipo_flujo|requiere_recoleccion)|"[^"]*"|\b(?:and|or|not|in)\b|==|[(),\s]')


def es_condicion_generada(condicion):
    return not _VOCABULARIO_GENERADO.sub("", condicion or "")


def tipos_que_anulan(paso):
    """(tipo de orden, tipo de flujo) en los que el paso se puede anular (nunca el último)."""
    return [(o, f) for o, f, seq in combinaciones() if paso in seq and seq[-1] != paso]


def sufijos_de_paso(paso):
    return [s for s in ESTADOS_PREDETERMINADOS if s != ANULADO or tipos_que_anulan(paso)]


def estados_finales():
    """Último paso de cada flujo en Completado => documento enviado (docstatus 1)."""
    return {estado(seq[-1], COMPLETADO) for _o, _f, seq in combinaciones()}


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
    """Transiciones de todos los flujos. Una misma transición (p. ej. en un paso
    compartido) se genera una sola vez con la condición de todos los flujos que la usan."""
    entradas = OrderedDict()

    def agregar(origen, accion, destino, roles_permitidos, orden, flujo, extra=None):
        clave = (origen, accion, destino, tuple(OrderedDict.fromkeys(roles_permitidos)))
        entradas.setdefault(clave, []).append((orden, flujo, extra))

    arranque = [ROL_RECEPCION, ROL_SUPERVISOR]
    for orden, flujo, seq in combinaciones():
        # 1) Arranque: Nueva -> Recolección (si requiere) o directo al primer paso
        if seq[0] == PASO_RECOLECCION and len(seq) > 1:
            agregar(ESTADO_INICIAL, "Programar Recolección", estado(seq[0], EN_PROCESO), arranque,
                    orden, flujo, "doc.requiere_recoleccion")
            agregar(ESTADO_INICIAL, f"Enviar a {seq[1]}", estado(seq[1], EN_PROCESO), arranque,
                    orden, flujo, "not doc.requiere_recoleccion")
        else:
            accion = "Programar Recolección" if seq[0] == PASO_RECOLECCION else f"Enviar a {seq[0]}"
            agregar(ESTADO_INICIAL, accion, estado(seq[0], EN_PROCESO), arranque, orden, flujo)

        # 2) Movimientos internos de cada paso (En Proceso -> Completado / Anulado)
        for paso in seq:
            for origen, accion, destino in TRANSICIONES_INTERNAS:
                if destino == ANULADO and paso == seq[-1]:
                    continue
                agregar(estado(paso, origen), accion, estado(paso, destino),
                        [PASOS[paso], ROL_SUPERVISOR], orden, flujo)

        # 3) Avance al siguiente paso (desde Completado o Anulado)
        for actual, siguiente in zip(seq, seq[1:]):
            for sufijo in (COMPLETADO, ANULADO):
                agregar(estado(actual, sufijo), f"Enviar a {siguiente}", estado(siguiente, EN_PROCESO),
                        [PASOS[actual], ROL_SUPERVISOR], orden, flujo)

        # 4) Retrabajo desde el paso de calidad del tipo de orden
        calidad, pasos_retrabajo = RETRABAJO.get(orden, (None, []))
        if calidad in seq:
            for paso in pasos_retrabajo:
                if paso in seq:
                    agregar(estado(calidad, EN_PROCESO), f"Retrabajo a {paso}", estado(paso, EN_PROCESO),
                            [PASOS[calidad], ROL_SUPERVISOR], orden, flujo)

    filas = []

    def fila(origen, accion, destino, rol, condicion):
        filas.append({"state": origen, "action": accion, "next_state": destino, "allowed": rol,
                      "allow_self_approval": 1, "condition": condicion})

    for (origen, accion, destino, roles_permitidos), combos in entradas.items():
        condicion = condicion_combos(combos)
        for rol in roles_permitidos:
            fila(origen, accion, destino, rol, condicion)

    # 5) Cancelación (desde cualquier estado no enviado) y reactivación: cualquier tipo de orden
    for e in construir_estados():
        if e["doc_status"] == "0" and e["state"] != ESTADO_CANCELADA:
            fila(e["state"], "Cancelar", ESTADO_CANCELADA, ROL_SUPERVISOR, None)
    fila(ESTADO_CANCELADA, "Reactivar", ESTADO_INICIAL, ROL_SUPERVISOR, None)
    return filas


def acciones():
    return list(OrderedDict.fromkeys(t["action"] for t in construir_transiciones()))


def validar_configuracion():
    errores = []
    for orden, tipo, seq in combinaciones():
        nombre = f"{orden} / {tipo}"
        if not seq:
            errores.append(f"El flujo '{nombre}' no tiene pasos.")
        for paso in seq:
            if paso not in PASOS:
                errores.append(f"El paso '{paso}' del flujo '{nombre}' no existe en PASOS.")
        if len(seq) != len(set(seq)):
            errores.append(f"El flujo '{nombre}' repite pasos.")
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
    # --- Mecánica ---
    {
        "descripcion": "Mecánica: diagnóstico registrado",
        "tipo_orden": TIPO_ORDEN_MECANICA, "tipo_flujo": "Todos",
        "estado_destino": estado("Diagnóstico", "Completado"),
        "condicion": "doc.diagnostico",
        "mensaje": "Registra el diagnóstico antes de completar el paso.",
    },
    {
        "descripcion": "Mecánica: cotización creada",
        "tipo_orden": TIPO_ORDEN_MECANICA, "tipo_flujo": "Todos",
        "estado_destino": estado("Cotización", "Completado"),
        "condicion": "doc.cotizacion",
        "mensaje": "Crea la cotización (Crear → Cotización) antes de completar el paso.",
    },
    {
        "descripcion": "Mecánica: autorización del cliente",
        "tipo_orden": TIPO_ORDEN_MECANICA, "tipo_flujo": "Todos",
        "estado_destino": estado("Autorización del cliente", "Completado"),
        "condicion": "doc.presupuesto_aprobado",
        "mensaje": "El cliente debe autorizar: envía la orden de venta (o marca Presupuesto aprobado).",
    },
    {
        "descripcion": "Mecánica: hallazgo documentado",
        "tipo_orden": TIPO_ORDEN_MECANICA, "tipo_flujo": "Todos",
        "estado_destino": estado("Hallazgo adicional", "Completado"),
        "condicion": "doc.hallazgo_adicional",
        "mensaje": "Describe el hallazgo adicional, o anula el paso si no hubo.",
    },
    {
        "descripcion": "Mecánica: control de calidad y prueba de ruta",
        "tipo_orden": TIPO_ORDEN_MECANICA, "tipo_flujo": "Todos",
        "estado_destino": estado("Control de calidad y ruta", "Completado"),
        "condicion": "doc.checklist_calidad_ok",
        "mensaje": "Marca el checklist de calidad y prueba de ruta como aprobado, o regresa la unidad a Reparación.",
    },
    {
        "descripcion": "Recepción: valuación aprobada",
        "tipo_orden": TIPO_ORDEN_FLUJO,
        "tipo_flujo": "Todos", "estado_destino": estado("Recepción", "Completado"),
        "condicion": "doc.valuacion_aprobada",
        "mensaje": "Carga y envía (aprueba) la valuación de la orden antes de completar la recepción. "
                   "En Agencia y Aseguradora, adjunta el PDF de Audatex; en Particular, captura las partidas.",
    },
    {
        "descripcion": "Recepción: identificar el vehículo",
        "tipo_flujo": "Todos", "estado_destino": estado("Recepción", "Completado"),
        "condicion": "doc.placas or doc.vin",
        "mensaje": "Registra las placas o el VIN antes de completar la recepción.",
    },
    {
        "descripcion": "Aseguradora: siniestro autorizado antes de Carrocería",
        "tipo_orden": TIPO_ORDEN_FLUJO,
        "tipo_flujo": "Aseguradora", "paso": "Carrocería",
        "condicion": "doc.numero_siniestro and doc.autorizacion_aseguradora",
        "mensaje": "No se puede pasar a Carrocería sin número de siniestro y autorización de la aseguradora.",
    },
    {
        "descripcion": "Agencia: orden de la agencia antes de Carrocería",
        "tipo_orden": TIPO_ORDEN_FLUJO,
        "tipo_flujo": "Agencia", "paso": "Carrocería",
        "condicion": CONDICION_ORDEN_AGENCIA,
        "mensaje": "Captura en el inventario el número de orden de la agencia antes de pasar a Carrocería.",
    },
    {
        "descripcion": "Particular: presupuesto aprobado antes de Carrocería",
        "tipo_orden": TIPO_ORDEN_FLUJO,
        "tipo_flujo": "Particular", "paso": "Carrocería",
        "condicion": "doc.presupuesto_aprobado",
        "mensaje": "El cliente debe aprobar el presupuesto antes de pasar a Carrocería.",
    },
    {
        "descripcion": "Calidad: checklist aprobado",
        "tipo_orden": TIPO_ORDEN_FLUJO,
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

    from taller.erp.documentos import crear_campos_personalizados, crear_propiedades

    validar_configuracion()
    crear_campos_personalizados()
    crear_propiedades()
    crear_estatus()
    crear_roles()
    crear_estados_workflow()
    crear_acciones()
    asignar_permisos()
    crear_workflow(reconstruir=reconstruir)
    crear_reglas_ejemplo()
    crear_zonas()
    frappe.db.commit()
    frappe.clear_cache(doctype=DOCTYPE)
    print(f"Workflow '{NOMBRE_WORKFLOW}' listo: "
          f"{len(construir_estados())} estados, {len(construir_transiciones())} transiciones.")


def crear_estatus():
    """Catálogo de estatus: crea los de sistema que falten (no cambia colores editados)."""
    import frappe

    for nombre, color, descripcion in CATALOGO_ESTATUS:
        if frappe.db.exists(DOCTYPE_ESTATUS, nombre):
            frappe.db.set_value(DOCTYPE_ESTATUS, nombre, "sistema", 1)
            continue
        frappe.get_doc({"doctype": DOCTYPE_ESTATUS, "estatus": nombre, "color": color,
                        "descripcion": descripcion, "sistema": 1}).insert(ignore_permissions=True)


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

    # Catálogo de estatus: todos lo consultan; el jefe lo administra
    for rol in roles():
        add_permission(DOCTYPE_ESTATUS, rol, 0)
        ptypes = ["read", "write", "create", "report"] if rol == ROL_SUPERVISOR else ["read"]
        for ptype in ptypes:
            update_permission_property(DOCTYPE_ESTATUS, rol, 0, ptype, 1)

    # Valuación: la carga y aprueba recepción; el jefe además cancela y modifica
    for rol in roles():
        add_permission(DOCTYPE_VALUACION, rol, 0)
        if rol == ROL_SUPERVISOR:
            ptypes = ["read", "write", "create", "submit", "cancel", "amend", "delete", "report", "print"]
        elif rol == ROL_RECEPCION:
            ptypes = ["read", "write", "create", "submit", "report", "print"]
        else:
            ptypes = ["read"]
        for ptype in ptypes:
            update_permission_property(DOCTYPE_VALUACION, rol, 0, ptype, 1)

    # Inventario: lo levanta el chofer (Recolección) o recepción; el jefe además cancela
    for rol in roles():
        add_permission(DOCTYPE_INVENTARIO, rol, 0)
        if rol == ROL_SUPERVISOR:
            ptypes = ["read", "write", "create", "submit", "cancel", "amend", "delete", "report", "print"]
        elif rol in (ROL_RECEPCION, PASOS[PASO_RECOLECCION]):
            ptypes = ["read", "write", "create", "submit", "report", "print"]
        else:
            ptypes = ["read", "print"]
        for ptype in ptypes:
            update_permission_property(DOCTYPE_INVENTARIO, rol, 0, ptype, 1)

    # Zonas de carrocería: todos las consultan; el jefe las administra
    for rol in roles():
        add_permission(DOCTYPE_ZONA, rol, 0)
        ptypes = ["read", "write", "create", "delete", "report"] if rol == ROL_SUPERVISOR else ["read"]
        for ptype in ptypes:
            update_permission_property(DOCTYPE_ZONA, rol, 0, ptype, 1)

    # Costeo (permlevel 1 en Orden Taller): solo el jefe y el facturista lo ven
    for rol in ROLES_COSTEO:
        add_permission(DOCTYPE, rol, 1)
        update_permission_property(DOCTYPE, rol, 1, "read", 1)

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
        previa = condiciones_previas.get(clave)
        # Las condiciones generadas se reemplazan; una escrita en el Desk se conserva
        if previa and not es_condicion_generada(previa) and previa not in (fila["condition"] or ""):
            fila["condition"] = y(fila["condition"], previa)
        wf.append("transitions", fila)

    wf.save(ignore_permissions=True)


def crear_zonas():
    """Catálogo Zona de Carrocería: crea las zonas que falten (no cambia las editadas)."""
    import frappe

    for numero, zona, lado in ZONAS_CARROCERIA:
        if not frappe.db.exists(DOCTYPE_ZONA, zona):
            frappe.get_doc({"doctype": DOCTYPE_ZONA, "numero": numero, "zona": zona,
                            "lado": lado}).insert(ignore_permissions=True)


def crear_reglas_ejemplo():
    import frappe

    for regla in REGLAS_EJEMPLO:
        if frappe.db.exists(DOCTYPE_REGLAS, {"descripcion": regla["descripcion"]}):
            continue
        datos = {"doctype": DOCTYPE_REGLAS, "activo": 1, "tipo_regla": "Bloquear",
                 "paso": "Todos", "tipo_orden": "Todos", "prioridad": 10}
        datos.update(regla)
        frappe.get_doc(datos).insert(ignore_permissions=True)
