"""
VIN: validación del dígito verificador y prellenado de marca, modelo y año.

Validación (offline, sin dependencias):
  * Formato: 17 caracteres, letras y números, sin I, O ni Q.
  * Dígito verificador (posición 9, ISO 3779 / 49 CFR 565). Es obligatorio en
    VINs de Norteamérica (primer carácter 1-5; 3 = México), así que ahí un dígito
    que no cuadra es un error de captura y se bloquea. En otros orígenes (Europa,
    Asia, Sudamérica) muchos fabricantes no lo usan: solo se advierte.

Decodificación: ultravin (base vPIC de la NHTSA embebida, funciona sin red). Solo
llena los campos que están vacíos. La marca se guarda en mayúsculas, igual que
en Audatex, para que sirva como llave estable.

`revisar_vin(doc)` se llama desde validate() de Vehiculo Taller, Orden Taller y
Valuacion Taller; `consultar_vin` lo usa el formulario mientras se captura.
"""

import re

import frappe
from frappe import _

VALORES = {**{str(i): i for i in range(10)}, **dict(zip("ABCDEFGH", range(1, 9))),
           **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
PESOS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
REGIONES_CON_DV = "12345"  # Norteamérica: EE. UU. (1, 4, 5), Canadá (2), México (3)
PATRON = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normalizar(vin):
    return re.sub(r"[\s\-]", "", vin or "").upper()


def digito_verificador(vin):
    residuo = sum(VALORES[c] * p for c, p in zip(vin, PESOS)) % 11
    return "X" if residuo == 10 else str(residuo)


def validar(vin):
    """{"valido": bool, "bloquea": bool, "mensaje": str | None, "dv_esperado": str | None}"""
    vin = normalizar(vin)
    if not vin:
        return {"valido": True, "bloquea": False, "mensaje": None, "dv_esperado": None}
    if len(vin) != 17:
        return {"valido": False, "bloquea": True, "dv_esperado": None,
                "mensaje": _("El VIN debe tener 17 caracteres (tiene {0}).").format(len(vin))}
    if not PATRON.match(vin):
        return {"valido": False, "bloquea": True, "dv_esperado": None,
                "mensaje": _("El VIN solo admite letras y números, sin I, O ni Q.")}
    esperado = digito_verificador(vin)
    if vin[8] == esperado:
        return {"valido": True, "bloquea": False, "mensaje": None, "dv_esperado": esperado}
    norteamerica = vin[0] in REGIONES_CON_DV
    mensaje = _("El dígito verificador del VIN (posición 9) es {0} y debería ser {1}; revisa la captura.").format(
        vin[8], esperado)
    if not norteamerica:
        mensaje += " " + _("Este VIN no es de Norteamérica y su fabricante podría no usar dígito verificador.")
    return {"valido": False, "bloquea": norteamerica, "mensaje": mensaje, "dv_esperado": esperado}


def decodificar(vin):
    """{"marca", "modelo", "anio", "version", "carroceria", "pais_fabricacion"} o {} si no se puede."""
    vin = normalizar(vin)
    if len(vin) != 17:
        return {}
    try:
        import ultravin
    except ImportError:
        return {}
    try:
        r = ultravin.decode(vin)
    except Exception:
        frappe.log_error(f"ultravin no pudo decodificar {vin}")
        return {}
    a = r.get("attributes") or {}
    datos = {
        "marca": (a.get("Make") or "").strip().upper() or None,
        "modelo": (a.get("Model") or "").strip() or None,
        "anio": r.get("model_year") or None,
        "version": (a.get("Trim") or a.get("Series") or "").strip() or None,
        "carroceria": (a.get("Body Class") or "").strip() or None,
        "pais_fabricacion": (a.get("Plant Country") or "").strip().title() or None,
    }
    return {k: v for k, v in datos.items() if v}


def revisar_vin(doc, campo="vin", estricto=True):
    """Normaliza y valida el VIN del documento y llena lo que falte del vehículo.

    Valida y prellena solo si el VIN es nuevo o cambió. Con estricto=False (VIN que
    viene de un documento externo, p. ej. Audatex) nunca bloquea: solo advierte.
    Si la marca capturada no coincide con la del VIN, advierte (no bloquea).
    """
    vin = normalizar(doc.get(campo))
    doc.set(campo, vin or None)
    if not vin:
        return
    vin_cambio = doc.is_new() or doc.has_value_changed(campo)
    marca_cambio = doc.meta.has_field("marca") and (doc.is_new() or doc.has_value_changed("marca"))
    if not (vin_cambio or marca_cambio):
        return

    resultado = validar(vin)
    if vin_cambio and resultado["mensaje"]:
        if resultado["bloquea"] and estricto and not doc.flags.get("vin_externo"):
            frappe.throw(resultado["mensaje"], title=_("VIN inválido"))
        frappe.msgprint(resultado["mensaje"], title=_("Revisa el VIN"), indicator="orange")
    if resultado["bloquea"]:
        return

    datos = decodificar(vin)
    if doc.meta.has_field("marca") and doc.get("marca") and not misma_marca(doc.marca, datos.get("marca")):
        frappe.msgprint(_("La marca capturada es {0}, pero el VIN corresponde a {1}. Revisa cuál es la correcta.")
                        .format(doc.marca, datos["marca"]), title=_("Marca distinta al VIN"), indicator="orange")
    if vin_cambio:
        for campo_destino, valor in datos.items():
            if doc.meta.has_field(campo_destino) and not doc.get(campo_destino):
                doc.set(campo_destino, valor)


# Nombres comunes de una marca -> nombre de vPIC
ALIAS_MARCA = {"VW": "VOLKSWAGEN", "CHEVY": "CHEVROLET", "MERCEDES": "MERCEDESBENZ", "MB": "MERCEDESBENZ",
               "MINI COOPER": "MINI", "LAND ROVER": "LANDROVER"}


def _clave_marca(marca):
    clave = re.sub(r"[^A-Z0-9 ]", "", (marca or "").upper()).strip()
    clave = ALIAS_MARCA.get(clave, clave)
    return clave.replace(" ", "")


def misma_marca(capturada, del_vin):
    """True si coinciden o si el VIN no trae marca (no hay con qué comparar)."""
    if not del_vin:
        return True
    a, b = _clave_marca(capturada), _clave_marca(del_vin)
    return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))


@frappe.whitelist()
def consultar_vin(vin):
    vin = normalizar(vin)
    return {"vin": vin, **validar(vin), "datos": decodificar(vin) if len(vin) == 17 else {}}


@frappe.whitelist()
def comparar_marca(marca, marca_vin):
    return misma_marca(marca, marca_vin)
