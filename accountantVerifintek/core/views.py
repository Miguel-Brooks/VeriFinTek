from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Empresa, Subempresa, UsuarioEmpresa, Movimiento

# ----- HELPERS -----
def _contexto_usuario(request):
    """Helper: empresas, subempresas y selección actual para el usuario."""
    empresas = (
        Empresa.objects.filter(usuarios__usuario=request.user)
        .distinct()
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
    if subempresa_id:
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

    # Validar membresía del usuario en esa empresa
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

    # Ejemplo de cómo filtrar movimientos según contextos
    movimientos = Movimiento.objects.filter(empresa__in=ctx["empresas_disponibles"])
    if ctx["empresa_actual"]:
        movimientos = movimientos.filter(empresa=ctx["empresa_actual"])
    if ctx["subempresa_actual"]:
        movimientos = movimientos.filter(subempresa=ctx["subempresa_actual"])

    ctx["movimientos"] = movimientos[:20]  # por ahora, top 20

    return render(request, "core/dashboard.html", ctx)


@login_required(login_url="core:login")
def captura_view(request):
    ctx = _contexto_usuario(request)

    # Aquí más adelante validarás rol FINANCIERO y captura solo si hay subempresa seleccionada
    return render(request, "core/captura.html", ctx)


@login_required(login_url="core:login")
def balance_view(request):
    ctx = _contexto_usuario(request)

    # Después usarás ctx["empresa_actual"] / ctx["subempresa_actual"] para calcular el balance
    return render(request, "core/balance.html", ctx)
