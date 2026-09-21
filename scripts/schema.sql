-- Esquema completo de PRISM ETL/EDA Assistant para Neon/Postgres.
--
-- La app ya crea estas mismas tablas sola (CREATE TABLE IF NOT EXISTS) la
-- primera vez que las necesita, así que correr esto a mano es opcional —
-- pero es útil para dejar la base lista ANTES del primer request (por
-- ejemplo, para revisar el esquema en el dashboard de Neon antes de
-- desplegar, o para tener un script de referencia versionado).
--
-- Es seguro correrlo más de una vez (IF NOT EXISTS en todo).

-- Usuarios y roles (app/services/users.py)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historial de análisis completos (app/services/history.py)
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tables_count INT NOT NULL,
    findings_count INT NOT NULL,
    payload JSONB NOT NULL
);

-- Configuración de la app (por ahora solo la config de IA) (app/services/storage.py)
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Índices de apoyo para las consultas que ya hace la app
CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses (created_at DESC);
