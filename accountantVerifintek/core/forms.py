from datetime import date
from django import forms
from .models import Movimiento, ConceptoMovimiento, Pago, Empresa, Subempresa, UsuarioEmpresa
from decimal import Decimal, InvalidOperation
from django.contrib.auth.models import User

class MovimientoForm(forms.ModelForm):
    # Tipo con placeholder "-----" que no es válido
    tipo = forms.ChoiceField(
        choices=[("", "-----")] + list(Movimiento.TipoMovimiento.choices),
        required=True,
    )

    # Concepto como texto
    concepto_nombre = forms.CharField(
        label="Concepto",
        max_length=255,
    )

    # Número de pagos: mínimo 1
    numero_pagos = forms.IntegerField(
        label="Número de pagos",
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"min": "1", "id": "id_numero_pagos"}),
    )

    # Monto total (permite que JS lo formatee con comas)
    monto_total = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        label="Monto total",
        widget=forms.TextInput(
            attrs={
                "inputmode": "decimal",
                "placeholder": "0.00",
                "id": "id_monto_total",
            }
        ),
    )

    fecha_registro = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "readonly": "readonly"})
    )
    fecha_inicio = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"})
    )

    class Meta:
        model = Movimiento
        fields = [
            "tipo",
            "concepto_nombre",
            "descripcion",
            "monto_total",
            "fecha_registro",
            "fecha_inicio",
            "numero_pagos",
            "frecuencia_pago",
            "observaciones",
        ]
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 2}),
            "observaciones": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Placeholder seleccionado por defecto en "tipo"
        if not self.is_bound:
            self.fields["tipo"].initial = ""

        # Frecuencia por defecto = Único
        self.fields["frecuencia_pago"].initial = Movimiento.FrecuenciaPago.UNICO
        # Asegurar id conocido en el select (para JS)
        self.fields["frecuencia_pago"].widget.attrs.setdefault(
            "id", "id_frecuencia_pago"
        )

        # Fechas por defecto = hoy para formularios nuevos
        if not self.is_bound:
            hoy = date.today()
            self.fields["fecha_registro"].initial = hoy
            self.fields["fecha_inicio"].initial = hoy

    def clean_monto_total(self):
        """
        Permitir formato con comas, ej. 1,000,000.50.
        """
        raw = self.cleaned_data.get("monto_total")

        # Cuando viene como string (por el TextInput) limpiamos comas
        if isinstance(raw, str):
            raw = raw.replace(",", "")

        # Reusar la validación estándar de DecimalField
        return forms.DecimalField(
            max_digits=14,
            decimal_places=2
        ).clean(raw)

class PagoForm(forms.ModelForm):
    fecha_vencimiento = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "readonly": "readonly"})
    )

    fecha_pago = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"})
    )

    # Usar CharField en el formulario para poder aceptar comas
    monto = forms.CharField(
        label="Monto",
        widget=forms.TextInput(
            attrs={
                "inputmode": "decimal",
                "placeholder": "00.00",
                "id": "id_monto",
            }
        ),
    )

    class Meta:
        model = Pago
        fields = ["fecha_vencimiento", "monto", "fecha_pago"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Los campos requeridos a nivel HTML
        self.fields["fecha_vencimiento"].widget.attrs["required"] = "required"
        self.fields["monto"].widget.attrs["required"] = "required"

    def clean_monto(self):
        """
        Recibe el valor como texto, quita comas y lo convierte a Decimal.
        Si está vacío o es inválido, lanza un error claro.
        """
        raw = self.cleaned_data.get("monto", "")

        if raw is None:
            raw = ""
        raw = str(raw).replace(",", "").strip()

        if raw == "":
            raise forms.ValidationError("Ingresa una cantidad.")

        try:
            valor = Decimal(raw)
        except InvalidOperation:
            raise forms.ValidationError("Ingresa una cantidad válida.")

        return valor

# --- FORMULARIOS DE CONFIGURACIÓN / ADMINISTRACIÓN ---

class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        # En el modelo el campo se llama capital_inicial
        fields = ['nombre', 'descripcion', 'capital_inicial']
        labels = {
            'capital_inicial': 'Capital base',
        }

class SubempresaForm(forms.ModelForm):
    class Meta:
        model = Subempresa
        # En el modelo el campo se llama esta_activa
        fields = ['nombre', 'descripcion', 'esta_activa']
        labels = {
            'esta_activa': 'Activa',
        }

class InvitacionUsuarioForm(forms.Form):
    email = forms.EmailField()
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)

class UsuarioEmpresaForm(forms.ModelForm):
    class Meta:
        model = UsuarioEmpresa
        # En el modelo el campo es puede_listar_reportes
        fields = [
            'usuario',
            'empresa',
            'subempresa',
            'rol',
            'puede_leer',
            'puede_escribir',
            'puede_listar_reportes',
        ]
        widgets = {
            'usuario': forms.Select(attrs={'class': 'form-select'}),
            'empresa': forms.Select(attrs={'class': 'form-select'}),
            'subempresa': forms.Select(attrs={'class': 'form-select'}),
            'rol': forms.Select(attrs={'class': 'form-select'}),
            'puede_leer': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'puede_escribir': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'puede_listar_reportes': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
