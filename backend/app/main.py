from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.routers.ai_config import router as ai_config_router
from app.routers.analyze import router as analyze_router
from app.routers.auth import router as auth_router
from app.routers.charts import router as charts_router
from app.routers.cleaning import router as cleaning_router
from app.routers.forecast import router as forecast_router
from app.routers.history import router as history_router
from app.routers.synthetic import router as synthetic_router
from app.routers.users import router as users_router
from app.services.history import close_pg_pool as close_history_pool
from app.services.storage import close_pool as close_storage_pool
from app.services.users import close_pg_pool as close_users_pool
from app.services.users import ensure_super_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Patrón recomendado por Vercel para setup en el arranque de la función
    # (ver "Manage startup and shutdown with lifespan events" en sus docs de
    # FastAPI) — reemplaza al @app.on_event("startup") que usábamos antes.
    try:
        generated_password = await ensure_super_admin()
        if generated_password:
            import os
            username = os.environ.get("SUPER_ADMIN_USERNAME", "admin")
            print("=" * 64)
            print("[PRISM] Usuario super_admin inicial creado.")
            print(f"[PRISM] Usuario: {username}")
            print(f"[PRISM] Contraseña (cambiarla apenas ingreses, no se vuelve a mostrar): {generated_password}")
            print("=" * 64)
    except Exception as e:
        # Nunca dejar que un problema de DB en el arranque tumbe TODA la app:
        # sin esto, un DATABASE_URL mal seteado provocaría un 500 en cada
        # request, no solo en los que necesitan la base.
        print(f"[PRISM][ADVERTENCIA] No se pudo verificar/crear el super_admin inicial: {e}")
    yield
    # Shutdown: cerrar pools de conexiones para evitar warnings en serverless
    try:
        await close_storage_pool()
        await close_history_pool()
        await close_users_pool()
    except Exception as e:
        print(f"[PRISM][ADVERTENCIA] Error cerrando pools de BD: {e}")


app = FastAPI(title="PRISM ETL/EDA Assistant", version="1.2.0", lifespan=lifespan)

import os
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").split(",") if os.environ.get("ALLOWED_ORIGINS") else ["http://localhost:8000", "http://127.0.0.1:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(ai_config_router, prefix="/api")
app.include_router(history_router, prefix="/api")
app.include_router(charts_router, prefix="/api")
app.include_router(forecast_router, prefix="/api")
app.include_router(synthetic_router, prefix="/api")
app.include_router(cleaning_router, prefix="/api")


@app.get("/health", include_in_schema=False)
async def health_check():
    """Health check endpoint for Vercel monitoring."""
    return {"status": "ok", "service": "PRISM ETL/EDA Assistant", "version": "1.2.0"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Caso documentado por Vercel: dejar que /favicon.ico caiga en el mount de
    # StaticFiles de abajo puede fallar en su runtime cuando no hay un archivo
    # real ahí. Una ruta explícita ANTES del mount evita el problema —
    # FastAPI respeta el orden de declaración, así que esta ruta tiene
    # prioridad sobre lo que haga el mount para ese mismo path.
    return Response(status_code=204)


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    return Response(content="User-agent: *\nAllow: /\n", media_type="text/plain")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon():
    # Mismo caso que favicon.ico: navegadores/crawlers piden esto solos;
    # sin una ruta explícita, cae en el mount y puede repetir el mismo error.
    return Response(status_code=204)


# Servir el frontend vía StaticFiles SOLO tiene sentido para desarrollo local
# (uvicorn). En Vercel el archivo equivalente vive en /public y lo sirve el
# CDN directamente, sin pasar por la función — ver README, sección Vercel.
# El chequeo de directorio evita que un despliegue sin esa carpeta (por lo
# que sea) tumbe la función entera: sin esto, un mount a un path inexistente
# rompe TODOS los requests, no solo "/".
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
else:
    print(f"[PRISM][ADVERTENCIA] No se encontró la carpeta de frontend en {_FRONTEND_DIR}; "
          f"la API sigue funcionando en /api/*, pero no se sirve HTML en '/'.")
