from django.shortcuts import render
from .models import SubEmpresa, BalanceHistorico, Cuenta, Poliza


def panel_general(request):
    return render(request, 'gestor/index.html')

def subempresas_view(request):
    subempresas = SubEmpresa.objects.all()
    context = {'subempresas': subempresas}
    return render(request, 'gestor/subempresas.html', context)

def captura_view(request):
    return render(request, 'gestor/captura.html')

def flujo_view(request):
    return render(request, 'gestor/flujo.html')

def balance_view(request):
    balance = BalanceHistorico.objects.all()
    context = {'balance': balance}
    return render(request, 'gestor/balance.html', context)