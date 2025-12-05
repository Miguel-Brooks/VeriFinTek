from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from .models import Empresa, Subempresa, UsuarioEmpresa, Movimiento, Pago, ConceptoMovimiento
from django.db.models import Sum, Q
from django.contrib.admin.views.decorators import staff_member_required
from .forms import MovimientoForm, PagoForm
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

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

    if empresa is None:
        ctx.update({
            "total_activos": 0,
            "total_pasivos": 0,
            "total_capital": 0,
            "balance_detallado": [],
            "ratio_ap_total": None,
            "movimientos_detalle": [],
        })
        return render(request, "core/balance.html", ctx)

    # Query base: todos los movimientos de la empresa actual
    qs_movs = (
        Movimiento.objects
        .filter(empresa=empresa)
        .select_related("subempresa", "concepto", "usuario_captura")
        .order_by("-fecha_registro", "-id")
    )

    # Si hay sub-empresa seleccionada, filtramos a esa
    if subempresa:
        qs_movs = qs_movs.filter(subempresa=subempresa)

    # Totales globales para tarjetas superiores
    total_activos = (
        qs_movs.filter(tipo=Movimiento.TipoMovimiento.ACTIVO)
        .aggregate(total=Sum("monto_total"))["total"] or 0
    )
    total_pasivos = (
        qs_movs.filter(tipo=Movimiento.TipoMovimiento.PASIVO)
        .aggregate(total=Sum("monto_total"))["total"] or 0
    )

    if subempresa:
        # Capital solo de esa sub-empresa
        total_capital = total_activos - total_pasivos
        subempresas = empresa.subempresas.filter(id=subempresa.id, esta_activa=True)
    else:
        # Capital consolidado empresa: capital inicial + A - P
        capital_inicial = empresa.capital_inicial or 0
        total_capital = capital_inicial + total_activos - total_pasivos
        subempresas = empresa.subempresas.filter(esta_activa=True)

    # Balance detallado por sub-empresa (tabla similar a tu HTML original)
    balance_detallado = []
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
        # queryset completo para la tabla de movimientos explícitos
        "movimientos_detalle": qs_movs,
    })
    return render(request, "core/balance.html", ctx)

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
