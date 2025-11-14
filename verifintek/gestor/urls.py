from django.urls import path
from . import views

urlpatterns = [
    path('', views.panel_general, name='panel_general'),
    path('subempresas/', views.subempresas_view, name='subempresas'),
    path('captura/', views.captura_view, name='captura'),
    path('flujo/', views.flujo_view, name='flujo'),
    path('balance/', views.balance_view, name='balance'),
]

