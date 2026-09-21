-- ============================================================
-- PRISM ETL/EDA Assistant — setup manual para Neon
-- Pegar y correr entero en el editor SQL de Neon (una sola vez).
-- Es seguro re-ejecutarlo: las tablas usan IF NOT EXISTS, y el
-- INSERT del usuario usa ON CONFLICT para no pisar una contraseña
-- que ya hayas cambiado desde la app.
-- ============================================================

-- Usuarios y roles
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historial de análisis completos
CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tables_count INT NOT NULL,
    findings_count INT NOT NULL,
    payload JSONB NOT NULL
);

-- Configuración de la app (config de IA, etc.)
CREATE TABLE IF NOT EXISTS app_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses (created_at DESC);

-- Usuario super_admin precargado.
-- Usuario: admin
-- Contraseña: 7ataOx1lWVY303x2L2   (¡cambiala apenas ingreses!)
-- El hash de abajo es PBKDF2-HMAC-SHA256 (200k iteraciones) de esa
-- contraseña exacta, en el mismo formato "salt_b64:hash_b64" que espera
-- la app (backend/app/services/auth.py) — no es una contraseña en texto
-- plano, pero tampoco es un secreto general: es específica de esta
-- contraseña, cambiala igual.
INSERT INTO users (id, username, password_hash, role, active, created_at)
VALUES (
    '7524f9e2-53dd-4117-854b-33d25f117321',
    'admin',
    '9piJ/9LKLOFSFTcV2Cwsiw==:RUXmVAPZ9wmyPo5eR77PTvA0rqFyq9tkaa0NsQv5LHw=',
    'super_admin',
    true,
    now()
)
ON CONFLICT (username) DO NOTHING;

-- Verificación rápida (debería mostrar la fila de 'admin' con rol super_admin)
SELECT username, role, active, created_at FROM users;
