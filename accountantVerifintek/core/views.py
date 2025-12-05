from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Empresa, Subempresa, UsuarioEmpresa, Movimiento, Pago, ConceptoMovimiento
from django.db.models import Sum, Q, Count
from django.contrib.admin.views.decorators import staff_member_required
from .forms import MovimientoForm, PagoForm
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
import csv
from io import BytesIO



def _generar_pagos_iniciales(mov: Movimiento):
    """
    Crea los registros Pago para un movimiento nuevo, repartiendo el monto_total
    en mov.numero_pagos, con fechas según la frecuencia.
    """
    n = mov.numero_pagos or 1
    if n < 1:
        n = 1

    monto_total = mov.monto_total or Decimal("0")
    if n == 0:
        return

    # Monto base por pago (dos decimales)
    base = (monto_total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    montos = [base for _ in range(n)]

    # Ajustar el último para que la suma sea exactamente monto_total
    suma = sum(montos)
    diferencia = monto_total - suma
    if diferencia:
        montos[-1] = (montos[-1] + diferencia).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Incremento de días según frecuencia
    if mov.frecuencia_pago == Movimiento.FrecuenciaPago.SEMANAL:
        delta_dias = 7
    elif mov.frecuencia_pago == Movimiento.FrecuenciaPago.QUINCENAL:
        delta_dias = 14
    elif mov.frecuencia_pago == Movimiento.FrecuenciaPago.MENSUAL:
        delta_dias = 30
    elif mov.frecuencia_pago == Movimiento.FrecuenciaPago.ANUAL:
        delta_dias = 365
    else:
        # Único: todas las fechas al inicio
        delta_dias = 0

    for i in range(n):
        if delta_dias == 0:
            fecha_venc = mov.fecha_inicio
        else:
            # Primer pago: inicio + delta, luego se acumula
            fecha_venc = mov.fecha_inicio + timedelta(days=delta_dias * (i + 1))

        Pago.objects.create(
            movimiento=mov,
            numero_pago=i + 1,
            fecha_vencimiento=fecha_venc,
            monto=montos[i],
            fecha_pago=None,
            esta_pagado=False,
        )



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
    """
    Panel general con:
    - Filtros globales (rango, estado de pago, concepto)
    - Dashboard operativo (sub-empresa): flujo de caja proyectado + CxC
    - Dashboard estratégico (empresa): rentabilidad por sub-empresa + desglose por conceptos
    """
    ctx = _contexto_usuario(request)
    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]
    hoy = date.today()

    # -----------------------------
    # 1) Filtros globales ("Control Center")
    # -----------------------------
    # Rango: mes_actual / ultimos_30 / personalizado
    rango = request.GET.get("rango", "mes_actual")
    fecha_desde = None
    fecha_hasta = None

    if rango == "ultimos_30":
        fecha_hasta = hoy
        fecha_desde = hoy - timedelta(days=30)
    elif rango == "personalizado":
        desde_str = request.GET.get("desde")
        hasta_str = request.GET.get("hasta")
        try:
            if desde_str:
                fecha_desde = date.fromisoformat(desde_str)
        except ValueError:
            fecha_desde = None
        try:
            if hasta_str:
                fecha_hasta = date.fromisoformat(hasta_str)
        except ValueError:
            fecha_hasta = None
        # Defaults si algo viene mal
        if not fecha_hasta:
            fecha_hasta = hoy
        if not fecha_desde:
            fecha_desde = fecha_hasta - timedelta(days=30)
    else:
        # mes_actual (default)
        rango = "mes_actual"
        fecha_hasta = hoy
        fecha_desde = date(hoy.year, hoy.month, 1)

    # Estado de pago: todos / pagados / pendientes / vencidos
    estado_pago = request.GET.get("estado_pago", "todos")
    if estado_pago not in ("todos", "pagados", "pendientes", "vencidos"):
        estado_pago = "todos"

    # Filtro de concepto (por id)
    concepto_id = request.GET.get("concepto") or ""
    if not concepto_id.isdigit():
        concepto_id = ""

    # Lista de conceptos disponibles para el dropdown (solo los que tienen movimientos en la empresa)
    if empresa:
        conceptos_disponibles = (
            ConceptoMovimiento.objects
            .filter(movimientos__empresa=empresa)
            .distinct()
            .order_by("nombre")
        )
    else:
        conceptos_disponibles = ConceptoMovimiento.objects.none()

    # Si no hay empresa seleccionada, devolvemos contexto "vacío" pero con filtros y dropdown
    if empresa is None:
        ctx.update({
            "total_subempresas_activas": 0,
            "balance_total": Decimal("0"),
            "flujo_caja_pagos": [],
            "cxc_pagos": [],
            "reporte_subempresas": [],
            "desglose_conceptos": [],
            "total_conceptos_monto": Decimal("0"),
            "filtro_rango": rango,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "filtro_estado_pago": estado_pago,
            "filtro_concepto_id": concepto_id,
            "conceptos_disponibles": conceptos_disponibles,
            "hoy": hoy,
        })
        return render(request, "core/dashboard.html", ctx)

    # -----------------------------
    # 2) Métricas históricas básicas (empresa)
    #    (NO dependen de los filtros, para el "Balance total" general)
    # -----------------------------
    qs_movs_total = Movimiento.objects.filter(empresa=empresa)
    total_activos_total = (
        qs_movs_total
        .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    total_pasivos_total = (
        qs_movs_total
        .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    capital_inicial = empresa.capital_inicial or Decimal("0")
    balance_total = capital_inicial + total_activos_total - total_pasivos_total
    total_subs_activas = empresa.subempresas.filter(esta_activa=True).count()

    # -----------------------------
    # 3) Query base para filtros (devengado y flujo)
    # -----------------------------

    # DEVENGADO (Movimiento) filtrado por rango y concepto
    qs_movs_rango = Movimiento.objects.filter(
        empresa=empresa,
        fecha_registro__gte=fecha_desde,
        fecha_registro__lte=fecha_hasta,
    )
    if concepto_id:
        qs_movs_rango = qs_movs_rango.filter(concepto_id=int(concepto_id))

    # FLUJO (Pago) filtrado globalmente por empresa, rango y concepto
    qs_pagos_base = Pago.objects.filter(
        movimiento__empresa=empresa,
        fecha_vencimiento__gte=fecha_desde,
        fecha_vencimiento__lte=fecha_hasta,
    )
    if concepto_id:
        qs_pagos_base = qs_pagos_base.filter(movimiento__concepto_id=int(concepto_id))

    # -----------------------------
    # 4) Nivel Sub-empresa (Operativo)
    # -----------------------------
    flujo_caja_pagos = []
    cxc_pagos = []

    if subempresa:
        # a) Flujo de caja proyectado: pagos de la sub-empresa en el rango
        pagos_sub = qs_pagos_base.filter(movimiento__subempresa=subempresa)

        # Filtro por estado de pago (solo para esta tabla)
        if estado_pago == "pagados":
            pagos_sub = pagos_sub.filter(esta_pagado=True)
        elif estado_pago == "pendientes":
            pagos_sub = pagos_sub.filter(
                esta_pagado=False,
                fecha_vencimiento__gte=hoy,
            )
        elif estado_pago == "vencidos":
            pagos_sub = pagos_sub.filter(
                esta_pagado=False,
                fecha_vencimiento__lt=hoy,
            )

        pagos_sub = pagos_sub.select_related(
            "movimiento",
            "movimiento__concepto",
            "movimiento__subempresa",
        ).order_by("fecha_vencimiento", "numero_pago")

        # Enriquecer con etiquetas de estado para la UI
        flujo_caja_pagos = list(pagos_sub)
        for p in flujo_caja_pagos:
            if p.esta_pagado:
                p.estado_label = "Pagado"
                p.estado_color = "#16A34A"  # verde
            else:
                if p.fecha_vencimiento < hoy:
                    p.estado_label = "Vencido"
                    p.estado_color = "#DC2626"  # rojo
                else:
                    p.estado_label = "Pendiente"
                    p.estado_color = "#6B7280"  # gris

        # b) Cuentas por cobrar (cartera vencida/pendiente) solo de ACTIVOS pendientes
        cxc_qs = qs_pagos_base.filter(
            movimiento__subempresa=subempresa,
            movimiento__tipo=Movimiento.TipoMovimiento.ACTIVO,
            esta_pagado=False,
        ).select_related("movimiento", "movimiento__concepto")

        cxc_pagos = list(cxc_qs)
        for p in cxc_pagos:
            # Días de retraso: negativo = por vencer
            p.dias_retraso = (hoy - p.fecha_vencimiento).days
            # Valor absoluto para mostrar "Por vencer (X días)" sin usar filtro abs en template
            p.dias_retraso_abs = abs(p.dias_retraso)

    # -----------------------------
    # 5) Nivel Empresa (Estratégico)
    # -----------------------------

    # a) Rentabilidad por sub-empresa (ingresos cobrados / egresos pagados / deuda pendiente)
    # Sub-empresas permitidas para el usuario
    subs_permitidas = getattr(empresa, "subs_permitidas", None)
    if subs_permitidas is not None:
        base_sub_qs = Subempresa.objects.filter(
            empresa=empresa,
            id__in=[s.id for s in subs_permitidas],
            esta_activa=True,
        )
    else:
        base_sub_qs = empresa.subempresas.filter(esta_activa=True)

    filtro_ingresos = Q(
        movimientos__pagos__esta_pagado=True,
        movimientos__tipo=Movimiento.TipoMovimiento.ACTIVO,
        movimientos__pagos__fecha_pago__gte=fecha_desde,
        movimientos__pagos__fecha_pago__lte=fecha_hasta,
    )
    filtro_egresos = Q(
        movimientos__pagos__esta_pagado=True,
        movimientos__tipo=Movimiento.TipoMovimiento.PASIVO,
        movimientos__pagos__fecha_pago__gte=fecha_desde,
        movimientos__pagos__fecha_pago__lte=fecha_hasta,
    )
    filtro_deuda = Q(
        movimientos__pagos__esta_pagado=False,
        movimientos__tipo=Movimiento.TipoMovimiento.PASIVO,
        movimientos__pagos__fecha_vencimiento__gte=fecha_desde,
        movimientos__pagos__fecha_vencimiento__lte=fecha_hasta,
    )
    if concepto_id:
        filtro_ingresos &= Q(movimientos__concepto_id=int(concepto_id))
        filtro_egresos &= Q(movimientos__concepto_id=int(concepto_id))
        filtro_deuda &= Q(movimientos__concepto_id=int(concepto_id))

    reporte_qs = base_sub_qs.annotate(
        ingresos_cobrados=Sum("movimientos__pagos__monto", filter=filtro_ingresos),
        egresos_pagados=Sum("movimientos__pagos__monto", filter=filtro_egresos),
        deuda_pendiente=Sum("movimientos__pagos__monto", filter=filtro_deuda),
    )

    reporte_subempresas = []
    for sub in reporte_qs:
        ing = sub.ingresos_cobrados or Decimal("0")
        egr = sub.egresos_pagados or Decimal("0")
        deuda = sub.deuda_pendiente or Decimal("0")
        neto = ing - egr
        if neto > 0:
            salud_label = "Sana"
            salud_color = "#16A34A"
        elif neto < 0:
            salud_label = "En riesgo"
            salud_color = "#DC2626"
        else:
            salud_label = "Neutra"
            salud_color = "#6B7280"
        reporte_subempresas.append({
            "subempresa": sub,
            "ingresos_cobrados": ing,
            "egresos_pagados": egr,
            "flujo_neto_real": neto,
            "deuda_pendiente": deuda,
            "salud_label": salud_label,
            "salud_color": salud_color,
        })

    # b) Desglose por conceptos (devengado, a nivel corporativo)
    conceptos_qs = (
        qs_movs_rango
        .values("concepto__nombre")
        .annotate(
            total_movimientos=Count("id"),
            monto_total=Sum("monto_total"),
        )
        .order_by("-monto_total")
    )

    total_conceptos_monto = Decimal("0")
    for row in conceptos_qs:
        total_conceptos_monto += row["monto_total"] or Decimal("0")

    desglose_conceptos = []
    for row in conceptos_qs:
        monto = row["monto_total"] or Decimal("0")
        if total_conceptos_monto > 0:
            pct = (monto / total_conceptos_monto) * Decimal("100")
        else:
            pct = Decimal("0")
        desglose_conceptos.append({
            "concepto": row["concepto__nombre"],
            "total_movimientos": row["total_movimientos"],
            "monto_total": monto,
            "porcentaje": pct,
        })

    # -----------------------------
    # 6) Actualizar contexto y render
    # -----------------------------
    ctx.update({
        "total_subempresas_activas": total_subs_activas,
        "balance_total": balance_total,
        # Filtros
        "filtro_rango": rango,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "filtro_estado_pago": estado_pago,
        "filtro_concepto_id": concepto_id,
        "conceptos_disponibles": conceptos_disponibles,
        # Nivel sub-empresa
        "flujo_caja_pagos": flujo_caja_pagos,
        "cxc_pagos": cxc_pagos,
        # Nivel empresa
        "reporte_subempresas": reporte_subempresas,
        "desglose_conceptos": desglose_conceptos,
        "total_conceptos_monto": total_conceptos_monto,
        # Utilidades para la plantilla
        "hoy": hoy,
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

def _calcular_estatus_mov(mov: Movimiento, hoy: date):
    """
    Devuelve (label, clase_css) según los pagos del movimiento.
    """
    pagos_qs = mov.pagos.all()

    total_pagado = (
        pagos_qs.filter(esta_pagado=True)
        .aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )
    total_pendiente = (mov.monto_total or Decimal("0")) - total_pagado

    hay_pagos_pendientes = pagos_qs.filter(esta_pagado=False).exists()
    hay_pagos_atrasados = pagos_qs.filter(
        esta_pagado=False,
        fecha_vencimiento__lt=hoy,
    ).exists()

    if total_pendiente <= 0 or not hay_pagos_pendientes:
        return "Saldado", "estatus-label-saldado"
    elif hay_pagos_atrasados:
        return "Atrasado", "estatus-label-atrasado"
    else:
        return "Con saldo pendiente", "estatus-label-pendiente"


@login_required(login_url="core:login")
def captura_view(request):
    ctx = _contexto_usuario(request)
    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]

    if not empresa or not subempresa:
        ctx.update({
            "puede_capturar": False,
            "form": None,
            "movimientos": [],
            "total_activos": 0,
            "total_pasivos": 0,
            "balance_contexto": 0,
            "total_movimientos": 0,
            "total_movimientos_futuro": 0,
            "total_proximo_pagos": 0,
        })
        return render(request, "core/captura.html", ctx)

    # Query base de movimientos para la sub-empresa actual
    qs = Movimiento.objects.filter(
        empresa=empresa,
        subempresa=subempresa,
    ).prefetch_related("pagos")

    hoy = date.today()

    # ----------------------------
    # 1) Filtro de fechas: MOVIMIENTOS RECIENTES
    # ----------------------------
    fecha_desde_str = request.GET.get("mov_desde")
    fecha_hasta_str = request.GET.get("mov_hasta")

    # Selector de qué fecha usar en el filtro (registro / inicio)
    mov_fecha_campo = request.GET.get("mov_fecha_campo", "registro")
    if mov_fecha_campo not in ("registro", "inicio"):
        mov_fecha_campo = "registro"

    fecha_desde = None
    fecha_hasta = None

    # Si el usuario pulsa "Limpiar filtro" en movimientos recientes, ignoramos fechas
    reset_mov_fechas = request.GET.get("reset_mov_fechas")
    if not reset_mov_fechas:
        if fecha_desde_str:
            try:
                # Soporta valores enviados por <input type="date"> (YYYY-MM-DD)
                fecha_desde = date.fromisoformat(fecha_desde_str)
            except ValueError:
                fecha_desde = None

        if fecha_hasta_str:
            try:
                fecha_hasta = date.fromisoformat(fecha_hasta_str)
            except ValueError:
                fecha_hasta = None

        # Aplicar filtros según el campo elegido
        if fecha_desde:
            if mov_fecha_campo == "inicio":
                qs = qs.filter(fecha_inicio__gte=fecha_desde)
            else:
                qs = qs.filter(fecha_registro__gte=fecha_desde)

        if fecha_hasta:
            if mov_fecha_campo == "inicio":
                qs = qs.filter(fecha_inicio__lte=fecha_hasta)
            else:
                qs = qs.filter(fecha_registro__lte=fecha_hasta)

    # Orden de la tabla de movimientos recientes
    orden_mov = request.GET.get("orden_mov", "-fecha_registro")
    campos_mov_permitidos = {
        "fecha_registro", "-fecha_registro",
        "tipo", "-tipo",
        "concepto__nombre", "-concepto__nombre",
        "monto_total", "-monto_total",
        "subempresa__nombre", "-subempresa__nombre",
        "estado", "-estado",
        "fecha_inicio", "-fecha_inicio",
        "frecuencia_pago", "-frecuencia_pago",
        "numero_pagos", "-numero_pagos",
    }
    if orden_mov not in campos_mov_permitidos:
        orden_mov = "-fecha_registro"

    qs = qs.order_by(orden_mov, "-id")

    # ----------------------------
    # 2) Alta de movimiento (modal)
    # ----------------------------
    abrir_modal_mov = False
    if request.method == "POST":
        form = MovimientoForm(request.POST)
        abrir_modal_mov = True

        if form.is_valid():
            mov = form.save(commit=False)

            # Concepto desde texto
            nombre_concepto = form.cleaned_data["concepto_nombre"].strip()
            concepto, _ = ConceptoMovimiento.objects.get_or_create(
                nombre=nombre_concepto
            )

            mov.concepto = concepto
            mov.empresa = empresa
            mov.subempresa = subempresa
            mov.usuario_captura = request.user
            mov.fecha_registro = date.today()
            mov.save()

            _generar_pagos_iniciales(mov)

            messages.success(request, "Movimiento registrado correctamente.")
            return redirect("core:captura")
    else:
        form = MovimientoForm()

    if request.GET.get("open_modal") == "1":
        abrir_modal_mov = True

    # ----------------------------
    # 3) Totales de activos / pasivos del contexto (sub-empresa)
    # ----------------------------
    total_activos = (
        qs.filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or 0
    )
    total_pasivos = (
        qs.filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or 0
    )

    # Balance del contexto de captura: A - P
    balance_contexto = total_activos - total_pasivos

    # ----------------------------
    # 4) Sección "Movimientos que se deberán pagar a futuro"
    # ----------------------------
    futuro_desde_str = request.GET.get("futuro_desde")
    futuro_hasta_str = request.GET.get("futuro_hasta")

    futuro_desde = None
    futuro_hasta = None

    # Si el usuario pulsa "Limpiar filtro" en futuros, regresamos al rango por defecto
    reset_futuro_fechas = request.GET.get("reset_futuro_fechas")
    if not reset_futuro_fechas:
        if futuro_desde_str:
            try:
                futuro_desde = date.fromisoformat(futuro_desde_str)
            except ValueError:
                futuro_desde = None

        if futuro_hasta_str:
            try:
                futuro_hasta = date.fromisoformat(futuro_hasta_str)
            except ValueError:
                futuro_hasta = None

    # Valores por defecto del rango de futuros (hoy -> hoy + 365 días)
    if not futuro_desde:
        futuro_desde = hoy
    if not futuro_hasta:
        futuro_hasta = hoy + timedelta(days=365)

    from django.db.models import Min

    movimientos_futuro = (
        Movimiento.objects
        .filter(
            empresa=empresa,
            subempresa=subempresa,
            pagos__esta_pagado=False,
            pagos__fecha_vencimiento__gte=futuro_desde,
            pagos__fecha_vencimiento__lte=futuro_hasta,
        )
        .annotate(
            # Próxima fecha de pago dentro del rango
            proximo_vencimiento=Min(
                "pagos__fecha_vencimiento",
                filter=Q(
                    pagos__esta_pagado=False,
                    pagos__fecha_vencimiento__gte=futuro_desde,
                ),
            ),
        )
        .order_by("proximo_vencimiento", "id")
        .prefetch_related("pagos")
    )

    # ----------------------------
    # 5) Estatus dinámico y cálculos por movimiento
    # ----------------------------

    # a) Movimientos recientes
    for mov in qs:
        label, css = _calcular_estatus_mov(mov, hoy)
        mov.estatus_label = label
        mov.estatus_css = css

    # b) Movimientos a futuro: chips de fechas y monto solo del PRÓXIMO pago
    total_proximo_pagos = Decimal("0")

    for mov in movimientos_futuro:
        label, css = _calcular_estatus_mov(mov, hoy)
        mov.estatus_label = label
        mov.estatus_css = css

        # Pagos futuros (no pagados, dentro del rango) ordenados por fecha
        pagos_futuros = [
            p for p in mov.pagos.all()
            if (
                not p.esta_pagado
                and p.fecha_vencimiento
                and futuro_desde <= p.fecha_vencimiento <= futuro_hasta
            )
        ]
        pagos_futuros.sort(key=lambda p: p.fecha_vencimiento)

        # Máximo 10 chips: 9 fechas + 1 "ver más"
        mov.fechas_pago_visibles = pagos_futuros[:9]
        mov.hay_mas_fechas_pago = len(pagos_futuros) > 9
        mov.fechas_pago_ocultas = pagos_futuros[9:]

        # Monto pendiente mostrado en la tabla:
        # SOLO el monto del próximo pago dentro del rango
        if pagos_futuros:
            mov.monto_proximo_pago = pagos_futuros[0].monto or Decimal("0")
        else:
            mov.monto_proximo_pago = Decimal("0")

        total_proximo_pagos += mov.monto_proximo_pago

    # ----------------------------
    # 6) Métricas para el resumen rápido
    # ----------------------------
    total_movimientos = qs.count()
    total_movimientos_futuro = movimientos_futuro.count()

    ctx.update({
        "puede_capturar": True,
        "form": form,
        "movimientos": qs,
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
        "balance_contexto": balance_contexto,
        "orden_mov": orden_mov,
        "abrir_modal_mov": abrir_modal_mov,
        "movimientos_futuro": movimientos_futuro,
        "futuro_desde": futuro_desde,
        "futuro_hasta": futuro_hasta,
        "hoy": hoy,
        "mov_desde": fecha_desde,
        "mov_hasta": fecha_hasta,
        "mov_fecha_campo": mov_fecha_campo,
        # Resumen rápido
        "total_movimientos": total_movimientos,
        "total_movimientos_futuro": total_movimientos_futuro,
        "total_proximo_pagos": total_proximo_pagos,
    })

    return render(request, "core/captura.html", ctx)

def _recalcular_pagos_pendientes(mov: Movimiento):
    """
    Reparte el restante del movimiento entre los pagos aún no pagados.
    """
    pagos = mov.pagos.all().order_by("numero_pago")

    total_pagado = (
        pagos.filter(esta_pagado=True).aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )
    restante = (mov.monto_total or Decimal("0")) - total_pagado

    pendientes = list(pagos.filter(esta_pagado=False))
    n_pend = len(pendientes)
    if n_pend <= 0 or restante <= 0:
        return

    base = (restante / n_pend).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    montos = [base for _ in range(n_pend)]
    suma = sum(montos)
    diff = restante - suma
    if diff:
        montos[-1] = (montos[-1] + diff).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    for pago, monto in zip(pendientes, montos):
        pago.monto = monto
        pago.save(update_fields=["monto"])

@login_required(login_url="core:login")
def pago_editar_view(request, movimiento_id: int, pk: int):
    mov = get_object_or_404(Movimiento, pk=movimiento_id)
    pago = get_object_or_404(Pago, pk=pk, movimiento=mov)

    # Permisos de edición (mismas reglas que en movimiento_detalle_view)
    if request.user.is_superuser:
        allowed = True
    else:
        memberships = UsuarioEmpresa.objects.filter(
            usuario=request.user,
            empresa=mov.empresa,
            puede_escribir=True,
        )

        if mov.subempresa:
            memberships = memberships.filter(
                Q(subempresa__isnull=True) | Q(subempresa=mov.subempresa)
            )
        else:
            memberships = memberships.filter(subempresa__isnull=True)

        allowed = memberships.filter(
            rol__in=[UsuarioEmpresa.Rol.ADMIN, UsuarioEmpresa.Rol.FINANCIERO]
        ).exists()

    if not allowed:
        messages.error(
            request,
            "No tienes permiso para editar pagos de este movimiento.",
        )
        return redirect("core:movimiento_detalle", pk=mov.pk)

    if request.method == "POST":
        form = PagoForm(request.POST, instance=pago)
        if form.is_valid():
            pago = form.save(commit=False)

            # Reglas: pagado si tiene monto > 0 y fecha de pago
            if pago.monto and pago.fecha_pago:
                pago.esta_pagado = True
            else:
                pago.esta_pagado = False

            pago.save()

            # Recalcular sugerencias para los pagos pendientes
            _recalcular_pagos_pendientes(mov)

            messages.success(
                request,
                f"Pago {pago.numero_pago} actualizado correctamente.",
            )
            return redirect("core:movimiento_detalle", pk=mov.pk)
    else:
        # Sugerir fecha de hoy si todavía no tiene fecha_pago
        if not pago.fecha_pago:
            form = PagoForm(instance=pago, initial={"fecha_pago": date.today()})
        else:
            form = PagoForm(instance=pago)

    # Totales del movimiento (igual que antes)
    total_pagado = (
        mov.pagos.filter(esta_pagado=True)
        .aggregate(total=Sum("monto"))["total"] or 0
    )
    total_pendiente = mov.monto_total - total_pagado

    # Monto actual de ESTE pago
    pago_monto_actual = pago.monto or Decimal("0")

    # Base para el cálculo en el modal:
    # - Si el pago está pagado, el pendiente "hipotético" si lo pusieras en 0
    #   es: pendiente_global + monto_original_de_este_pago
    # - Si el pago está pendiente, el pendiente ya incluye este pago,
    #   así que usamos total_pendiente tal cual.
    if pago.esta_pagado:
        base_pendiente = total_pendiente + pago_monto_actual
    else:
        base_pendiente = total_pendiente

    # Etiquetas según tipo y si es diferido (esto lo dejas igual)
    es_activo = mov.tipo == Movimiento.TipoMovimiento.ACTIVO
    es_pasivo = mov.tipo == Movimiento.TipoMovimiento.PASIVO
    es_diferido = mov.numero_pagos > 1

    if es_activo and es_diferido:
        label_pagado = "Cantidad recibida"
        label_pendiente = "Cantidad por recibir"
    elif es_pasivo and es_diferido:
        label_pagado = "Cantidad pagada"
        label_pendiente = "Cantidad por pagar"
    else:
        label_pagado = "Cantidad pagada"
        label_pendiente = "Cantidad pendiente"

    # Lógica de color (sin cambios)
    if es_activo:
        clase_total_pendiente = "mov-pendiente-azul"
    else:
        if total_pendiente > 0:
            clase_total_pendiente = "mov-pendiente-alerta"
        elif total_pendiente == 0:
            clase_total_pendiente = "mov-pendiente-verde"
        else:
            clase_total_pendiente = "mov-pendiente-azul"

    ctx = {
        "movimiento": mov,
        "pago": pago,
        "form": form,
        "total_pagado": total_pagado,
        "total_pendiente": total_pendiente,  # sigue disponible si lo usas en otro lado
        "base_pendiente": base_pendiente,    # base real para el modal
        "label_pendiente": label_pendiente,
        "clase_total_pendiente": clase_total_pendiente,
        "es_activo": es_activo,
    }

    return render(request, "core/pago_editar_modal.html", ctx)


@login_required(login_url="core:login")
def balance_view(request):
    ctx = _contexto_usuario(request)
    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]

    hoy = date.today()

    # Selector simple para resaltar pestaña en la UI (no oculta secciones)
    vista_activa = request.GET.get("vista", "consolidado")

    # Si no hay empresa seleccionada, devolvemos contexto vacío seguro
    if empresa is None:
        ctx.update({
            # Consolidado
            "saldo_neto_consolidado": Decimal("0"),
            "ingresos_ytd": Decimal("0"),
            "egresos_ytd": Decimal("0"),
            "flujo_neto_ytd": Decimal("0"),
            "total_activos": Decimal("0"),
            "total_pasivos": Decimal("0"),
            "total_capital": Decimal("0"),
            "balance_detallado": [],
            "ratio_ap_total": None,
            "resumen_tipo_estado": {},
            "cuentas_cobrar_vencidas": Decimal("0"),
            "cuentas_cobrar_vigentes": Decimal("0"),
            "deuda_vencida": Decimal("0"),
            "deuda_vigente": Decimal("0"),
            "pagos_vencidos_consolidados": 0,
            "monto_pagos_vencidos_consolidados": Decimal("0"),
            "flujo_12m": [],

            # Detalle operativo sub-empresa
            "tiene_subempresa_detalle": False,
            "detalle_desde": None,
            "detalle_hasta": None,
            "ingresos_periodo": Decimal("0"),
            "egresos_periodo": Decimal("0"),
            "flujo_neto_periodo": Decimal("0"),
            "conceptos_detalle": [],
            "monto_cxc_pendientes_sub": Decimal("0"),
            "monto_ctp_pendientes_sub": Decimal("0"),
            "cxc_pendientes_lista": [],
            "ctp_pendientes_lista": [],
            "pagos_vencidos_sub": [],
            "proyeccion_mensual": [],
            "movimientos_detalle": [],
            "vista_activa": vista_activa,
        })
        return render(request, "core/balance.html", ctx)

    # -------------------------------------------------------------
    # 1) NIVEL EMPRESA (CONSOLIDADO)
    # -------------------------------------------------------------
    qs_movs_empresa = (
        Movimiento.objects
        .filter(empresa=empresa)
        .select_related("subempresa", "concepto", "usuario_captura")
    )

    # Totales globales acumulados (todos los años)
    total_activos = (
        qs_movs_empresa
        .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    total_pasivos = (
        qs_movs_empresa
        .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    capital_inicial = empresa.capital_inicial or Decimal("0")
    total_capital = capital_inicial + total_activos - total_pasivos
    saldo_neto_consolidado = total_capital  # interpretación: patrimonio actual

    # Year-to-date (YTD) para métricas rápidas
    inicio_ytd = date(hoy.year, 1, 1)
    qs_ytd = qs_movs_empresa.filter(
        fecha_registro__gte=inicio_ytd,
        fecha_registro__lte=hoy,
    )
    ingresos_ytd = (
        qs_ytd
        .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    egresos_ytd = (
        qs_ytd
        .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    flujo_neto_ytd = ingresos_ytd - egresos_ytd

    # Balance detallado por sub-empresa
    # Usa las subempresas permitidas en el contexto si existen,
    # o todas las activas de la empresa en caso contrario.
    subs_permitidas = getattr(empresa, "subs_permitidas", None)
    if subs_permitidas is not None:
        subempresas = subs_permitidas
    else:
        subempresas = empresa.subempresas.filter(esta_activa=True)

    balance_detallado = []
    for sub in subempresas:
        qs_sub = qs_movs_empresa.filter(subempresa=sub)
        act_sub = (
            qs_sub
            .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        pas_sub = (
            qs_sub
            .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
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

    # Resumen por tipo y estado (Pendiente / Aprobado / Cancelado)
    resumen_tipo_estado = {}
    for tipo_value, tipo_label in Movimiento.TipoMovimiento.choices:
        movs_tipo = qs_movs_empresa.filter(tipo=tipo_value)
        resumen_tipo_estado[tipo_label] = {}
        total_tipo = Decimal("0")

        for estado_value, estado_label in Movimiento.Estado.choices:
            monto_estado = (
                movs_tipo
                .filter(estado=estado_value)
                .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
            )
            resumen_tipo_estado[tipo_label][estado_label] = monto_estado
            total_tipo += monto_estado

        resumen_tipo_estado[tipo_label]["Total"] = total_tipo

    # KPIs de vencimientos consolidados (todas las sub-empresas)
    pagos_qs = Pago.objects.filter(movimiento__in=qs_movs_empresa)

    cuentas_cobrar_vencidas = (
        pagos_qs.filter(
            movimiento__tipo=Movimiento.TipoMovimiento.ACTIVO,
            esta_pagado=False,
            fecha_vencimiento__lt=hoy,
        )
        .aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )
    cuentas_cobrar_vigentes = (
        pagos_qs.filter(
            movimiento__tipo=Movimiento.TipoMovimiento.ACTIVO,
            esta_pagado=False,
            fecha_vencimiento__gte=hoy,
        )
        .aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )
    deuda_vencida = (
        pagos_qs.filter(
            movimiento__tipo=Movimiento.TipoMovimiento.PASIVO,
            esta_pagado=False,
            fecha_vencimiento__lt=hoy,
        )
        .aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )
    deuda_vigente = (
        pagos_qs.filter(
            movimiento__tipo=Movimiento.TipoMovimiento.PASIVO,
            esta_pagado=False,
            fecha_vencimiento__gte=hoy,
        )
        .aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )

    pagos_vencidos_consolidados_qs = pagos_qs.filter(
        esta_pagado=False,
        fecha_vencimiento__lt=hoy,
    )
    pagos_vencidos_consolidados = pagos_vencidos_consolidados_qs.count()
    monto_pagos_vencidos_consolidados = (
        pagos_vencidos_consolidados_qs
        .aggregate(total=Sum("monto"))["total"] or Decimal("0")
    )

    # Tendencia: flujo neto últimos ~12 meses (agrupado por año-mes en Python)
    hace_12m = hoy - timedelta(days=365)
    movs_12m = qs_movs_empresa.filter(fecha_registro__gte=hace_12m)

    flujo_12m_dict = {}
    for mov in movs_12m:
        clave = (mov.fecha_registro.year, mov.fecha_registro.month)
        if clave not in flujo_12m_dict:
            flujo_12m_dict[clave] = {
                "anio": mov.fecha_registro.year,
                "mes": mov.fecha_registro.month,
                "ingresos": Decimal("0"),
                "egresos": Decimal("0"),
            }
        entry = flujo_12m_dict[clave]
        if mov.tipo == Movimiento.TipoMovimiento.ACTIVO:
            entry["ingresos"] += mov.monto_total or Decimal("0")
        else:
            entry["egresos"] += mov.monto_total or Decimal("0")

    flujo_12m = []
    for (anio, mes), data in sorted(flujo_12m_dict.items(), key=lambda x: (x[0][0], x[0][1])):
        ingresos = data["ingresos"]
        egresos = data["egresos"]
        flujo_12m.append({
            "anio": anio,
            "mes": mes,
            "ingresos": ingresos,
            "egresos": egresos,
            "neto": ingresos - egresos,
        })

    # -------------------------------------------------------------
    # 2) NIVEL SUB-EMPRESA (DETALLE OPERATIVO)
    # -------------------------------------------------------------
    tiene_subempresa_detalle = subempresa is not None

    # Valores por defecto del rango operativo: mes actual
    if tiene_subempresa_detalle:
        op_desde_str = request.GET.get("op_desde")
        op_hasta_str = request.GET.get("op_hasta")

        detalle_desde = None
        detalle_hasta = None

        if op_desde_str:
            try:
                detalle_desde = date.fromisoformat(op_desde_str)
            except ValueError:
                detalle_desde = None
        if op_hasta_str:
            try:
                detalle_hasta = date.fromisoformat(op_hasta_str)
            except ValueError:
                detalle_hasta = None

        if not detalle_hasta:
            detalle_hasta = hoy
        if not detalle_desde:
            detalle_desde = date(hoy.year, hoy.month, 1)

        # Query base del detalle: solo esa sub-empresa y rango de fechas
        # IMPORTANTE: se filtra por fecha_inicio (periodo operativo)
        qs_movs_detalle = (
            qs_movs_empresa
            .filter(
                subempresa=subempresa,
                fecha_inicio__gte=detalle_desde,
                fecha_inicio__lte=detalle_hasta,
            )
            .prefetch_related("pagos")
        )

        ingresos_periodo = (
            qs_movs_detalle
            .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        egresos_periodo = (
            qs_movs_detalle
            .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        flujo_neto_periodo = ingresos_periodo - egresos_periodo

        # Desglose por concepto (ingresos/egresos y neto)
        conceptos_qs = (
            qs_movs_detalle
            .values("concepto__nombre")
            .annotate(
                total_activos=Sum(
                    "monto_total",
                    filter=Q(tipo=Movimiento.TipoMovimiento.ACTIVO),
                ),
                total_pasivos=Sum(
                    "monto_total",
                    filter=Q(tipo=Movimiento.TipoMovimiento.PASIVO),
                ),
            )
        )
        conceptos_detalle = []
        for row in conceptos_qs:
            act = row["total_activos"] or Decimal("0")
            pas = row["total_pasivos"] or Decimal("0")
            conceptos_detalle.append({
                "concepto": row["concepto__nombre"],
                "activos": act,
                "pasivos": pas,
                "neto": act - pas,
            })
        # Ordenar por impacto neto (mayor absoluto primero)
        conceptos_detalle.sort(key=lambda r: abs(r["neto"]), reverse=True)

        # Pagos asociados a la sub-empresa (para CxC, CxP y proyección)
        # Nota: estas tarjetas muestran TODO lo pendiente de la sub-empresa,
        # no solo el rango, para no ocultar obligaciones importantes.
        pagos_sub = Pago.objects.filter(movimiento__empresa=empresa, movimiento__subempresa=subempresa)

        pagos_pendientes = pagos_sub.filter(esta_pagado=False)

        cxc_pendientes_qs = pagos_pendientes.filter(
            movimiento__tipo=Movimiento.TipoMovimiento.ACTIVO
        )
        ctp_pendientes_qs = pagos_pendientes.filter(
            movimiento__tipo=Movimiento.TipoMovimiento.PASIVO
        )

        monto_cxc_pendientes_sub = (
            cxc_pendientes_qs.aggregate(total=Sum("monto"))["total"] or Decimal("0")
        )
        monto_ctp_pendientes_sub = (
            ctp_pendientes_qs.aggregate(total=Sum("monto"))["total"] or Decimal("0")
        )

        # Listas para acción directa (limitadas para no explotar la tabla)
        cxc_pendientes_lista = (
            cxc_pendientes_qs
            .select_related("movimiento", "movimiento__subempresa")
            .order_by("fecha_vencimiento", "movimiento__id")[:100]
        )
        ctp_pendientes_lista = (
            ctp_pendientes_qs
            .select_related("movimiento", "movimiento__subempresa")
            .order_by("fecha_vencimiento", "movimiento__id")[:100]
        )

        pagos_vencidos_sub = (
            pagos_pendientes
            .filter(fecha_vencimiento__lt=hoy)
            .select_related("movimiento", "movimiento__subempresa")
            .order_by("fecha_vencimiento", "movimiento__id")[:100]
        )

        # Proyección mensual de flujo (próximos ~6 meses)
        horizonte = hoy + timedelta(days=180)
        pagos_futuros = pagos_pendientes.filter(
            fecha_vencimiento__gte=hoy,
            fecha_vencimiento__lte=horizonte,
        ).select_related("movimiento")

        proy_dict = {}
        for p in pagos_futuros:
            clave = (p.fecha_vencimiento.year, p.fecha_vencimiento.month)
            if clave not in proy_dict:
                proy_dict[clave] = {
                    "anio": p.fecha_vencimiento.year,
                    "mes": p.fecha_vencimiento.month,
                    "ingresos": Decimal("0"),
                    "egresos": Decimal("0"),
                }
            entry = proy_dict[clave]
            if p.movimiento.tipo == Movimiento.TipoMovimiento.ACTIVO:
                entry["ingresos"] += p.monto or Decimal("0")
            else:
                entry["egresos"] += p.monto or Decimal("0")

        proyeccion_mensual = []
        for (anio, mes), data in sorted(proy_dict.items(), key=lambda x: (x[0][0], x[0][1])):
            ingresos = data["ingresos"]
            egresos = data["egresos"]
            proyeccion_mensual.append({
                "anio": anio,
                "mes": mes,
                "ingresos": ingresos,
                "egresos": egresos,
                "neto": ingresos - egresos,
            })

        # Movimientos detallados de la sub-empresa (para tabla de la parte baja)
        qs_movs_detalle = (
            qs_movs_detalle
            .annotate(
                total_pagado=Sum(
                    "pagos__monto",
                    filter=Q(pagos__esta_pagado=True),
                )
            )
            .order_by("-fecha_inicio", "-id")
        )

        for mov in qs_movs_detalle:
            label, css = _calcular_estatus_mov(mov, hoy)
            mov.estatus_label = label
            mov.estatus_css = css
            pagado = mov.total_pagado or Decimal("0")
            mov.total_pagado = pagado
            mov.total_pendiente = (mov.monto_total or Decimal("0")) - pagado

    else:
        # Sin sub-empresa seleccionada: se muestra mensaje en la UI
        detalle_desde = None
        detalle_hasta = None
        ingresos_periodo = Decimal("0")
        egresos_periodo = Decimal("0")
        flujo_neto_periodo = Decimal("0")
        conceptos_detalle = []
        monto_cxc_pendientes_sub = Decimal("0")
        monto_ctp_pendientes_sub = Decimal("0")
        cxc_pendientes_lista = []
        ctp_pendientes_lista = []
        pagos_vencidos_sub = []
        proyeccion_mensual = []
        qs_movs_detalle = []

    # -------------------------------------------------------------
    # 3) ACTUALIZAR CONTEXTO Y RENDER
    # -------------------------------------------------------------
    ctx.update({
        # Vista / pestaña activa
        "vista_activa": vista_activa,

        # Nivel empresa (consolidado)
        "saldo_neto_consolidado": saldo_neto_consolidado,
        "ingresos_ytd": ingresos_ytd,
        "egresos_ytd": egresos_ytd,
        "flujo_neto_ytd": flujo_neto_ytd,
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
        "total_capital": total_capital,
        "balance_detallado": balance_detallado,
        "ratio_ap_total": ratio_ap_total,
        "resumen_tipo_estado": resumen_tipo_estado,
        "cuentas_cobrar_vencidas": cuentas_cobrar_vencidas,
        "cuentas_cobrar_vigentes": cuentas_cobrar_vigentes,
        "deuda_vencida": deuda_vencida,
        "deuda_vigente": deuda_vigente,
        "pagos_vencidos_consolidados": pagos_vencidos_consolidados,
        "monto_pagos_vencidos_consolidados": monto_pagos_vencidos_consolidados,
        "flujo_12m": flujo_12m,

        # Nivel sub-empresa (detalle operativo)
        "tiene_subempresa_detalle": tiene_subempresa_detalle,
        "detalle_desde": detalle_desde,
        "detalle_hasta": detalle_hasta,
        "ingresos_periodo": ingresos_periodo,
        "egresos_periodo": egresos_periodo,
        "flujo_neto_periodo": flujo_neto_periodo,
        "conceptos_detalle": conceptos_detalle,
        "monto_cxc_pendientes_sub": monto_cxc_pendientes_sub,
        "monto_ctp_pendientes_sub": monto_ctp_pendientes_sub,
        "cxc_pendientes_lista": cxc_pendientes_lista,
        "ctp_pendientes_lista": ctp_pendientes_lista,
        "pagos_vencidos_sub": pagos_vencidos_sub,
        "proyeccion_mensual": proyeccion_mensual,
        "movimientos_detalle": qs_movs_detalle,
    })

    return render(request, "core/balance.html", ctx)

@login_required(login_url="core:login")
def balance_export_view(request):
    """
    Exporta el mismo reporte financiero de balance_view
    en formato CSV, PDF o texto plano.
    """
    ctx = _contexto_usuario(request)
    empresa = ctx["empresa_actual"]
    subempresa = ctx["subempresa_actual"]
    hoy = date.today()

    if empresa is None:
        messages.error(request, "Selecciona una empresa antes de exportar el reporte.")
        return redirect("core:balance")

    # Formato solicitado
    formato = request.GET.get("formato", "csv").lower()
    if formato not in ("csv", "txt", "pdf"):
        formato = "csv"

    # --------------------------
    # 1) Datos a nivel empresa
    # --------------------------
    qs_movs_empresa = Movimiento.objects.filter(empresa=empresa)

    total_activos = (
        qs_movs_empresa
        .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    total_pasivos = (
        qs_movs_empresa
        .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    capital_inicial = empresa.capital_inicial or Decimal("0")
    total_capital = capital_inicial + total_activos - total_pasivos
    saldo_neto_consolidado = total_capital

    inicio_ytd = date(hoy.year, 1, 1)
    qs_ytd = qs_movs_empresa.filter(
        fecha_registro__gte=inicio_ytd,
        fecha_registro__lte=hoy,
    )
    ingresos_ytd = (
        qs_ytd
        .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    egresos_ytd = (
        qs_ytd
        .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
    )
    flujo_neto_ytd = ingresos_ytd - egresos_ytd

    # Rendimiento por sub-empresa (mismas subempresas que se muestran en balance.html)
    subs_permitidas = getattr(empresa, "subs_permitidas", None)
    if subs_permitidas is not None:
        subempresas = subs_permitidas
    else:
        subempresas = empresa.subempresas.filter(esta_activa=True)

    filas_subempresas = []
    for sub in subempresas:
        qs_sub = qs_movs_empresa.filter(subempresa=sub)
        act_sub = (
            qs_sub
            .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        pas_sub = (
            qs_sub
            .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        cap_sub = act_sub - pas_sub
        filas_subempresas.append((sub.nombre, act_sub, pas_sub, cap_sub))

    # --------------------------
    # 2) Detalle de sub-empresa (si hay)
    # --------------------------
    tiene_sub = subempresa is not None
    detalle_desde = None
    detalle_hasta = None
    ingresos_periodo = Decimal("0")
    egresos_periodo = Decimal("0")
    flujo_neto_periodo = Decimal("0")
    conceptos_detalle = []

    if tiene_sub:
        # Reutilizamos los mismos parámetros que usa balance_view
        op_desde_str = request.GET.get("op_desde")
        op_hasta_str = request.GET.get("op_hasta")

        if op_desde_str:
            try:
                detalle_desde = date.fromisoformat(op_desde_str)
            except ValueError:
                detalle_desde = None
        if op_hasta_str:
            try:
                detalle_hasta = date.fromisoformat(op_hasta_str)
            except ValueError:
                detalle_hasta = None

        if not detalle_hasta:
            detalle_hasta = hoy
        if not detalle_desde:
            detalle_desde = date(hoy.year, hoy.month, 1)

        qs_det = (
            qs_movs_empresa
            .filter(
                subempresa=subempresa,
                fecha_inicio__gte=detalle_desde,
                fecha_inicio__lte=detalle_hasta,
            )
        )

        ingresos_periodo = (
            qs_det
            .filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        egresos_periodo = (
            qs_det
            .filter(tipo=Movimiento.TipoMovimiento.PASIVO)
            .aggregate(total=Sum("monto_total"))["total"] or Decimal("0")
        )
        flujo_neto_periodo = ingresos_periodo - egresos_periodo

        conceptos_qs = (
            qs_det
            .values("concepto__nombre")
            .annotate(
                total_activos=Sum(
                    "monto_total",
                    filter=Q(tipo=Movimiento.TipoMovimiento.ACTIVO),
                ),
                total_pasivos=Sum(
                    "monto_total",
                    filter=Q(tipo=Movimiento.TipoMovimiento.PASIVO),
                ),
            )
        )
        for row in conceptos_qs:
            act = row["total_activos"] or Decimal("0")
            pas = row["total_pasivos"] or Decimal("0")
            conceptos_detalle.append(
                (row["concepto__nombre"], act, pas, act - pas)
            )
        # Orden por mayor impacto neto
        conceptos_detalle.sort(key=lambda r: abs(r[3]), reverse=True)

    # --------------------------
    # 3) Armar respuesta según formato
    # --------------------------

    # Helper para nombres de archivo
    base_nombre = f"reporte_financiero_{empresa.nombre.replace(' ', '_')}_{hoy.isoformat()}"

    if formato == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{base_nombre}.csv"'
        writer = csv.writer(response)

        # Resumen consolidado
        writer.writerow(["RESUMEN CONSOLIDADO"])
        writer.writerow(["Empresa", empresa.nombre])
        writer.writerow(["Fecha de corte", hoy.isoformat()])
        writer.writerow(["Saldo neto consolidado (hoy)", str(saldo_neto_consolidado)])
        writer.writerow(["Total ingresos YTD", str(ingresos_ytd)])
        writer.writerow(["Total egresos YTD", str(egresos_ytd)])
        writer.writerow(["Flujo neto YTD", str(flujo_neto_ytd)])
        writer.writerow([])
        writer.writerow(["Capital inicial", str(capital_inicial)])
        writer.writerow(["Total activos acumulados", str(total_activos)])
        writer.writerow(["Total pasivos acumulados", str(total_pasivos)])
        writer.writerow(["Patrimonio total", str(total_capital)])
        writer.writerow([])

        # Tabla de sub-empresas
        writer.writerow(["RENDIMIENTO POR SUB-EMPRESA"])
        writer.writerow(["Sub-empresa", "Ingresos (activos)", "Egresos (pasivos)", "Flujo neto"])
        for nombre_sub, act_sub, pas_sub, cap_sub in filas_subempresas:
            writer.writerow([nombre_sub, str(act_sub), str(pas_sub), str(cap_sub)])

        # Detalle de sub-empresa (si aplica)
        if tiene_sub:
            writer.writerow([])
            writer.writerow([f"DETALLE OPERATIVO - SUB-EMPRESA: {subempresa.nombre}"])
            writer.writerow(["Rango de fechas", f"{detalle_desde} a {detalle_hasta}"])
            writer.writerow(["Ingresos período", str(ingresos_periodo)])
            writer.writerow(["Egresos período", str(egresos_periodo)])
            writer.writerow(["Flujo neto período", str(flujo_neto_periodo)])
            writer.writerow([])

            writer.writerow(["Movimientos por concepto (período)"])
            writer.writerow(["Concepto", "Ingresos", "Egresos", "Flujo neto"])
            for concepto, act, pas, neto in conceptos_detalle:
                writer.writerow([concepto, str(act), str(pas), str(neto)])

        return response

    if formato == "txt":
        lineas = []
        lineas.append(f"REPORTE FINANCIERO - {empresa.nombre}")
        lineas.append(f"Fecha de corte: {hoy.isoformat()}")
        lineas.append("")
        lineas.append("== Resumen consolidado ==")
        lineas.append(f"Saldo neto consolidado (hoy): {saldo_neto_consolidado}")
        lineas.append(f"Total ingresos YTD: {ingresos_ytd}")
        lineas.append(f"Total egresos YTD: {egresos_ytd}")
        lineas.append(f"Flujo neto YTD: {flujo_neto_ytd}")
        lineas.append("")
        lineas.append(f"Capital inicial: {capital_inicial}")
        lineas.append(f"Total activos acumulados: {total_activos}")
        lineas.append(f"Total pasivos acumulados: {total_pasivos}")
        lineas.append(f"Patrimonio total: {total_capital}")
        lineas.append("")
        lineas.append("== Rendimiento por sub-empresa ==")
        for nombre_sub, act_sub, pas_sub, cap_sub in filas_subempresas:
            lineas.append(
                f"- {nombre_sub}: ingresos={act_sub}, egresos={pas_sub}, flujo_neto={cap_sub}"
            )

        if tiene_sub:
            lineas.append("")
            lineas.append(f"== Detalle operativo - Sub-empresa: {subempresa.nombre} ==")
            lineas.append(f"Rango de fechas: {detalle_desde} a {detalle_hasta}")
            lineas.append(f"Ingresos del período: {ingresos_periodo}")
            lineas.append(f"Egresos del período: {egresos_periodo}")
            lineas.append(f"Flujo neto del período: {flujo_neto_periodo}")
            lineas.append("")
            lineas.append("Movimientos por concepto (período):")
            for concepto, act, pas, neto in conceptos_detalle:
                lineas.append(
                    f"- {concepto}: ingresos={act}, egresos={pas}, flujo_neto={neto}"
                )

        contenido = "\n".join(lineas)
        response = HttpResponse(contenido, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{base_nombre}.txt"'
        return response

    # PDF
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
    except ImportError:
        messages.error(
            request,
            "La exportación a PDF requiere instalar la librería reportlab (pip install reportlab).",
        )
        return redirect("core:balance")

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 50

    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, y, f"Reporte financiero - {empresa.nombre}")
    y -= 20
    p.setFont("Helvetica", 10)
    p.drawString(50, y, f"Fecha de corte: {hoy.isoformat()}")
    y -= 30

    # Resumen consolidado
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Resumen consolidado")
    y -= 15
    p.setFont("Helvetica", 10)
    p.drawString(50, y, f"Saldo neto consolidado (hoy): {saldo_neto_consolidado}")
    y -= 12
    p.drawString(50, y, f"Ingresos YTD: {ingresos_ytd}  |  Egresos YTD: {egresos_ytd}")
    y -= 12
    p.drawString(50, y, f"Flujo neto YTD: {flujo_neto_ytd}")
    y -= 18

    # Sub-empresas
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y, "Rendimiento por sub-empresa")
    y -= 15
    p.setFont("Helvetica", 9)
    for nombre_sub, act_sub, pas_sub, cap_sub in filas_subempresas:
        texto = (
            f"{nombre_sub}: ingresos={act_sub}, egresos={pas_sub}, flujo_neto={cap_sub}"
        )
        p.drawString(50, y, texto)
        y -= 12
        if y < 60:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica", 9)

    # Detalle sub-empresa
    if tiene_sub:
        if y < 80:
            p.showPage()
            y = height - 50
        p.setFont("Helvetica-Bold", 11)
        p.drawString(50, y, f"Detalle operativo - {subempresa.nombre}")
        y -= 15
        p.setFont("Helvetica", 9)
        p.drawString(50, y, f"Rango: {detalle_desde} a {detalle_hasta}")
        y -= 12
        p.drawString(
            50,
            y,
            f"Ingresos período: {ingresos_periodo}  |  Egresos período: {egresos_periodo}",
        )
        y -= 12
        p.drawString(50, y, f"Flujo neto período: {flujo_neto_periodo}")
        y -= 16
        p.setFont("Helvetica-Bold", 10)
        p.drawString(50, y, "Movimientos por concepto:")
        y -= 14
        p.setFont("Helvetica", 9)
        for concepto, act, pas, neto in conceptos_detalle:
            texto = f"{concepto}: ingresos={act}, egresos={pas}, flujo_neto={neto}"
            p.drawString(50, y, texto)
            y -= 12
            if y < 60:
                p.showPage()
                y = height - 50
                p.setFont("Helvetica", 9)

    p.showPage()
    p.save()
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{base_nombre}.pdf"'
    return response

@login_required(login_url="core:login")
def movimiento_detalle_view(request, pk: int):
    mov = get_object_or_404(
        Movimiento.objects.select_related(
            "empresa", "subempresa", "concepto", "usuario_captura"
        ).prefetch_related("pagos"),
        pk=pk,
    )

    # Permisos de lectura (ver detalle del movimiento)
    if not request.user.is_superuser:
        memberships = UsuarioEmpresa.objects.filter(
            usuario=request.user,
            empresa=mov.empresa,
            puede_leer=True,
        )

        if mov.subempresa:
            allowed = memberships.filter(
                Q(subempresa__isnull=True) | Q(subempresa=mov.subempresa)
            ).exists()
        else:
            allowed = memberships.filter(subempresa__isnull=True).exists()

        if not allowed:
            messages.error(request, "No tienes permiso para ver este movimiento.")
            return redirect("core:balance")

    # Orden de pagos (?orden=...)
    orden = request.GET.get("orden", "numero_pago")
    campos_permitidos = {
        "fecha_vencimiento",
        "numero_pago",
        "monto",
        "esta_pagado",
        "fecha_pago",
    }

    if not orden or orden.lstrip("-") not in campos_permitidos:
        orden = "numero_pago"

    pagos_qs = mov.pagos.all().order_by(orden, "numero_pago")

    # Pagos realizados (para la previsualización)
    pagos_realizados = mov.pagos.filter(
        esta_pagado=True,
        fecha_pago__isnull=False,
    ).order_by("numero_pago")

    # Totales: pagado y pendiente
    total_pagado = (
        mov.pagos.filter(esta_pagado=True)
        .aggregate(total=Sum("monto"))["total"] or 0
    )
    total_pendiente = mov.monto_total - total_pagado

    # Fecha límite de pago = fecha de vencimiento del último pago generado
    fecha_limite_pago = (
        mov.pagos.order_by("-fecha_vencimiento")
        .values_list("fecha_vencimiento", flat=True)
        .first()
    )

    # Estatus del movimiento (pendiente / atrasado / saldado)
    hoy = date.today()
    hay_pagos_pendientes = mov.pagos.filter(esta_pagado=False).exists()
    hay_pagos_atrasados = mov.pagos.filter(
        esta_pagado=False,
        fecha_vencimiento__lt=hoy,
    ).exists()

    if total_pendiente <= 0 or not hay_pagos_pendientes:
        estatus_mov = "Saldado"
    elif hay_pagos_atrasados:
        estatus_mov = "Atrasado"
    else:
        estatus_mov = "Con saldo pendiente"

    # Clase visual para la celda de "cantidad por pagar"
    if mov.tipo == Movimiento.TipoMovimiento.ACTIVO:
        clase_total_pendiente = "mov-pendiente-azul"
    else:
        if total_pendiente > 0:
            clase_total_pendiente = "mov-pendiente-alerta"
        elif total_pendiente == 0:
            clase_total_pendiente = "mov-pendiente-verde"
        else:
            clase_total_pendiente = "mov-pendiente-azul"

    # Etiquetas según tipo y si es diferido
    es_activo = mov.tipo == Movimiento.TipoMovimiento.ACTIVO
    es_pasivo = mov.tipo == Movimiento.TipoMovimiento.PASIVO
    es_diferido = mov.numero_pagos > 1

    if es_activo and es_diferido:
        label_pagado = "Cantidad recibida"
        label_pendiente = "Cantidad por recibir"
    elif es_pasivo and es_diferido:
        label_pagado = "Cantidad pagada"
        label_pendiente = "Cantidad por pagar"
    else:
        label_pagado = "Cantidad pagada"
        label_pendiente = "Cantidad pendiente"

    # Sin formulario activo, no hay error global
    form_error_global = ""

    # Siguiente número de pago sugerido (por si reactives el formulario)
    siguiente_numero_pago = mov.pagos.count() + 1

    # Permisos de edición:
    # - Superuser: siempre
    # - ADMIN / FINANCIERO con puede_escribir=True y acceso a la subempresa
    if request.user.is_superuser:
        puede_editar = True
    else:
        memberships_edit = UsuarioEmpresa.objects.filter(
            usuario=request.user,
            empresa=mov.empresa,
            puede_escribir=True,
        )

        if mov.subempresa:
            memberships_edit = memberships_edit.filter(
                Q(subempresa__isnull=True) | Q(subempresa=mov.subempresa)
            )
        else:
            memberships_edit = memberships_edit.filter(subempresa__isnull=True)

        puede_editar = memberships_edit.filter(
            rol__in=[UsuarioEmpresa.Rol.ADMIN, UsuarioEmpresa.Rol.FINANCIERO]
        ).exists()

    # Fecha de vencimiento siguiente (para formulario futuro)
    def calcular_fecha_vencimiento():
        ultimo = mov.pagos.order_by("-numero_pago").first()
        if ultimo and ultimo.fecha_vencimiento:
            base = ultimo.fecha_vencimiento
        else:
            base = mov.fecha_inicio

        if mov.frecuencia_pago == Movimiento.FrecuenciaPago.SEMANAL:
            return base + timedelta(days=7)
        elif mov.frecuencia_pago == Movimiento.FrecuenciaPago.QUINCENAL:
            return base + timedelta(days=14)
        elif mov.frecuencia_pago == Movimiento.FrecuenciaPago.MENSUAL:
            return base + timedelta(days=30)
        elif mov.frecuencia_pago == Movimiento.FrecuenciaPago.ANUAL:
            return base + timedelta(days=365)
        else:
            return base

    fecha_vencimiento_siguiente = calcular_fecha_vencimiento()

    ctx = {
        "movimiento": mov,
        "pagos": pagos_qs,
        "pagos_realizados": pagos_realizados,
        "form_error_global": form_error_global,
        "siguiente_numero_pago": siguiente_numero_pago,
        "puede_editar": puede_editar,
        "total_pagado": total_pagado,
        "total_pendiente": total_pendiente,
        "label_pagado": label_pagado,
        "label_pendiente": label_pendiente,
        "orden_actual": orden,
        "fecha_vencimiento_siguiente": fecha_vencimiento_siguiente,
        "clase_total_pendiente": clase_total_pendiente,
        "estatus_mov": estatus_mov,
        "fecha_limite_pago": fecha_limite_pago,
        "hoy": hoy,
    }
    return render(request, "core/movimiento_detalle.html", ctx)

@login_required(login_url="core:login")
def movimiento_eliminar_view(request, pk: int):
    mov = get_object_or_404(Movimiento, pk=pk)

    # Permisos: debe poder leer y escribir en la empresa / subempresa
    memberships = UsuarioEmpresa.objects.filter(
        usuario=request.user,
        empresa=mov.empresa,
        puede_escribir=True,
    )

    if not request.user.is_superuser:
        if mov.subempresa:
            allowed = memberships.filter(
                Q(subempresa__isnull=True) | Q(subempresa=mov.subempresa)
            ).exists()
        else:
            allowed = memberships.filter(subempresa__isnull=True).exists()

        if not allowed:
            messages.error(request, "No tienes permiso para borrar este movimiento.")
            return redirect("core:captura")

    if request.method == "POST":
        mov.delete()
        messages.success(request, "Movimiento borrado correctamente.")
        return redirect("core:captura")

    # Si llega por GET, redirigimos sin borrar
    return redirect("core:captura")
