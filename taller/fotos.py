"""
Fotos de la unidad (tabla hija Foto Orden Taller de la orden y del inventario).

  * forzar_privado (File.after_insert): las fotos y firmas de las unidades nunca
    quedan públicas, aunque se suban por API o se desmarque "Privado".
  * procesar_fotos (validate de Orden Taller e Inventario): optimiza las fotos
    grandes y crea su miniatura privada.

La miniatura se hace con Pillow en lugar de File.make_thumbnail, porque esa
función escribe en la carpeta pública del sitio y no sirve para archivos privados.
"""

import io

import frappe
from frappe.utils import cint, now_datetime
from PIL import Image, ImageOps

DOCTYPES_CON_FOTOS = ("Orden Taller", "Vehiculo Taller", "Inventario")
CAMPO_FOTOS = "fotos"
LIMITE_BYTES = 400 * 1024
LADO_MINIATURA = 320
PREFIJO_MINIATURA = "min_"


def forzar_privado(doc, method=None):
    """File.after_insert: mueve a privado un archivo público de una unidad.

    Corre después de que Frappe guardó el archivo en disco (File.before_insert lo
    guarda con el is_private que trae), así que no basta con cambiar la bandera:
    hay que mover el archivo y actualizar su URL.
    """
    if doc.attached_to_doctype not in DOCTYPES_CON_FOTOS or cint(doc.is_private):
        return
    if doc.is_folder or doc.is_remote_file:
        return
    url_publica = doc.file_url
    compartido = frappe.db.count("File", {"file_url": url_publica, "name": ["!=", doc.name]})
    doc.is_private = 1
    if compartido:
        # Otro documento usa el mismo archivo público: se guarda una copia privada
        doc.save_file(content=doc.get_content())
    else:
        doc.handle_is_private_changed()
    doc.db_set({"is_private": 1, "file_url": doc.file_url}, update_modified=False)
    if doc.attached_to_field and doc.attached_to_name:
        meta = frappe.get_meta(doc.attached_to_doctype)
        if meta.has_field(doc.attached_to_field) and frappe.db.get_value(
                doc.attached_to_doctype, doc.attached_to_name, doc.attached_to_field) == url_publica:
            frappe.db.set_value(doc.attached_to_doctype, doc.attached_to_name, doc.attached_to_field,
                                doc.file_url, update_modified=False)


def archivo_de(file_url, doc=None):
    """File de una URL, de preferencia el adjunto al documento."""
    if not file_url:
        return None
    filtros = {"file_url": file_url}
    if doc and not doc.is_new():
        nombre = frappe.db.get_value("File", dict(filtros, attached_to_name=doc.name))
        if nombre:
            return frappe.get_doc("File", nombre)
    nombre = frappe.db.get_value("File", filtros, order_by="creation desc")
    return frappe.get_doc("File", nombre) if nombre else None


def etapa_de_paso(paso):
    """Etapa de una foto tomada en la orden, según el paso en que está."""
    if paso in ("Recolección", "Recepción"):
        return paso
    if (paso or "").startswith("Control de calidad"):
        return "Calidad"
    if paso in ("Entrega", "Cobro", "Facturación"):
        return "Entrega"
    return "Proceso" if paso and paso not in ("Nueva", "Cancelada") else None


def procesar_fotos(doc, etapa=None):
    """Optimiza cada foto nueva, le crea su miniatura y llena quién, cuándo y en qué paso."""
    for fila in doc.get(CAMPO_FOTOS) or []:
        fila.etapa = fila.etapa or etapa or etapa_de_paso(doc.get("paso_actual"))
        fila.paso = fila.paso or doc.get("paso_actual")
        fila.tomada_por = fila.tomada_por or frappe.session.user
        fila.fecha = fila.fecha or now_datetime()
        if not fila.imagen or fila.miniatura:
            continue
        archivo = archivo_de(fila.imagen, doc)
        if not archivo:
            continue
        try:
            if (archivo.file_size or 0) > LIMITE_BYTES:
                archivo.optimize_file()
                fila.imagen = archivo.file_url
            fila.miniatura = crear_miniatura(archivo, doc)
        except Exception:
            # Una imagen que Pillow no puede abrir se queda sin miniatura; no frena el guardado
            frappe.log_error(title=f"Miniatura de {archivo.name}")


def crear_miniatura(archivo, doc):
    imagen = ImageOps.exif_transpose(Image.open(io.BytesIO(archivo.get_content())))
    imagen.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
    salida = io.BytesIO()
    imagen.convert("RGB").save(salida, format="JPEG", quality=75)
    miniatura = frappe.get_doc({
        "doctype": "File",
        "file_name": f"{PREFIJO_MINIATURA}{archivo.name}.jpg",
        "content": salida.getvalue(),
        "is_private": 1,
        "attached_to_doctype": doc.doctype,
        "attached_to_name": None if doc.is_new() else doc.name,
    }).insert(ignore_permissions=True)
    return miniatura.file_url
