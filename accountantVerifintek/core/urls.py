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
    path("movimiento/<int:pk>/neutralizar/", views.neutralizar_movimiento_view, name="neutralizar_movimiento"),
    path("movimiento/<int:pk>/eliminar/", views.movimiento_eliminar_view, name="movimiento_eliminar"),
    path(
        "movimiento/<int:movimiento_id>/pago/<int:pk>/editar/",
        views.pago_editar_view,
        name="pago_editar",
    ),

    # CRUD de empresas, sub-empresas y usuarios
    # --- Rutas de Configuración / Admin ---
    path("configuracion/", views.configuracion_view, name="configuracion"),
    
    # CRUD Empresas
    path('configuracion/crear-empresa/', views.crear_empresa_view, name='crear_empresa'),
    path("configuracion/empresa/<int:pk>/editar/", views.editar_empresa_view, name="editar_empresa"),
    
    # CRUD Subempresas
    path("configuracion/empresa/<int:empresa_id>/subempresa/crear/", views.crear_subempresa_view, name="crear_subempresa"),
    path("configuracion/subempresa/<int:pk>/editar/", views.editar_subempresa_view, name="editar_subempresa"),
    
    # Usuarios y Permisos
    path('configuracion/invitar/', views.invitar_usuario_view, name='invitar_usuario'),
    path('configuracion/asignar/', views.asignar_permiso_view, name='asignar_permiso'),
    path("configuracion/permiso/<int:pk>/editar/", views.editar_permiso_view, name="editar_permiso"),
    path('configuracion/eliminar-permiso/<int:pk>/', views.eliminar_permiso_view, name='eliminar_permiso'),

    # En urls.py


]
