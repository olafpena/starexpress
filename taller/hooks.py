app_name = "taller"
app_title = "Taller"
app_publisher = "Ariel Peña"
app_description = "Taller mecánico, hojalatería y pintura: Flujo Hojalatería y Pintura"
app_email = "ariel@example.com"
app_license = "MIT"
required_apps = ["erpnext"]
app_home = "/desk/taller"

# Taller en el selector de apps (/apps). El icono del escritorio, el menú lateral y la
# pantalla de inicio están en desktop_icon/, workspace_sidebar/ y taller/workspace/ (bench migrate).
add_to_apps_screen = [
    {
        "name": app_name,
        "logo": "/assets/taller/images/taller-logo.svg",
        "title": app_title,
        "route": app_home,
    }
]

# Crea roles, estados, acciones, permisos, el workflow y reglas de ejemplo.
# Para regenerar: bench --site <sitio> execute taller.flujo.configuracion.instalar --kwargs "{'reconstruir': True}"
after_install = "taller.flujo.configuracion.instalar"

# Cuando el workflow esté estable puedes versionarlo como fixtures:
#   bench --site <sitio> export-fixtures --app taller
# OJO: con fixtures, cada `bench migrate` sobrescribe lo editado en el Desk.
# fixtures = [
#     {"dt": "Workflow", "filters": [["name", "=", "Flujo Hojalatería y Pintura"]]},
#     {"dt": "Workflow State"},
#     {"dt": "Workflow Action Master"},
#     {"dt": "Regla Transicion Taller"},
# ]

# Validación del VIN y prellenado (taller/vehiculo/vin.py) en los formularios con VIN
doctype_js = {
    "Vehiculo Taller": "public/js/vin.js",
    "Orden Taller": "public/js/fotos.js",
    "Valuacion Taller": "public/js/vin.js",
    "Inventario": ["public/js/vin.js", "public/js/fotos.js"],
    # Botón para regresar a la Orden Taller (public/js/documentos_erp.js)
    "Quotation": "public/js/documentos_erp.js",
    "Sales Order": "public/js/documentos_erp.js",
    "Sales Invoice": "public/js/documentos_erp.js",
}

# Montos y documentos de ERPNext ligados a la Orden Taller (taller/erp/documentos.py)
_eventos_documento = {
    evento: "taller.erp.documentos.al_cambiar_documento"
    for evento in ("on_submit", "on_cancel", "on_trash", "on_update_after_submit")
}
doc_events = {
    # Fotos y firmas de las unidades siempre privadas (taller/fotos.py)
    "File": {"after_insert": "taller.fotos.forzar_privado"},
    "Quotation": _eventos_documento,
    "Sales Order": _eventos_documento,
    "Sales Invoice": _eventos_documento,
    "Payment Entry": {
        "on_submit": "taller.erp.documentos.al_cambiar_pago",
        "on_cancel": "taller.erp.documentos.al_cambiar_pago",
    },
    # Costeo (taller/erp/costeo.py)
    "Stock Entry": {
        "on_submit": "taller.erp.costeo.al_cambiar_consumo",
        "on_cancel": "taller.erp.costeo.al_cambiar_consumo",
    },
    "Timesheet": {
        "on_submit": "taller.erp.costeo.al_cambiar_timesheet",
        "on_cancel": "taller.erp.costeo.al_cambiar_timesheet",
    },
}
