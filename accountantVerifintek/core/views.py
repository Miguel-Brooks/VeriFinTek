from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Empresa, Subempresa, UsuarioEmpresa, Movimiento
from django.db.models import Sum, Q
from django.contrib.admin.views.decorators import staff_member_required


def _contexto_usuario(request):
    """Helper: empresas, subempresas y selección actual para el usuario."""
    
    '''
    empresas = (
        Empresa.objects.filter(usuarios__usuario=request.user)
        .distinct()
    )
    '''

    empresa_id = request.session.get("empresa_id")
    subempresa_id = request.session.get("subempresa_id")

    if request.user.is_superuser:
        empresas_qs = Empresa.objects.all().prefetch_related("subempresas")

        empresas = []
        for emp in empresas_qs:
            subs = list(emp.subempresas.filter(esta_activa=True))
            emp.subs_permitidas = subs
            emp.mostrar_todas = True  
            empresas.append(emp)

        empresa_actual = next((e for e in empresas if e.id == empresa_id), None)
        subempresas = empresa_actual.subs_permitidas if empresa_actual else []
        subempresa_actual = (
            next((s for s in subempresas if s.id == subempresa_id), None)
            if subempresas else None
        )

        return {
            "empresas_disponibles": empresas,
            "subempresas_disponibles": subempresas,
            "empresa_actual": empresa_actual,
            "subempresa_actual": subempresa_actual,
        }

    memberships = (
        UsuarioEmpresa.objects
        .filter(usuario=request.user, puede_leer=True)
        .select_related("empresa", "subempresa")
    )

    empresa_map = {}
    for m in memberships:
        data = empresa_map.setdefault(m.empresa.id, {
            "empresa": m.empresa,
            "all_subs": False,  
            "subs_ids": set(),   
        })
        if m.subempresa is None:
            data["all_subs"] = True
        else:
            data["subs_ids"].add(m.subempresa.id)

    empresas = []
    for data in empresa_map.values():
        emp = data["empresa"]

        if data["all_subs"]:
            subs_qs = emp.subempresas.filter(esta_activa=True)
            mostrar_todas = True
        else:
            subs_qs = emp.subempresas.filter(
                esta_activa=True,
                id__in=data["subs_ids"],
            )
            mostrar_todas = len(data["subs_ids"]) > 1

        subs = list(subs_qs)
        emp.subs_permitidas = subs
        emp.mostrar_todas = mostrar_todas
        empresas.append(emp)

    if not empresas:
        return {
            "empresas_disponibles": [],
            "subempresas_disponibles": [],
            "empresa_actual": None,
            "subempresa_actual": None,
        }

    empresa_actual = next((e for e in empresas if e.id == empresa_id), None)
    subempresas = empresa_actual.subs_permitidas if empresa_actual else []
    subempresa_actual = (
        next((s for s in subempresas if s.id == subempresa_id), None)
        if subempresas else None
    )

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

    if tipo == "empresa" and pk.isdigit():
        empresa = get_object_or_404(Empresa, id=pk)
    elif tipo == "subempresa" and pk.isdigit():
        subempresa = get_object_or_404(Subempresa, id=pk)
        empresa = subempresa.empresa
    else:
        messages.error(request, "Selección inválida.")
        return redirect("core:dashboard")

    if not request.user.is_superuser:
        memberships = UsuarioEmpresa.objects.filter(
            usuario=request.user,
            empresa=empresa,
            puede_leer=True,
        )

        if subempresa:
           
            allowed = memberships.filter(
                Q(subempresa__isnull=True) | Q(subempresa=subempresa)
            ).exists()
        else:
            allowed = memberships.filter(subempresa__isnull=True).exists()

        if not allowed:
            messages.error(request, "No tienes acceso a esta empresa o sub-empresa.")
            return redirect("core:dashboard")

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
    if request.method == "POST":
        logout(request)
        request.session.pop("empresa_id", None)
        request.session.pop("subempresa_id", None)
        return redirect("core:login")

    return redirect("core:login")


@login_required(login_url="core:login")
def dashboard_view(request):
    ctx = _contexto_usuario(request)

    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]

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

    if not empresa or not subempresa:
        ctx.update({
            "puede_capturar": False,
            "movimientos": [],
            "total_activos": 0,
            "total_pasivos": 0,
        })
        return render(request, "core/captura.html", ctx)

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
        subempresas = empresa.subempresas.filter(id=subempresa.id, esta_activa=True)
        total_capital = total_activos - total_pasivos
    else:
        subempresas = empresa.subempresas.filter(esta_activa=True)
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


