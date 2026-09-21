"""
Configuración multi-proveedor de IA, siguiendo el mismo patrón usado en
PRISM EDA Assistant: soporte para proveedores comerciales (Anthropic, un
endpoint compatible con OpenAI, Gemini), NVIDIA NIM (también compatible con
OpenAI, con endpoint propio), un proveedor local (Ollama), o "none" para
usar solo las reglas heurísticas del diccionario/motor de calidad.

Nota de seguridad (OWASP): en desarrollo local esto persiste en un archivo
JSON plano en disco; en producción (Vercel) usa Neon/Postgres vía
storage.py, ya que el filesystem serverless es efímero. En ambos casos la
api_key queda en texto plano en el almacén — para un despliegue expuesto
más allá de uso propio, conviene cifrarla o moverla a un vault de
secretos.
"""
from typing import Optional

import httpx
from pydantic import BaseModel

from app.services.storage import get_json, set_json

_CONFIG_KEY = "ai_config"

DEFAULT_BASE_URLS = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "ollama": "http://localhost:11434",
}
DEFAULT_MODELS = {
    "anthropic": "claude-3-5-haiku-20241022",
    "openai_compatible": "gpt-4o-mini",
    "nvidia": "meta/llama-3.1-8b-instruct",
    "gemini": "gemini-1.5-flash",
    "ollama": "llama3.1",
}


class AIConfig(BaseModel):
    provider: str = "none"  # "none" | "anthropic" | "openai_compatible" | "nvidia" | "gemini" | "ollama"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


async def load_config() -> AIConfig:
    data = await get_json(_CONFIG_KEY)
    if data:
        try:
            return AIConfig.model_validate(data)
        except Exception:
            return AIConfig()
    return AIConfig()


async def save_config(config: AIConfig) -> None:
    await set_json(_CONFIG_KEY, config.model_dump())


def masked(config: AIConfig) -> dict:
    d = config.model_dump()
    if d.get("api_key"):
        d["api_key"] = "•" * 6 + d["api_key"][-4:]
    return d


def _resolve(config: AIConfig) -> tuple[str, str]:
    base = config.base_url or DEFAULT_BASE_URLS.get(config.provider, "")
    model = config.model or DEFAULT_MODELS.get(config.provider, "")
    return base, model


async def test_connection(config: AIConfig) -> tuple[bool, str]:
    try:
        if config.provider == "none":
            return True, "Modo sin IA: se usarán solo las reglas heurísticas."

        if config.provider == "ollama":
            base, _ = _resolve(config)
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(base.rstrip("/") + "/api/tags")
            return (True, "Conexión con Ollama local exitosa.") if r.status_code == 200 \
                else (False, f"Ollama respondió con estado {r.status_code}.")

        if config.provider in ("openai_compatible", "nvidia"):
            base, _ = _resolve(config)
            if not config.api_key:
                return False, "Falta la api_key para este proveedor."
            headers = {"Authorization": f"Bearer {config.api_key}"}
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(base.rstrip("/") + "/models", headers=headers)
            return (True, "Conexión exitosa con el endpoint compatible con OpenAI.") if r.status_code == 200 \
                else (False, f"Respuesta inesperada ({r.status_code}): {r.text[:200]}")

        if config.provider == "anthropic":
            if not config.api_key:
                return False, "Falta la api_key de Anthropic."
            _, model = _resolve(config)
            headers = {"x-api-key": config.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "ping"}]}
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            return (True, "Conexión exitosa con Anthropic.") if r.status_code == 200 \
                else (False, f"Respuesta inesperada ({r.status_code}): {r.text[:200]}")

        if config.provider == "gemini":
            if not config.api_key:
                return False, "Falta la api_key de Gemini."
            _, model = _resolve(config)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.api_key}"
            payload = {"contents": [{"parts": [{"text": "ping"}]}]}
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.post(url, json=payload)
            return (True, "Conexión exitosa con Gemini.") if r.status_code == 200 \
                else (False, f"Respuesta inesperada ({r.status_code}): {r.text[:200]}")

        return False, f"Proveedor desconocido: {config.provider}"
    except Exception as e:
        return False, f"Error de conexión: {e}"


async def generate_text(config: AIConfig, prompt: str) -> Optional[str]:
    """Devuelve texto generado por el proveedor configurado, o None si falla o está en 'none'."""
    if config.provider == "none":
        return None
    try:
        base, model = _resolve(config)

        if config.provider in ("openai_compatible", "nvidia"):
            headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 120}
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(base.rstrip("/") + "/chat/completions", headers=headers, json=payload)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            return None

        if config.provider == "anthropic":
            headers = {"x-api-key": config.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {"model": model, "max_tokens": 120, "messages": [{"role": "user", "content": prompt}]}
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            if r.status_code == 200:
                return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
            return None

        if config.provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json=payload)
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return None

        if config.provider == "ollama":
            payload = {"model": model, "prompt": prompt, "stream": False}
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(base.rstrip("/") + "/api/generate", json=payload)
            if r.status_code == 200:
                return r.json().get("response", "").strip()
            return None

    except Exception:
        return None
    return None
