from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse


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
    logout(request)
    return redirect("core:login")


@login_required(login_url="core:login")
def dashboard_view(request):
    return render(request, "core/dashboard.html")


@login_required(login_url="core:login")
def subempresas_view(request):
    return render(request, "core/subempresas.html")


@login_required(login_url="core:login")
def captura_view(request):
    # Más adelante aquí estará el formulario de registro de movimientos
    return render(request, "core/captura.html")


@login_required(login_url="core:login")
def flujo_view(request):
    return render(request, "core/flujo.html")


@login_required(login_url="core:login")
def balance_view(request):
    # En el futuro aquí se calculará el balance real con Movimiento y Pago
    return render(request, "core/balance.html")


# Si quieres conservar movimientos_view separado:
@login_required(login_url="core:login")
def movimientos_view(request):
    # Ejemplo: podrías reutilizar captura.html o crear otra plantilla específica
    return render(request, "core/captura.html")
