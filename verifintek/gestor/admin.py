from django.contrib import admin
from .models import SubEmpresa, Cuenta, Poliza, Partida, BalanceHistorico

admin.site.register(SubEmpresa)
admin.site.register(Cuenta)
admin.site.register(Poliza)
admin.site.register(Partida)
admin.site.register(BalanceHistorico)