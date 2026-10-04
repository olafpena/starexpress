"""
Lector del "Reporte Completo" de Audatex (AudaEnterpriseGold, Solera).

`leer_pdf(contenido)` recibe los bytes del PDF y devuelve un dict con:

    encabezado  número de reclamo, expediente, póliza, estado, fechas, autorizado por...
    vehiculo    marca, modelo, año, placas, VIN, color, valor de mercado
    ut_por_hora unidades de trabajo por hora ("T.Base 10 UT = 1 HR")
    tarifa_hora precio por hora de la mano de obra
    partidas    lista de dicts: tipo, referencia, numero_pieza, descripcion,
                ut, cantidad, precio_unitario, descuento
    totales     totales que imprime el documento (para cuadrar las partidas)
    notas       notas de la aseguradora

El PDF viene cifrado sin contraseña de usuario; pypdf lo abre con contraseña vacía.
`leer_texto(texto)` hace lo mismo sobre el texto ya extraído (modo layout); no
depende de Frappe para poder probarlo aparte.

Partidas por sección:

    PIEZAS SUSTITUIDAS         Refacción (precio, DCTO %)
    Materiales de Reparación   Material de reparación
    Mano de Obra / Hojal       Mano de obra hojalatería (cantidad = UT / UT por hora)
    PINTURA DE CARROCERIA      Mano de obra pintura, más "TIEMPO PREPARACION"
    RESUMEN MATERIALES PINTURA Material de pintura
"""

import re

REFACCION = "Refacción"
MO_HOJALATERIA = "Mano de obra hojalatería"
MO_PINTURA = "Mano de obra pintura"
MATERIAL_PINTURA = "Material de pintura"
MATERIAL_REPARACION = "Material de reparación"
OTRO = "Otro"
TIPOS = [REFACCION, MO_HOJALATERIA, MO_PINTURA, MATERIAL_PINTURA, MATERIAL_REPARACION, OTRO]

MONTO = r"-?\$\s?[\d,]+\.\d{2}"
_RUIDO = (
    re.compile(r"AudaEnterpriseGold"),
    re.compile(r"^\s*Esta valuaci[oó]n est[aá] sujeta"),
    re.compile(r"^\s*da[ñn]os ocultos y/o suspensi[oó]n\s*$"),
    re.compile(r"^\s*Page:\s*\d+\s+of\s+\d+\s*$"),
)

ENCABEZADO = {
    "numero_reclamo": "Número de Reclamo",
    "numero_expediente": "Número de Expediente",
    "numero_poliza": "Número de Poliza",
    "version": "Versión",
    "estado": "Estado de la Valuación",
    "causa": "Causa del Accidente",
    "proveedor": "Proveedor de Trabajo",
    "tipo_expediente": "Tipo de Expediente",
    "taller": "Taller de Reparación",
    "autorizado_por": "Autorizado por",
    "fecha_accidente": "Fecha del Accidente",
    "fecha_inspeccion": "Fecha de Inspección",
    "fecha_autorizacion": "Fecha Autorización",
}
FECHAS = {"fecha_accidente", "fecha_inspeccion", "fecha_autorizacion"}

VEHICULO = {
    "marca": "Fabricante",
    "modelo": "Modelo",
    "submodelo": "Sub Modelo",
    "placas": "No. Placa",
    "vin": "No. VIN Visual",
    "vin_poliza": "No. VIN Poliza",
    "color": "Color Vehículo",
    "anio": "Año de Fabricación",
    "tipo_motor": "Tipo de Motor",
    "transmision": "Transmisión",
    "valor_mercado": "Valor Mercado",
}

TOTALES = {
    "total_piezas": "TOTAL PIEZAS",
    "total_mo_hojalateria": "TOTAL M.O. HOJAL",
    "total_materiales_reparacion": "TOTAL MATERIALES DE REPARACI",
    "total_mo_pintura": "TOTAL M.O. PINTURA",
    "total_materiales_pintura": "TOTAL MATERIALES",
    "suma_sin_iva": "SUMA TOTAL SIN IVA",
    "total_deducciones": "TOTAL DE DEDUCCIONES",
    "subtotal": "SUBTOTAL",
    "iva": "IVA @",
    "total_con_iva": "SUMA TOTAL CON IVA",
    "gran_total": "GRAN TOTAL",
}


class ErrorValuacion(Exception):
    pass


# ==========================================================================
# Entrada
# ==========================================================================
def leer_pdf(contenido):
    return leer_texto(extraer_texto(contenido))


def extraer_texto(contenido):
    from io import BytesIO

    from pypdf import PdfReader

    lector = PdfReader(BytesIO(contenido))
    if lector.is_encrypted and not lector.decrypt(""):
        raise ErrorValuacion("El PDF está protegido con contraseña.")
    return "\n".join(p.extract_text(extraction_mode="layout") or "" for p in lector.pages)


def leer_texto(texto):
    lineas = _limpiar(texto)
    if not any("AUDATEX" in l.upper() or "Número de Reclamo" in l for l in lineas[:15]):
        raise ErrorValuacion("El archivo no parece un reporte de valuación de Audatex.")

    datos = {
        "encabezado": {c: _campo(lineas, e) for c, e in ENCABEZADO.items()},
        "vehiculo": {c: _campo(lineas, e) for c, e in VEHICULO.items()},
        "partidas": [],
        "totales": _totales(lineas),
        "notas": _notas(lineas),
    }
    for c in FECHAS:
        datos["encabezado"][c] = _fecha(datos["encabezado"][c])
    vehiculo = datos["vehiculo"]
    vehiculo["vin"] = vehiculo["vin"] or vehiculo.pop("vin_poliza", None)
    vehiculo.pop("vin_poliza", None)
    vehiculo["valor_mercado"] = _monto(vehiculo["valor_mercado"]) if vehiculo["valor_mercado"] else None
    vehiculo["anio"] = int(vehiculo["anio"]) if (vehiculo["anio"] or "").isdigit() else None

    ut_hora, tarifa = _tarifa(lineas, "Mano de Obra") or _tarifa(lineas, "PINTURA DE CARROCERIA") or (10, 0)
    datos["ut_por_hora"], datos["tarifa_hora"] = ut_hora, tarifa

    partidas = datos["partidas"]
    partidas += _piezas(_seccion(lineas, "PIEZAS SUSTITUIDAS", ["Materiales de Reparaci", "Mano de Obra"]))
    partidas += _materiales_reparacion(_seccion(lineas, "Materiales de Reparaci", ["Mano de Obra"]))
    partidas += _mano_obra(_seccion(lineas, "Mano de Obra", ["Total Unidades de Trabajo", "PINTURA DE CARROCERIA"]),
                           MO_HOJALATERIA, ut_hora, tarifa)
    ut_pint, tarifa_pint = _tarifa(lineas, "PINTURA DE CARROCERIA") or (ut_hora, tarifa)
    partidas += _mano_obra(_seccion(lineas, "PINTURA DE CARROCERIA", ["RESUMEN M.O PINTURA"]),
                           MO_PINTURA, ut_pint, tarifa_pint)
    partidas += _preparacion_pintura(_seccion(lineas, "RESUMEN M.O PINTURA", ["RESUMEN MATERIALES PINTURA"]),
                                     ut_pint, tarifa_pint)
    partidas += _materiales_pintura(_seccion(lineas, "RESUMEN MATERIALES PINTURA", ["Notas del Taller", "Notas de la"]))
    if not partidas:
        raise ErrorValuacion("No se encontraron partidas en la valuación.")
    return datos


# ==========================================================================
# Utilidades
# ==========================================================================
def _limpiar(texto):
    lineas = []
    for linea in texto.splitlines():
        if not linea.strip() or any(r.search(linea) for r in _RUIDO):
            continue
        lineas.append(linea.rstrip())
    return lineas


def _monto(texto):
    m = re.search(MONTO, texto or "")
    if not m:
        return 0.0
    valor = m.group(0).replace("$", "").replace(",", "").replace(" ", "")
    return float(valor)


def _fecha(texto):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texto or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _campo(lineas, etiqueta):
    """Valor de "Etiqueta:   valor   Otra etiqueta: ..." (dos columnas)."""
    for prefijo in (r"(?:^\s*|\s{2,})", r"\s"):
        patron = re.compile(prefijo + re.escape(etiqueta) + r":?[ \t]+(\S.*?)(?=\s{3,}|$)")
        for i, linea in enumerate(lineas):
            m = patron.search(linea)
            if not m:
                continue
            valor = m.group(1).strip()
            # Continuación en la línea siguiente, alineada en la misma columna
            if i + 1 < len(lineas):
                siguiente = lineas[i + 1]
                sangria = len(siguiente) - len(siguiente.lstrip())
                if sangria == m.start(1) and ":" not in siguiente:
                    valor += " " + re.split(r"\s{3,}", siguiente.strip())[0]
            return _cortar_en_etiqueta(valor, etiqueta) or None
    return None


def _cortar_en_etiqueta(valor, propia):
    """Si dos columnas quedaron pegadas, corta el valor donde empieza otra etiqueta."""
    for etiqueta in list(ENCABEZADO.values()) + list(VEHICULO.values()):
        if etiqueta != propia and etiqueta not in propia:
            i = valor.find(etiqueta)
            if i > 0:
                valor = valor[:i]
    return valor.strip()


def _seccion(lineas, inicio, fines):
    dentro, resultado = False, []
    for linea in lineas:
        texto = linea.strip()
        if not dentro:
            dentro = texto.startswith(inicio)
            continue
        if any(texto.startswith(f) for f in fines):
            break
        resultado.append(linea)
    return resultado


def _tarifa(lineas, seccion):
    patron = re.compile(r"(\d+)\s*UT\s*=\s*1\s*HR\.?\s*PRECIO\s*=?\s*(" + MONTO + r")", re.I)
    for linea in _seccion(lineas, seccion, ["Total Unidades", "RESUMEN", "TOTAL"])[:6] + [
            l for l in lineas if l.strip().startswith(seccion)]:
        m = patron.search(linea)
        if m:
            return int(m.group(1)), _monto(m.group(2))
    return None


def _columnas(linea):
    return [c for c in re.split(r"\s{2,}", linea.strip()) if c]


def _totales(lineas):
    resumen = _seccion(lineas, "RESUMEN FINAL", ["OBSERVACIONES"]) or lineas
    totales = {}
    for campo, etiqueta in TOTALES.items():
        for linea in resumen:
            texto = linea.strip()
            if texto.startswith(etiqueta) and re.search(MONTO, texto):
                if campo == "total_materiales_pintura" and "REPARACI" in texto:
                    continue
                totales[campo] = _monto(re.findall(MONTO, texto)[-1])
                break
    return totales


def _notas(lineas):
    bloque = _seccion(lineas, "Notas de la Aseguradora", ["Historial", "Códigos Opcionales", "RESUMEN FINAL"])
    return "\n".join(l.strip() for l in bloque) or None


def _partida(tipo, descripcion, cantidad, precio_unitario, referencia=None, numero_pieza=None,
             descuento=0.0, ut=None):
    return {"tipo": tipo, "referencia": referencia, "numero_pieza": numero_pieza,
            "descripcion": (descripcion or "").strip() or tipo, "ut": ut, "cantidad": cantidad,
            "precio_unitario": precio_unitario, "descuento": descuento}


# ==========================================================================
# Secciones
# ==========================================================================
def _piezas(lineas):
    partidas = []
    for linea in lineas:
        cols = _columnas(linea)
        if not cols or not re.match(MONTO, cols[0]):
            continue
        m = re.match(r"(" + MONTO + r")\s*([*A-Z])?$", cols[0])
        precio = _monto(m.group(1)) if m else _monto(cols[0])
        resto = cols[1:]
        if resto and re.fullmatch(r"[*A-Z]", resto[0]):
            resto = resto[1:]
        descuento = 0.0
        for c in list(resto):
            if re.fullmatch(r"\d+(?:\.\d+)?%", c):
                descuento = float(c[:-1])
                resto.remove(c)
        pos = resto.pop() if len(resto) > 1 and re.fullmatch(r"\d+", resto[-1]) else None
        numero_pieza = resto.pop() if len(resto) > 2 else None
        referencia = resto[0] if resto else None
        descripcion = " ".join(resto[1:])
        partidas.append(_partida(REFACCION, descripcion, 1, precio, referencia or pos,
                                 numero_pieza, descuento))
    return partidas


def _materiales_reparacion(lineas):
    """Descripción en varias líneas alrededor de la línea "Pos.  texto  $precio"."""
    filas = [l for l in lineas if not l.strip().startswith("Pos.")]
    anclas = [i for i, l in enumerate(filas) if re.search(MONTO + r"\s*$", l)]
    partidas = []
    for n, i in enumerate(anclas):
        # Las líneas entre dos anclas se reparten: la primera mitad es del anterior
        previas = filas[(anclas[n - 1] + 1 if n else 0):i]
        posteriores = filas[i + 1:(anclas[n + 1] if n + 1 < len(anclas) else len(filas))]
        antes = previas[(len(previas) + 1) // 2:] if n else previas
        despues = posteriores[:(len(posteriores) + 1) // 2] if n + 1 < len(anclas) else posteriores
        cols = _columnas(filas[i])
        pos = cols[0] if len(cols) >= 3 else None
        medio = " ".join(cols[1:-1] if pos else cols[:-1])
        descripcion = " ".join([l.strip() for l in antes] + [medio] + [l.strip() for l in despues])
        partidas.append(_partida(MATERIAL_REPARACION, descripcion, 1, _monto(cols[-1]), pos))
    return partidas


_FILA_MO = re.compile(r"^(?P<prefijo>.*?)\s+(?P<ut>\d+(?:\.\d+)?)\s*(?:R)?\s+(?P<precio>" + MONTO + r")\s*$")


def _mano_obra(lineas, tipo, ut_hora, tarifa):
    partidas = []
    for linea in lineas:
        texto = linea.strip()
        if texto.startswith(("NR ", "Total", "TOTAL", "T.", "T ")) or "UT = 1 HR" in texto.upper():
            continue
        m = _FILA_MO.match(linea)
        if not m:
            continue
        cols = _columnas(m.group("prefijo"))
        if not cols:
            continue
        referencia = cols[0] if len(cols) > 1 else None
        descripcion = " ".join(cols[1:]) if referencia else cols[0]
        ut = float(m.group("ut"))
        importe = _monto(m.group("precio"))
        cantidad, precio = _horas(ut, ut_hora, tarifa, importe)
        partidas.append(_partida(tipo, descripcion, cantidad, precio, referencia, ut=ut))
    return partidas


def _preparacion_pintura(lineas, ut_hora, tarifa):
    for linea in lineas:
        if linea.strip().upper().startswith("TIEMPO PREPARACION"):
            m = _FILA_MO.match(linea)
            if m:
                ut = float(m.group("ut"))
                cantidad, precio = _horas(ut, ut_hora, tarifa, _monto(m.group("precio")))
                return [_partida(MO_PINTURA, "Tiempo de preparación (pintura)", cantidad, precio, ut=ut)]
    return []


def _materiales_pintura(lineas):
    partidas = []
    for linea in lineas:
        cols = _columnas(linea)
        if len(cols) < 2 or not re.fullmatch(MONTO, cols[-1]) or cols[0].upper().startswith("TOTAL"):
            continue
        partidas.append(_partida(MATERIAL_PINTURA, " ".join(cols[:-1]).capitalize(), 1, _monto(cols[-1])))
    return partidas


def _horas(ut, ut_hora, tarifa, importe):
    """Horas = UT / UT por hora; si no cuadra con el importe, cantidad 1 al importe."""
    horas = round(ut / ut_hora, 4) if ut_hora else 0
    if tarifa and horas and abs(round(horas * tarifa, 2) - importe) <= 0.01:
        return horas, tarifa
    return 1, importe
