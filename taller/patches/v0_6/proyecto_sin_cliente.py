"""Quita el cliente de los proyectos de las órdenes: Aseguradora factura a dos clientes."""

import frappe


def execute():
    proyectos = frappe.get_all("Orden Taller", filters={"proyecto": ["is", "set"]}, pluck="proyecto")
    for proyecto in proyectos:
        if frappe.db.get_value("Project", proyecto, "customer"):
            frappe.db.set_value("Project", proyecto, "customer", None, update_modified=False)
