from django import forms
from .models import SubEmpresa, BalanceHistorico, Cuenta, Poliza

class SubEmpresaForm(forms.ModelForm):
    class Meta:
        model = SubEmpresa
        fields = ['nombre', 'area', 'estado', 'empleados', 'balance']