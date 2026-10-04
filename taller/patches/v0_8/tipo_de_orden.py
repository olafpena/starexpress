"""
Tipo de orden (Hojalatería y Pintura / Mecánica): las órdenes existentes son de
Hojalatería y Pintura, y el workflow se reconstruye para que sus transiciones
apliquen solo a ese tipo.
"""

import frappe

from taller.flujo import configuracion as conf


def execute():
    frappe.db.sql(f"""update `tab{conf.DOCTYPE}` set {conf.CAMPO_TIPO_ORDEN} = %s
                      where ifnull({conf.CAMPO_TIPO_ORDEN}, '') = ''""", conf.TIPO_ORDEN_FLUJO)
    conf.instalar(reconstruir=True)
