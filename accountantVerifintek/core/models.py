from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Empresa(models.Model):
    nombre = models.CharField(max_length=255, unique=True)
    descripcion = models.TextField(blank=True)
    # Capital inicial opcional, útil para análisis de patrimonio
    capital_inicial = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Capital inicial registrado de la empresa.",
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

    def __str__(self) -> str:
        return self.nombre


class UsuarioEmpresa(models.Model):
    """
    Relación muchos-a-muchos entre Usuario y Empresa,
    con rol y permisos por empresa.
    """

    class Rol(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        FINANCIERO = "FINANCIERO", "Financiero / Capturista"
        DIRECTOR = "DIRECTOR", "Director"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="membresias",
    )
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="usuarios",
    )
    rol = models.CharField(
        max_length=15,
        choices=Rol.choices,
        default=Rol.FINANCIERO,
    )

    # Permisos básicos por empresa (R, W, L)
    puede_leer = models.BooleanField(default=True)
    puede_escribir = models.BooleanField(default=False)
    puede_listar_reportes = models.BooleanField(default=False)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Usuario por empresa"
        verbose_name_plural = "Usuarios por empresa"
        unique_together = ("usuario", "empresa")

    def __str__(self) -> str:
        return f"{self.usuario} @ {self.empresa} ({self.rol})"


class ConceptoMovimiento(models.Model):
    class TipoSugerido(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        PASIVO = "PASIVO", "Pasivo"

    nombre = models.CharField(max_length=255, unique=True)
    descripcion = models.TextField(blank=True)
    tipo_sugerido = models.CharField(
        max_length=10,
        choices=TipoSugerido.choices,
        blank=True,
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Concepto de movimiento"
        verbose_name_plural = "Conceptos de movimiento"

    def __str__(self) -> str:
        return self.nombre


class Movimiento(models.Model):
    class TipoMovimiento(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        PASIVO = "PASIVO", "Pasivo"

    class FrecuenciaPago(models.TextChoices):
        UNICO = "UNICO", "Único"
        SEMANAL = "SEMANAL", "Semanal"
        QUINCENAL = "QUINCENAL", "Quincenal"
        MENSUAL = "MENSUAL", "Mensual"
        ANUAL = "ANUAL", "Anual"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="movimientos",
    )
    usuario_captura = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_capturados",
    )
    tipo = models.CharField(
        max_length=10,
        choices=TipoMovimiento.choices,
    )
    concepto = models.ForeignKey(
        ConceptoMovimiento,
        on_delete=models.PROTECT,
        related_name="movimientos",
    )

    monto_total = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Monto total del movimiento.",
    )
    fecha_registro = models.DateField()
    fecha_inicio = models.DateField(
        help_text="Fecha a partir de la cual empiezan los pagos.",
    )

    numero_pagos = models.PositiveIntegerField(
        default=1,
        help_text="Número total de pagos para finiquitar el movimiento.",
    )
    frecuencia_pago = models.CharField(
        max_length=10,
        choices=FrecuenciaPago.choices,
        default=FrecuenciaPago.MENSUAL,
    )

    observaciones = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Movimiento"
        verbose_name_plural = "Movimientos"
        ordering = ["-fecha_registro", "-id"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} - {self.concepto} ({self.monto_total})"


class Pago(models.Model):
    movimiento = models.ForeignKey(
        Movimiento,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    numero_pago = models.PositiveIntegerField(
        help_text="Consecutivo del pago dentro del movimiento.",
    )
    fecha_vencimiento = models.DateField()
    monto = models.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    esta_pagado = models.BooleanField(default=False)
    fecha_pago = models.DateField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["fecha_vencimiento", "numero_pago"]
        unique_together = ("movimiento", "numero_pago")

    def __str__(self) -> str:
        return f"Pago {self.numero_pago} de {self.movimiento_id}"
