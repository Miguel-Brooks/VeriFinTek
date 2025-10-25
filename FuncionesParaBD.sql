-- ¿Usuario tiene rol (por nombre) en subempresa?
CREATE OR REPLACE FUNCTION has_role(p_usuario INT, p_rol TEXT, p_subempresa INT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1
    FROM usuario_rol ur
    JOIN rol r ON r.rol_id = ur.rol_id
    WHERE ur.usuario_id = p_usuario
      AND ur.subempresa_id = p_subempresa
      AND lower(r.nombre) = lower(p_rol)
  );
$$;


-- ¿Período está abierto?
CREATE OR REPLACE FUNCTION periodo_abierto(p_periodo INT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT (estado = 'abierto') FROM periodo WHERE periodo_id = p_periodo;
$$;


-- Asegurar monto positivo en partidas
CREATE OR REPLACE FUNCTION monto_positivo(de NUMERIC, ha NUMERIC)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
  SELECT ( (de > 0 AND ha = 0) OR (ha > 0 AND de = 0) );
$$;


-- Valida transición de estado, SoD y período
CREATE OR REPLACE FUNCTION fn_validar_transicion_poliza()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_subempresa INT;
  v_periodo INT;
BEGIN

  IF (TG_OP = 'UPDATE' AND OLD.estado = 'cerrada' AND NEW.estado <> 'cerrada') THEN
    RAISE EXCEPTION 'No se puede reabrir una póliza cerrada';
  END IF;

  v_subempresa := COALESCE(NEW.subempresa_id, OLD.subempresa_id);
  v_periodo    := COALESCE(NEW.periodo_id, OLD.periodo_id);

  IF NOT periodo_abierto(v_periodo) THEN
    RAISE EXCEPTION 'El período % no está abierto', v_periodo;
  END IF;

  IF TG_OP = 'UPDATE' THEN
    IF OLD.estado = 'borrador' AND NEW.estado NOT IN ('borrador','revisada') THEN
      RAISE EXCEPTION 'Transición inválida desde borrador a %', NEW.estado;
    END IF;

    IF OLD.estado = 'revisada' AND NEW.estado NOT IN ('revisada','aprobada') THEN
      RAISE EXCEPTION 'Transición inválida desde revisada a %', NEW.estado;
    END IF;

    IF OLD.estado = 'aprobada' AND NEW.estado NOT IN ('aprobada','cerrada') THEN
      RAISE EXCEPTION 'Transición inválida desde aprobada a %', NEW.estado;
    END IF;
  END IF;

  IF OLD.estado = 'borrador' AND NEW.estado = 'revisada' THEN
    IF NEW.revisado_por IS NULL THEN
      RAISE EXCEPTION 'Debe establecer revisado_por al pasar a revisada';
    END IF;
    IF NOT has_role(NEW.revisado_por, 'revisor', v_subempresa) THEN
      RAISE EXCEPTION 'Usuario % no tiene rol Revisor en subempresa %', NEW.revisado_por, v_subempresa;
    END IF;
	
    IF NEW.revisado_por = NEW.creado_por THEN
      RAISE EXCEPTION 'Quien revisa no puede ser quien creó la póliza';
    END IF;
  END IF;

  IF OLD.estado IN ('borrador','revisada') AND NEW.estado = 'aprobada' THEN
    IF NEW.aprobado_por IS NULL THEN
      RAISE EXCEPTION 'Debe establecer aprobado_por al pasar a aprobada';
    END IF;
    IF NOT has_role(NEW.aprobado_por, 'aprobador', v_subempresa)
       AND NOT has_role(NEW.aprobado_por, 'contador', v_subempresa) THEN
      RAISE EXCEPTION 'Usuario % no tiene rol Aprobador/Contador', NEW.aprobado_por;
    END IF;
    IF NEW.aprobado_por = NEW.creado_por OR NEW.aprobado_por = NEW.revisado_por THEN
      RAISE EXCEPTION 'Conflicto de rol: el aprobador debe ser distinto del creador y revisor';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;


CREATE TRIGGER trg_poliza_validar_transicion
BEFORE UPDATE ON poliza
FOR EACH ROW
EXECUTE FUNCTION fn_validar_transicion_poliza();


CREATE OR REPLACE FUNCTION fn_poliza_set_timestamps()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.estado = 'revisada' AND OLD.estado <> 'revisada' THEN
      NEW.fecha_revision := now();
    END IF;
    IF NEW.estado = 'aprobada' AND OLD.estado <> 'aprobada' THEN
      NEW.fecha_aprobacion := now();
    END IF;
  END IF;
  RETURN NEW;
END;
$$;


CREATE TRIGGER trg_poliza_timestamps
BEFORE UPDATE ON poliza
FOR EACH ROW
EXECUTE FUNCTION fn_poliza_set_timestamps();


CREATE OR REPLACE FUNCTION fn_poliza_bloqueo_edicion()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.estado IN ('aprobada','cerrada') THEN
    -- Permitimos solo transición a 'cerrada' o cambio de campos no críticos
    IF (NEW.estado <> OLD.estado) AND (OLD.estado = 'aprobada' AND NEW.estado = 'cerrada') THEN
      RETURN NEW;
    END IF;
    -- Cambios no permitidos
    IF (ROW(NEW.subempresa_id, NEW.periodo_id, NEW.descripcion, NEW.area_id, NEW.folio)
        IS DISTINCT FROM ROW(OLD.subempresa_id, OLD.periodo_id, OLD.descripcion, OLD.area_id, OLD.folio))
       OR (NEW.estado NOT IN ('aprobada','cerrada')) THEN
      RAISE EXCEPTION 'No se puede editar una póliza aprobada/cerrada';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;


CREATE TRIGGER trg_poliza_bloqueo
BEFORE UPDATE ON poliza
FOR EACH ROW
EXECUTE FUNCTION fn_poliza_bloqueo_edicion();


CREATE OR REPLACE FUNCTION fn_partida_validaciones_basicas()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_pol_sub INT;
  v_cta_sub INT;
BEGIN
  IF NOT monto_positivo(NEW.debe, NEW.haber) THEN
    RAISE EXCEPTION 'Cada partida debe tener importe positivo en solo un lado (debe o haber)';
  END IF;

  SELECT subempresa_id INTO v_pol_sub FROM poliza WHERE poliza_id = NEW.poliza_id;
  SELECT subempresa_id INTO v_cta_sub FROM cuenta WHERE cuenta_id = NEW.cuenta_id;

  IF v_pol_sub IS NULL OR v_cta_sub IS NULL OR v_pol_sub <> v_cta_sub THEN
    RAISE EXCEPTION 'La cuenta y la póliza deben pertenecer a la misma subempresa';
  END IF;

  -- No permitir modificar partidas si la póliza aprobada/cerrada
  IF EXISTS (SELECT 1 FROM poliza p WHERE p.poliza_id = NEW.poliza_id AND p.estado IN ('aprobada','cerrada')) THEN
    RAISE EXCEPTION 'No se pueden crear/editar partidas en póliza aprobada/cerrada';
  END IF;

  RETURN NEW;
END;
$$;


CREATE TRIGGER trg_partida_basicas_ins
BEFORE INSERT ON partida
FOR EACH ROW
EXECUTE FUNCTION fn_partida_validaciones_basicas();


CREATE TRIGGER trg_partida_basicas_upd
BEFORE UPDATE ON partida
FOR EACH ROW
EXECUTE FUNCTION fn_partida_validaciones_basicas();


CREATE OR REPLACE FUNCTION fn_validar_cuadre_poliza(p_poliza INT)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
  v_de NUMERIC(16,2);
  v_ha NUMERIC(16,2);
BEGIN
  SELECT COALESCE(SUM(debe),0), COALESCE(SUM(haber),0)
    INTO v_de, v_ha
  FROM partida
  WHERE poliza_id = p_poliza;

  IF COALESCE(v_de,0) <> COALESCE(v_ha,0) THEN
    RAISE EXCEPTION 'La póliza % no cuadra (debe=% <> haber=%)', p_poliza, v_de, v_ha;
  END IF;
END;
$$;


-- Disparador que valida cuadre al aprobar/cerrar y tras cambios en partidas
CREATE OR REPLACE FUNCTION fn_check_cuadre_on_events()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME = 'partida' THEN
    PERFORM fn_validar_cuadre_poliza(COALESCE(NEW.poliza_id, OLD.poliza_id));
    RETURN NULL;
  ELSIF TG_TABLE_NAME = 'poliza' THEN
    IF NEW.estado IN ('aprobada','cerrada') THEN
      PERFORM fn_validar_cuadre_poliza(NEW.poliza_id);
    END IF;
    RETURN NEW;
  END IF;
  RETURN NULL;
END;
$$;


CREATE TRIGGER trg_partida_valida_cuadre
AFTER INSERT OR UPDATE OR DELETE ON partida
FOR EACH ROW
EXECUTE FUNCTION fn_check_cuadre_on_events();

CREATE TRIGGER trg_poliza_valida_cuadre
BEFORE UPDATE ON poliza
FOR EACH ROW
EXECUTE FUNCTION fn_check_cuadre_on_events();


-- Aplica movimientos de una póliza a los saldos de cuenta
CREATE OR REPLACE FUNCTION fn_aplicar_movimientos_poliza(p_poliza INT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  UPDATE cuenta c
  SET balance_actual = balance_actual
    + COALESCE((
        SELECT COALESCE(SUM(pa.debe - pa.haber),0)
        FROM partida pa
        WHERE pa.cuenta_id = c.cuenta_id
          AND pa.poliza_id = p_poliza
      ),0)
  WHERE c.cuenta_id IN (SELECT cuenta_id FROM partida WHERE poliza_id = p_poliza);
END;
$$;


-- Disparador: al pasar a aprobada, aplica movimientos
CREATE OR REPLACE FUNCTION fn_on_aprobacion_aplicar_saldos()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.estado <> 'aprobada' AND NEW.estado = 'aprobada' THEN
    PERFORM fn_aplicar_movimientos_poliza(NEW.poliza_id);
  END IF;
  RETURN NEW;
END;
$$;


CREATE TRIGGER trg_poliza_aplica_saldos
AFTER UPDATE ON poliza
FOR EACH ROW
EXECUTE FUNCTION fn_on_aprobacion_aplicar_saldos();


-- Serializa OLD/NEW a JSONB
CREATE OR REPLACE FUNCTION row_to_jsonb(anyelement)
RETURNS JSONB LANGUAGE sql IMMUTABLE AS $$
  SELECT to_jsonb($1);
$$;


CREATE OR REPLACE FUNCTION fn_log_bitacora()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_usuario INT;
BEGIN
  v_usuario := NULL;

  IF TG_TABLE_NAME = 'poliza' THEN
    v_usuario := COALESCE(NEW.aprobado_por, NEW.revisado_por, NEW.creado_por, OLD.aprobado_por, OLD.revisado_por, OLD.creado_por);
  ELSIF TG_TABLE_NAME = 'partida' THEN
    v_usuario := NULL;
  ELSIF TG_TABLE_NAME = 'cuenta' THEN
    v_usuario := NULL;
  END IF;

  INSERT INTO bitacora(usuario_id, accion, entidad, entidad_id, ts, antes, despues)
  VALUES (
    v_usuario,
    TG_OP,
    TG_TABLE_NAME,
    COALESCE(
      (CASE WHEN TG_OP = 'DELETE' THEN (OLD).* END)::jsonb->>'*_id',
      (CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN (NEW).* END)::jsonb->>'*_id'
    )::BIGINT,
    now(),
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN row_to_jsonb(OLD) ELSE NULL END,
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN row_to_jsonb(NEW) ELSE NULL END
  );

  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;


-- Poliza
CREATE OR REPLACE FUNCTION fn_log_poliza()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO bitacora(usuario_id, accion, entidad, entidad_id, ts, antes, despues)
  VALUES (
    COALESCE(NEW.aprobado_por, NEW.revisado_por, NEW.creado_por, OLD.aprobado_por, OLD.revisado_por, OLD.creado_por),
    TG_OP, 'poliza',
    COALESCE(NEW.poliza_id, OLD.poliza_id),
    now(),
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END,
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) ELSE NULL END
  );
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;


CREATE TRIGGER trg_log_poliza
AFTER INSERT OR UPDATE OR DELETE ON poliza
FOR EACH ROW EXECUTE FUNCTION fn_log_poliza();


-- Partida
CREATE OR REPLACE FUNCTION fn_log_partida()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO bitacora(usuario_id, accion, entidad, entidad_id, ts, antes, despues)
  VALUES (
    NULL,  
    TG_OP, 'partida',
    COALESCE(NEW.partida_id, OLD.partida_id),
    now(),
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END,
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) ELSE NULL END
  );
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;


CREATE TRIGGER trg_log_partida
AFTER INSERT OR UPDATE OR DELETE ON partida
FOR EACH ROW EXECUTE FUNCTION fn_log_partida();


-- Cuenta
CREATE OR REPLACE FUNCTION fn_log_cuenta()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO bitacora(usuario_id, accion, entidad, entidad_id, ts, antes, despues)
  VALUES (
    NULL,
    TG_OP, 'cuenta',
    COALESCE(NEW.cuenta_id, OLD.cuenta_id),
    now(),
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) ELSE NULL END,
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) ELSE NULL END
  );
  IF TG_OP = 'DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
END;
$$;


CREATE TRIGGER trg_log_cuenta
AFTER INSERT OR UPDATE OR DELETE ON cuenta
FOR EACH ROW EXECUTE FUNCTION fn_log_cuenta();


CREATE OR REPLACE FUNCTION sp_crear_poliza(
  p_subempresa INT,
  p_periodo INT,
  p_area INT,
  p_descripcion TEXT,
  p_creado_por INT,
  p_partidas JSONB
) RETURNS INT LANGUAGE plpgsql AS $$
DECLARE
  v_poliza INT;
  v_item JSONB;
BEGIN
  IF NOT periodo_abierto(p_periodo) THEN
    RAISE EXCEPTION 'Período no abierto';
  END IF;

  INSERT INTO poliza(subempresa_id, periodo_id, area_id, descripcion, estado, creado_por)
  VALUES (p_subempresa, p_periodo, p_area, p_descripcion, 'borrador', p_creado_por)
  RETURNING poliza_id INTO v_poliza;

  FOR v_item IN SELECT * FROM jsonb_array_elements(p_partidas)
  LOOP
    INSERT INTO partida(poliza_id, cuenta_id, descripcion, debe, haber)
    VALUES (
      v_poliza,
      (v_item->>'cuenta_id')::INT,
      v_item->>'descripcion',
      COALESCE((v_item->>'debe')::NUMERIC,0),
      COALESCE((v_item->>'haber')::NUMERIC,0)
    );
  END LOOP;

  PERFORM fn_validar_cuadre_poliza(v_poliza);

  RETURN v_poliza;
END;
$$;