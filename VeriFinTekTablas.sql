-- 1) Tipos enumerados
CREATE TYPE estado_poliza AS ENUM ('borrador','revisada','aprobada','cerrada');
CREATE TYPE tipo_cuenta  AS ENUM ('activo','pasivo','capital','ingreso','gasto');

-- 2) Núcleo organizacional
CREATE TABLE empresa (
  empresa_id      SERIAL PRIMARY KEY,
  nombre          VARCHAR(120) NOT NULL,
  direccion       VARCHAR(200),
  telefono        VARCHAR(50),
  email           VARCHAR(120),
  fecha_creacion  DATE DEFAULT CURRENT_DATE,
  UNIQUE (nombre)
);

CREATE TABLE subempresa (
  subempresa_id   SERIAL PRIMARY KEY,
  empresa_id      INT NOT NULL REFERENCES empresa(empresa_id) ON DELETE CASCADE,
  nombre          VARCHAR(120) NOT NULL,
  direccion       VARCHAR(200),
  telefono        VARCHAR(50),
  email           VARCHAR(120),
  fecha_creacion  DATE DEFAULT CURRENT_DATE,
  UNIQUE (empresa_id, nombre)
);

-- 3) Seguridad: usuarios, roles, permisos
CREATE TABLE usuario (
  usuario_id      SERIAL PRIMARY KEY,
  nombre          VARCHAR(120) NOT NULL,
  email           VARCHAR(120) NOT NULL UNIQUE,
  password_hash   TEXT NOT NULL,
  activo          BOOLEAN NOT NULL DEFAULT TRUE,
  creado_en       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE rol (
  rol_id          SERIAL PRIMARY KEY,
  nombre          VARCHAR(60) NOT NULL UNIQUE,  -- Como capturista, revisor, aprobador, admin, auditor, corp, reportes
  descripcion     TEXT
);

CREATE TABLE permiso (
  permiso_id      SERIAL PRIMARY KEY,
  codigo          VARCHAR(80) NOT NULL UNIQUE,  -- Como poliza.crear, poliza.aprobar, cuentas.gestionar, reportes.ver
  descripcion     TEXT
);

-- Mapeo rol-permiso (plantilla de permisos por rol)
CREATE TABLE rol_permiso (
  rol_id          INT NOT NULL REFERENCES rol(rol_id) ON DELETE CASCADE,
  permiso_id      INT NOT NULL REFERENCES permiso(permiso_id) ON DELETE CASCADE,
  PRIMARY KEY (rol_id, permiso_id)
);

-- Asignación de roles por subempresa (scope)
CREATE TABLE usuario_rol (
  usuario_id      INT NOT NULL REFERENCES usuario(usuario_id) ON DELETE CASCADE,
  rol_id          INT NOT NULL REFERENCES rol(rol_id) ON DELETE CASCADE,
  subempresa_id   INT NOT NULL REFERENCES subempresa(subempresa_id) ON DELETE CASCADE,
  PRIMARY KEY (usuario_id, rol_id, subempresa_id)
);

-- 4) Áreas/Centros de costo (MAR, DEV, REDES)
CREATE TABLE area (
  area_id         SERIAL PRIMARY KEY,
  subempresa_id   INT NOT NULL REFERENCES subempresa(subempresa_id) ON DELETE CASCADE,
  nombre          VARCHAR(80) NOT NULL,         -- Como Marketing, Desarrollo, Redes
  UNIQUE (subempresa_id, nombre)
);

-- 5) Catálogo de cuentas
CREATE TABLE cuenta (
  cuenta_id       SERIAL PRIMARY KEY,
  subempresa_id   INT NOT NULL REFERENCES subempresa(subempresa_id) ON DELETE CASCADE,
  codigo          VARCHAR(30) NOT NULL,         -- ej: 1101-01
  nombre          VARCHAR(120) NOT NULL,
  tipo            tipo_cuenta NOT NULL,
  balance_inicial NUMERIC(16,2) NOT NULL DEFAULT 0,
  balance_actual  NUMERIC(16,2) NOT NULL DEFAULT 0,
  activa          BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (subempresa_id, codigo)
);

-- 6) Periodos contables (para cierres mensuales)
CREATE TABLE periodo (
  periodo_id      SERIAL PRIMARY KEY,
  subempresa_id   INT NOT NULL REFERENCES subempresa(subempresa_id) ON DELETE CASCADE,
  anio            INT NOT NULL,
  mes             INT NOT NULL CHECK (mes BETWEEN 1 AND 12),
  estado          VARCHAR(20) NOT NULL DEFAULT 'abierto',  -- abierto/cerrado
  UNIQUE (subempresa_id, anio, mes)
);

-- 7) Pólizas y partidas (doble entrada)
CREATE TABLE poliza (
  poliza_id       SERIAL PRIMARY KEY,
  subempresa_id   INT NOT NULL REFERENCES subempresa(subempresa_id) ON DELETE CASCADE,
  periodo_id      INT NOT NULL REFERENCES periodo(periodo_id) ON DELETE RESTRICT,
  area_id         INT REFERENCES area(area_id) ON DELETE SET NULL,  
  folio           VARCHAR(40),                                       
  estado          estado_poliza NOT NULL DEFAULT 'borrador',
  descripcion     VARCHAR(200),
  creado_por      INT NOT NULL REFERENCES usuario(usuario_id),
  revisado_por    INT REFERENCES usuario(usuario_id),
  aprobado_por    INT REFERENCES usuario(usuario_id),
  fecha_creacion  TIMESTAMP NOT NULL DEFAULT now(),
  fecha_revision  TIMESTAMP,
  fecha_aprobacion TIMESTAMP,
  -- Reglas básicas de segregación (permiten NULL):
  CHECK (aprobado_por IS NULL OR aprobado_por IS DISTINCT FROM creado_por),
  CHECK (aprobado_por IS NULL OR revisado_por IS NULL OR aprobado_por IS DISTINCT FROM revisado_por)
);

CREATE INDEX idx_poliza_subemp_estado ON poliza(subempresa_id, estado);

CREATE TABLE partida (
  partida_id      SERIAL PRIMARY KEY,
  poliza_id       INT NOT NULL REFERENCES poliza(poliza_id) ON DELETE CASCADE,
  cuenta_id       INT NOT NULL REFERENCES cuenta(cuenta_id),
  descripcion     VARCHAR(200),
  debe            NUMERIC(16,2) NOT NULL DEFAULT 0,
  haber           NUMERIC(16,2) NOT NULL DEFAULT 0,
  CHECK ((debe = 0 AND haber > 0) OR (haber = 0 AND debe > 0))  -- no permitir doble cargo/abono
);

-- Suma cuadra por póliza (se puede reforzar con trigger; aquí índice de apoyo)
CREATE INDEX idx_partida_poliza ON partida(poliza_id);

-- 8) Bitácora de auditoría (cambios críticos)
CREATE TABLE bitacora (
  bitacora_id     BIGSERIAL PRIMARY KEY,
  usuario_id      INT REFERENCES usuario(usuario_id),
  accion          VARCHAR(60) NOT NULL,         -- crear_poliza, aprobar_poliza, crear_cuenta, etc.
  entidad         VARCHAR(60) NOT NULL,         -- 'poliza','partida','cuenta','periodo','usuario', etc.
  entidad_id      BIGINT NOT NULL,
  ts              TIMESTAMP NOT NULL DEFAULT now(),
  ip_origen       INET,
  antes           JSONB,                        -- snapshot previo
  despues         JSONB                         -- snapshot posterior
);

CREATE INDEX idx_bitacora_entidad ON bitacora(entidad, entidad_id);
CREATE INDEX idx_bitacora_ts ON bitacora(ts);

