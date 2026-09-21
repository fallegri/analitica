from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
from app.services.users import ensure_super_admin

app = FastAPI(title="PRISM ETL/EDA Assistant", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.on_event("startup")
async def _create_initial_super_admin():
    generated_password = await ensure_super_admin()
    if generated_password:
        import os
        username = os.environ.get("SUPER_ADMIN_USERNAME", "admin")
        print("=" * 64)
        print("[PRISM] Usuario super_admin inicial creado.")
        print(f"[PRISM] Usuario: {username}")
        print(f"[PRISM] Contraseña (cambiarla apenas ingreses, no se vuelve a mostrar): {generated_password}")
        print("=" * 64)


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
