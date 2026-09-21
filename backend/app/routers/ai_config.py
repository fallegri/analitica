from fastapi import APIRouter, Depends

from app.routers.auth_deps import require_min_rank
from app.services.ai_providers import AIConfig, load_config, masked, save_config, test_connection
from app.services.storage import storage_backend

router = APIRouter()

PROVIDERS_INFO = [
    {"id": "none", "label": "Sin IA (solo reglas heurísticas)", "kind": "local"},
    {"id": "anthropic", "label": "Anthropic (comercial)", "kind": "commercial"},
    {"id": "openai_compatible", "label": "OpenAI / compatible (comercial)", "kind": "commercial"},
    {"id": "nvidia", "label": "NVIDIA NIM (integrate.api.nvidia.com)", "kind": "commercial"},
    {"id": "gemini", "label": "Google Gemini (comercial)", "kind": "commercial"},
    {"id": "ollama", "label": "Ollama (local)", "kind": "local"},
]


@router.get("/ai-config/providers")
async def list_providers(actor: dict = Depends(require_min_rank("report_viewer"))):
    return PROVIDERS_INFO


@router.get("/ai-config")
async def get_ai_config(actor: dict = Depends(require_min_rank("analista"))):
    cfg = await load_config()
    out = masked(cfg)
    out["storage_backend"] = storage_backend()
    return out


@router.post("/ai-config")
async def set_ai_config(config: AIConfig, actor: dict = Depends(require_min_rank("admin"))):
    await save_config(config)
    ok, message = await test_connection(config)
    return {"saved": True, "connection_ok": ok, "message": message, "storage_backend": storage_backend()}


@router.post("/ai-config/test")
async def test_ai_config(config: AIConfig | None = None, actor: dict = Depends(require_min_rank("admin"))):
    cfg = config if config is not None else await load_config()
    ok, message = await test_connection(cfg)
    return {"connection_ok": ok, "message": message}
