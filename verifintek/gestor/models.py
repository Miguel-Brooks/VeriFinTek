from django.db import models
from django.core.exceptions import ValidationError

class SubEmpresa(models.Model):
    nombre = models.CharField(max_length=255) # Nombre de la subempresa
    area = models.CharField(max_length=255) # Área de la subempresa
    estado = models.CharField(
        max_length=10,
        choices=[('activa', 'Activa'), ('inactiva', 'Inactiva')] # Estado de la subempresa
    )
    empleados = models.IntegerField() # Número de empleados
    balance = models.DecimalField(max_digits=20, decimal_places=2)  # Balance financiero


    class Meta:
        pass

    def __str__(self):
        return self.nombre

    def puede_gestionar(self, usuario):
        """
        Verifica si el usuario tiene permisos de gestión en la subempresa.
        """
        return (
            usuario.has_perm('gestor.add_subempresa') or
            usuario.has_perm('gestor.change_subempresa')
        )


class Cuenta(models.Model):
    codigo_cuenta = models.CharField(max_length=20, unique=True)
    nombre_cuenta = models.CharField(max_length=255)
    tipo_cuenta = models.CharField(
        max_length=50,
        choices=[
            ('activo', 'Activo'),
            ('pasivo', 'Pasivo'),
            ('patrimonio', 'Patrimonio'),
            ('ingreso', 'Ingreso'),
            ('gasto', 'Gasto'),
        ]
    )
    saldo = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        pass

    def __str__(self):
        return self.nombre_cuenta

    def puede_editar(self, usuario):
        return usuario.has_perm('gestor.change_cuenta')


class Poliza(models.Model):
    descripcion = models.CharField(max_length=255)
    estado = models.CharField(
        max_length=10,
        choices=[
            ('pendiente', 'Pendiente'),
            ('aprobada', 'Aprobada'),
            ('rechazada', 'Rechazada'),
        ]
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_revision = models.DateTimeField(null=True, blank=True)
    fecha_aprovacion = models.DateTimeField(null=True, blank=True)
    monto_total = models.DecimalField(max_digits=20, decimal_places=2)
    subempresa = models.ForeignKey(SubEmpresa, on_delete=models.CASCADE)
    creado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        related_name='polizas_creadas',
        null=True, blank=True
    )
    revisado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        related_name='polizas_revisadas',
        null=True, blank=True
    )
    aprobado_por = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        related_name='polizas_aprobadas',
        null=True, blank=True
    )

    class Meta:
        permissions = [
            ("can_approve_poliza", "Can approve poliza"),
        ]

    def __str__(self):
        return f'Póliza {self.id} - {self.descripcion}'

    def validar(self):
        if not self.pk:
            return

        partidas = self.partida_set.all()
        if not partidas.exists():
            return

        total_debito = sum(p.monto_debito for p in partidas)
        total_credito = sum(p.monto_credito for p in partidas)

        if total_debito != total_credito:
            raise ValidationError(
                "La suma de débitos debe ser igual a la suma de créditos."
            )
        

    def save(self, *args, **kwargs):
        creating = self.pk is None

        super().save(*args, **kwargs)

        if not creating:
            self.validar()

    def puede_aprobar(self, usuario):
        return usuario.has_perm('gestor.can_approve_poliza')


class Partida(models.Model):
    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE)
    cuenta = models.ForeignKey(Cuenta, on_delete=models.CASCADE)
    descripcion = models.CharField(max_length=255)
    monto_debito = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    monto_credito = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    class Meta:
        pass

    def __str__(self):
        return f'{self.cuenta.nombre_cuenta} - {self.monto_debito} / {self.monto_credito}'

    def puede_editar(self, usuario):
        return usuario.has_perm('gestor.change_partida')


class BalanceHistorico(models.Model):
    subempresa = models.ForeignKey(SubEmpresa, on_delete=models.CASCADE)
    fecha = models.DateField()
    balance = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        pass

    def __str__(self):
        return f'Balance {self.subempresa.nombre} en {self.fecha}'

    def puede_ver(self, usuario):
        return usuario.has_perm('gestor.view_balancehistorico')