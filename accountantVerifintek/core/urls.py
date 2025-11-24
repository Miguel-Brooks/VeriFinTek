from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),        # raíz del sitio
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    path("subempresas/", views.subempresas_view, name="subempresas"),
    path("captura/", views.captura_view, name="captura"),
    path("flujo/", views.flujo_view, name="flujo"),
    path("balance/", views.balance_view, name="balance"),

    # Opcional: alias adicional si quieres una URL distinta para movimientos
    path("movimientos/", views.movimientos_view, name="movimientos"),
]
