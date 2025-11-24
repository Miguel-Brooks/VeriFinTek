# core/admin.py
from django.contrib import admin
from .models import Empresa, UsuarioEmpresa, ConceptoMovimiento, Movimiento, Pago


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "capital_inicial", "creado_en")
    search_fields = ("nombre",)


@admin.register(UsuarioEmpresa)
class UsuarioEmpresaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "empresa", "rol", "puede_leer", "puede_escribir", "puede_listar_reportes")
    list_filter = ("rol", "empresa")
    search_fields = ("usuario__username", "empresa__nombre")


@admin.register(ConceptoMovimiento)
class ConceptoMovimientoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo_sugerido", "creado_en")
    search_fields = ("nombre",)


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "tipo", "concepto", "monto_total", "fecha_registro")
    list_filter = ("empresa", "tipo", "fecha_registro")
    search_fields = ("concepto__nombre", "empresa__nombre")


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("movimiento", "numero_pago", "fecha_vencimiento", "monto", "esta_pagado")
    list_filter = ("esta_pagado", "fecha_vencimiento")
    search_fields = ("movimiento__empresa__nombre",)
