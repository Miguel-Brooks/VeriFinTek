from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.db.models import UniqueConstraint


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


class Subempresa(models.Model):
    """
    Sub-empresa operativa que pertenece a una empresa 'madre'.
    Los movimientos se registran a nivel de subempresa.
    """

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="subempresas",
    )
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    esta_activa = models.BooleanField(default=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sub-empresa"
        verbose_name_plural = "Sub-empresas"
        unique_together = ("empresa", "nombre")

    def __str__(self) -> str:
        return f"{self.nombre} ({self.empresa.nombre})"


class EmpresaSubempresa(models.Model):
    """
    Tabla de transición explícita Empresa-Subempresa.
    Útil si quieres metadata extra sobre la relación.
    En este diseño, hace espejo de Subempresa. Puedes añadir campos
    como 'porcentaje_participacion' si lo necesitas en el futuro.
    """

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="relaciones_subempresas",
    )
    subempresa = models.ForeignKey(
        Subempresa,
        on_delete=models.CASCADE,
        related_name="relaciones_empresa",
    )
    porcentaje_participacion = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Participación de la empresa en la sub-empresa (opcional).",
    )

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Relación empresa-subempresa"
        verbose_name_plural = "Relaciones empresa-subempresa"
        unique_together = ("empresa", "subempresa")

    def __str__(self) -> str:
        return f"{self.empresa} -> {self.subempresa}"

class UsuarioEmpresa(models.Model):
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

    # Una fila puede ser “todas las subempresas” (subempresa = NULL)
    # o una subempresa concreta
    subempresa = models.ForeignKey(
        Subempresa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios_asignados",
    )

    puede_leer = models.BooleanField(default=True)
    puede_escribir = models.BooleanField(default=False)
    puede_listar_reportes = models.BooleanField(default=False)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Usuario por empresa"
        verbose_name_plural = "Usuarios por empresa"
        constraints = [
            # No duplicar la misma combinación usuario/empresa/subempresa
            UniqueConstraint(
                fields=["usuario", "empresa", "subempresa"],
                name="unique_usuario_empresa_subempresa",
            ),
        ]

    def clean(self):
        """
        Un usuario solo puede pertenecer a una empresa padre.
        Permitimos varias filas para distintas subempresas de esa empresa.
        """
        super().clean()
        if not self.usuario_id or not self.empresa_id:
            return

        qs = UsuarioEmpresa.objects.filter(usuario=self.usuario).exclude(pk=self.pk)
        otras_empresas = qs.exclude(empresa=self.empresa)
        if otras_empresas.exists():
            raise ValidationError(
                "Un usuario solo puede pertenecer a una empresa padre. "
                "Elimina o ajusta las membresías existentes."
            )

    def __str__(self) -> str:
        if self.subempresa:
            return f"{self.usuario} @ {self.empresa} / {self.subempresa}"
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

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        CANCELADO = "CANCELADO", "Cancelado"

    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="movimientos",
        help_text="Empresa propietaria del grupo de sub-empresas.",
    )
    subempresa = models.ForeignKey(
        Subempresa,
        on_delete=models.CASCADE,
        related_name="movimientos",
        help_text="Sub-empresa sobre la que se registra el movimiento.",
        null=True,
        blank=True,
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

    # NUEVOS CAMPOS PARA REPORTES / BÚSQUEDA
    folio = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Folio o referencia externa opcional, útil para búsquedas y reportes.",
    )
    descripcion = models.CharField(
        max_length=255,
        blank=True,
        help_text="Descripción corta que aparecerá en los reportes detallados.",
    )
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
        db_index=True,
        help_text="Estado del movimiento para flujos de aprobación.",
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
        default=FrecuenciaPago.UNICO,
    )

    observaciones = models.TextField(blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Movimiento"
        verbose_name_plural = "Movimientos"
        ordering = ["-fecha_registro", "-id"]
        indexes = [
            # Para filtros por empresa/subempresa + fecha en reportes
            models.Index(
                fields=["empresa", "subempresa", "fecha_registro"],
                name="mov_emp_sub_fecha_idx",
            ),
            # Para filtros por tipo en una empresa
            models.Index(
                fields=["empresa", "tipo"],
                name="mov_emp_tipo_idx",
            ),
            # Para reportes por concepto
            models.Index(
                fields=["empresa", "concepto"],
                name="mov_emp_concepto_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        """Genera folio automáticamente al crear el movimiento."""
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating and not self.folio:
            # 001 = Activo, 010 = Pasivo
            prefix = "001" if self.tipo == self.TipoMovimiento.ACTIVO else "010"
            self.folio = f"{prefix}{self.pk}"
            super().save(update_fields=["folio"])

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} - {self.concepto} ({self.monto_total})"


class Pago(models.Model):
    movimiento = models.ForeignKey(
        Movimiento,
        on_delete=models.CASCADE,
        related_name="pagos",
    )
    numero_pago = models.PositiveIntegerField()
    fecha_vencimiento = models.DateField(db_index=True)
    monto = models.DecimalField(max_digits=20, decimal_places=4)
    esta_pagado = models.BooleanField(default=False, db_index=True)
    fecha_pago = models.DateField(null=True, blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ["fecha_vencimiento", "numero_pago"]
        unique_together = ("movimiento", "numero_pago")
        indexes = [
            models.Index(
                fields=["movimiento", "fecha_vencimiento"],
                name="pago_mov_fecha_idx",
            ),
            models.Index(
                fields=["fecha_vencimiento", "esta_pagado"],
                name="pago_fecha_pagado_idx",
            ),
        ]