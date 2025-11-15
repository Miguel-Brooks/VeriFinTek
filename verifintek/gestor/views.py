from django.shortcuts import redirect, render
from .models import SubEmpresa, BalanceHistorico, Cuenta, Poliza
from .forms import SubEmpresaForm 
from django.db.models import Sum


def panel_general(request):
    return render(request, 'gestor/index.html')

def subempresas_view(request):
    subempresas = SubEmpresa.objects.all()
    context = {'subempresas': subempresas}
    #total_subempresas = subempresas.count()
    empresas_activas = subempresas.filter(estado='activa').count()
    balance_total = subempresas.aggregate(total=Sum('balance'))['total'] or 0
    context.update({
        'subempresas': subempresas,
        #'total_subempresas': total_subempresas,
        'empresas_activas': empresas_activas,
        'balance_total': balance_total,
    })
    return render(request, 'gestor/subempresas.html', context)

def subempresa_nueva(request):
    if request.method == 'POST':
        form = SubEmpresaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('subempresas')
    else:
        form = SubEmpresaForm()
    return render(request, 'gestor/subempresa_nueva.html', {'form': form})


def captura_view(request):
    return render(request, 'gestor/captura.html')

def flujo_view(request):
    return render(request, 'gestor/flujo.html')

def balance_view(request):
    balance = BalanceHistorico.objects.all()
    context = {'balance': balance}
    return render(request, 'gestor/balance.html', context)