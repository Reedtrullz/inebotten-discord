from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.request import Request, urlopen


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class OpenRouterModel:
    id: str
    name: str
    is_free: bool = False

    @property
    def choice(self) -> str:
        return f"{self.name} ({self.id})"


def parse_openrouter_models(payload: bytes | str) -> tuple[OpenRouterModel, ...]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    document = json.loads(payload)
    entries = document.get("data") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ValueError("invalid_openrouter_model_catalog")

    models: dict[str, OpenRouterModel] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            name = model_id
        models[model_id] = OpenRouterModel(
            id=model_id,
            name=name.strip(),
            is_free=_is_free_model(model_id, entry.get("pricing")),
        )

    if not models:
        raise ValueError("empty_openrouter_model_catalog")
    return tuple(sorted(models.values(), key=lambda model: (model.id.casefold(), model.id)))


def _is_free_model(model_id: str, pricing: object) -> bool:
    if model_id.endswith(":free"):
        return True
    if not isinstance(pricing, dict):
        return False
    return _is_zero_price(pricing.get("prompt")) and _is_zero_price(pricing.get("completion"))


def _is_zero_price(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        try:
            return float(value) == 0
        except ValueError:
            return False
    return False


def fetch_openrouter_models(timeout: float = 15) -> tuple[OpenRouterModel, ...]:
    request = Request(
        OPENROUTER_MODELS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "Inebotten-desktop-launcher/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("openrouter_model_catalog_too_large")
    return parse_openrouter_models(payload)
