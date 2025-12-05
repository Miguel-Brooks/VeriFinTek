from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),  # raíz del sitio
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("captura/", views.captura_view, name="captura"),
    path("balance/", views.balance_view, name="balance"),
    path(
        "balance/exportar/",
        views.balance_export_view,
        name="balance_exportar",
    ),
    path("cambiar-contexto/", views.seleccionar_contexto_view, name="cambiar_contexto"),
    path("movimiento/<int:pk>/", views.movimiento_detalle_view, name="movimiento_detalle"),
    path("movimiento/<int:pk>/eliminar/", views.movimiento_eliminar_view, name="movimiento_eliminar"),
    path(
        "movimiento/<int:movimiento_id>/pago/<int:pk>/editar/",
        views.pago_editar_view,
        name="pago_editar",
    ),
]
