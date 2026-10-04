app_name = "taller"
app_title = "Taller"
app_publisher = "Ariel Peña"
app_description = "Taller mecánico, hojalatería y pintura: Flujo Hojalatería y Pintura"
app_email = "ariel@example.com"
app_license = "MIT"
required_apps = ["erpnext"]

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

# Montos y documentos de ERPNext ligados a la Orden Taller (taller/erp/documentos.py)
_eventos_documento = {
    evento: "taller.erp.documentos.al_cambiar_documento"
    for evento in ("on_submit", "on_cancel", "on_trash")
}
doc_events = {
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
