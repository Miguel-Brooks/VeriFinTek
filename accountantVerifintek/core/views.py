from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Empresa, Subempresa, UsuarioEmpresa, Movimiento
from django.db.models import Sum, Q

# ----- HELPERS -----
def _contexto_usuario(request):
    """Helper: empresas, subempresas y selección actual para el usuario."""
    
    '''
    empresas = (
        Empresa.objects.filter(usuarios__usuario=request.user)
        .distinct()
    )
    '''

    if request.user.is_superuser:
        empresas = Empresa.objects.all().prefetch_related("subempresas")
    else:
        empresas = (
            Empresa.objects.filter(
                usuarios__usuario=request.user,
                usuarios__puede_leer=True,
            )
            .distinct()
            .prefetch_related("subempresas")
        )

    empresa_id = request.session.get("empresa_id")
    subempresa_id = request.session.get("subempresa_id")

    empresa_actual = None
    subempresa_actual = None
    subempresas = Subempresa.objects.none()

    if empresa_id:
        empresa_actual = empresas.filter(id=empresa_id).first()
        if empresa_actual:
            subempresas = empresa_actual.subempresas.filter(esta_activa=True)

    if subempresa_id and subempresas.exists():
        subempresa_actual = subempresas.filter(id=subempresa_id).first()

    return {
        "empresas_disponibles": empresas,
        "subempresas_disponibles": subempresas,
        "empresa_actual": empresa_actual,
        "subempresa_actual": subempresa_actual,
    }

    

@login_required(login_url="core:login")
def seleccionar_contexto_view(request):
      
    if request.method != "POST":
        return redirect("core:dashboard")

    raw = request.POST.get("contexto", "")
    tipo, _, pk = raw.partition(":")

    empresa = None
    subempresa = None

    # Resolver empresa / subempresa según el valor del select
    if tipo == "empresa" and pk.isdigit():
        empresa = get_object_or_404(Empresa, id=pk)
    elif tipo == "subempresa" and pk.isdigit():
        subempresa = get_object_or_404(Subempresa, id=pk)
        empresa = subempresa.empresa
    else:
        messages.error(request, "Selección inválida.")
        return redirect("core:dashboard")

    if request.user.is_superuser:
        tiene_membresia = True
    else:
        tiene_membresia = UsuarioEmpresa.objects.filter(
            usuario=request.user,
            empresa=empresa,
            puede_leer=True,
        ).exists()
    if not tiene_membresia:
        messages.error(request, "No tienes acceso a esta empresa.")
        return redirect("core:dashboard")


    # Guardar en sesión
    request.session["empresa_id"] = empresa.id
    request.session["subempresa_id"] = subempresa.id if subempresa else None

    return redirect("core:dashboard")

def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            next_url = request.GET.get("next") or reverse("core:dashboard")
            return redirect(next_url)
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")

    return render(request, "core/login.html")


def logout_view(request):
    # Solo aceptar POST para evitar CSRF de logout por GET
    if request.method == "POST":
        # Cerrar sesión Django
        logout(request)
        # Limpiar contexto de empresa/subempresa si sigue en la sesión
        request.session.pop("empresa_id", None)
        request.session.pop("subempresa_id", None)
        return redirect("core:login")

    # Si entra por GET, redirigir sin hacer logout real
    return redirect("core:login")


@login_required(login_url="core:login")
def dashboard_view(request):
    ctx = _contexto_usuario(request)

    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]

    #Si no hay empresa seleccionada, no calcular nada
    if empresa is None:
        ctx["total_sub_empresas_activas"] = 0
        ctx["total_activos"] = 0
        ctx["total_pasivos"] = 0
        ctx["balance_total"] = 0
        ctx["movimientos"] = Movimiento.objects.none()
        return render(request, "core/dashboard.html", ctx)
    
    total_subs_activas = empresa.subempresas.filter(esta_activa=True).count()

    qs_movs = Movimiento.objects.filter(empresa=empresa)

    total_activos = qs_movs.filter(
        tipo=Movimiento.TipoMovimiento.ACTIVO
    ).aggregate(total=Sum('monto_total'))['total'] or 0

    total_pasivos = qs_movs.filter(
        tipo=Movimiento.TipoMovimiento.PASIVO
    ).aggregate(total=Sum('monto_total'))['total'] or 0

    capital_inicial = empresa.capital_inicial or 0
    balance_total = capital_inicial + total_activos - total_pasivos

    movimientos = qs_movs.order_by("-fecha_registro", "-id")[:20]

    ctx.update({
        "total_subempresas_activas": total_subs_activas,
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
        "balance_total": balance_total,
        "movimientos": movimientos,
        "total_reportes_aprobados": 0,
        "total_pendientes_revision": 0,
        "aprobaciones_pendientes": [],
    })

    return render(request, "core/dashboard.html", ctx)

'''
    # Ejemplo de cómo filtrar movimientos según contextos
    movimientos = Movimiento.objects.filter(empresa__in=ctx["empresas_disponibles"])
    if ctx["empresa_actual"]:
        movimientos = movimientos.filter(empresa=ctx["empresa_actual"])
    if ctx["subempresa_actual"]:
        movimientos = movimientos.filter(subempresa=ctx["subempresa_actual"])

    ctx["movimientos"] = movimientos[:20]  # por ahora, top 20

    return render(request, "core/dashboard.html", ctx)
'''

@login_required(login_url="core:login")
def captura_view(request):
    ctx = _contexto_usuario(request)

    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]

    # Si no hay empresa o subempresa seleccionada, solo mostramos el mensaje
    if not empresa or not subempresa:
        ctx.update({
            "puede_capturar": False,
            "movimientos": [],
            "total_activos": 0,
            "total_pasivos": 0,
        })
        return render(request, "core/captura.html", ctx)

    # A partir de aquí SÍ hay subempresa seleccionada
    qs = Movimiento.objects.filter(
        empresa=empresa,
        subempresa=subempresa,
    ).order_by("-fecha_registro", "-id")

    total_activos = (
        qs.filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
          .aggregate(total=Sum("monto_total"))["total"] or 0
    )
    total_pasivos = (
        qs.filter(tipo=Movimiento.TipoMovimiento.PASIVO)
          .aggregate(total=Sum("monto_total"))["total"] or 0
    )

    ctx.update({
        "puede_capturar": True,
        "movimientos": qs,
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
    })

    return render(request, "core/captura.html", ctx)


@login_required(login_url="core:login")
def balance_view(request):
    ctx = _contexto_usuario(request)

    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]

    if empresa is None:
        ctx.update({
            "total_activos": 0,
            "total_pasivos": 0,
            "total_capital": 0,
            "balance_detallado": [],
            "ratio_ap_total": None,
        })
        return render(request, "core/balance.html", ctx)

    qs_movs = Movimiento.objects.filter(empresa=empresa)

    if subempresa:
        qs_movs = qs_movs.filter(subempresa=subempresa)
    
    total_activos = (
        qs_movs.filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or 0
    )

    total_pasivos = (
        qs_movs.filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or 0
    )

    if subempresa:
        total_capital = total_activos - total_pasivos
    else:
        capital_inicial = empresa.capital_inicial or 0
        total_capital = capital_inicial + total_activos - total_pasivos



    balance_detallado = []
    subempresas = empresa.subempresas.filter(esta_activa=True)

    for sub in subempresas:
        qs_sub = qs_movs.filter(subempresa=sub)

        act_sub = (
            qs_sub.filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
            .aggregate(total=Sum("monto_total"))["total"] or 0
        )
        pas_sub = (
            qs_sub.filter(tipo=Movimiento.TipoMovimiento.PASIVO)
            .aggregate(total=Sum("monto_total"))["total"] or 0
        )

        cap_sub = act_sub - pas_sub
        ratio_ap = (act_sub / pas_sub) if pas_sub else None

        balance_detallado.append({
            "subempresa": sub,
            "activos": act_sub,
            "pasivos": pas_sub,
            "capital": cap_sub,
            "ratio_ap": ratio_ap,
        })

    ratio_ap_total = (total_activos / total_pasivos) if total_pasivos else None

    ctx.update({
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
        "total_capital": total_capital,
        "balance_detallado": balance_detallado,
        "ratio_ap_total": ratio_ap_total,
    })
    # Después usarás ctx["empresa_actual"] / ctx["subempresa_actual"] para calcular el balance
    return render(request, "core/balance.html", ctx)
