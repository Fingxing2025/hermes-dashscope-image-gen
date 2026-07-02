"""DashScope image generation backend.

Exposes Alibaba DashScope (阿里云百炼) Qwen-Image generation models
as an :class:`ImageGenProvider` implementation. Uses DashScope's native
multimodal-generation API directly via ``requests``.

Supported models:

    qwen-image-2.0-pro      Qwen Image 2.0 Pro — best quality (recommended)
    qwen-image-2.0          Qwen Image 2.0 — balanced speed/quality
    qwen-image-max          Qwen Image Max — highest realism
    qwen-image-plus         Qwen Image Plus — diverse styles

API reference:
  https://www.alibabacloud.com/help/en/model-studio/qwen-image-api

Selection precedence (first hit wins):

1. ``DASHSCOPE_IMAGE_MODEL`` env var (escape hatch)
2. ``image_gen.dashscope.model`` in ``config.yaml``
3. ``image_gen.model`` in ``config.yaml`` (when it matches a known ID)
4. :data:`DEFAULT_MODEL` — ``qwen-image-2.0-pro``
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    resolve_aspect_ratio,
    save_url_image,
    success_response,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------

_MODELS: Dict[str, Dict[str, Any]] = {
    "qwen-image-2.0-pro": {
        "display": "Qwen Image 2.0 Pro",
        "speed": "~15s",
        "strengths": (
            "Best quality, complex text rendering, multi-line layouts, "
            "fine-grained detail. Supports 1-6 images per call."
        ),
        "price": "varies",
    },
    "qwen-image-2.0": {
        "display": "Qwen Image 2.0",
        "speed": "~10s",
        "strengths": "Balanced speed/quality, accelerated generation",
        "price": "varies",
    },
    "qwen-image-max": {
        "display": "Qwen Image Max",
        "speed": "~20s",
        "strengths": "Highest realism, fewer AI artifacts, natural look",
        "price": "varies",
    },
    "qwen-image-plus": {
        "display": "Qwen Image Plus",
        "speed": "~12s",
        "strengths": "Diverse artistic styles, good text rendering",
        "price": "varies",
    },
}

DEFAULT_MODEL = "qwen-image-2.0-pro"

# Supported sizes for qwen-image-2.0 series.
# Format: width*height as DashScope expects.
_QWEN2_SIZES = {
    "landscape": "2688*1536",   # 16:9
    "square": "2048*2048",      # 1:1
    "portrait": "1536*2688",    # 9:16
}

# Sizes for qwen-image-max / qwen-image-plus (different constraints).
_QWEN_MAX_SIZES = {
    "landscape": "1664*928",
    "square": "1328*1328",
    "portrait": "928*1664",
}

# Model series → size table.
_QWEN2_SERIES = frozenset({"qwen-image-2.0-pro", "qwen-image-2.0"})
_QWEN_MAX_SERIES = frozenset({"qwen-image-max", "qwen-image-plus"})


def _size_for(aspect: str, model_id: str) -> str:
    """Return ``width*height`` string for the given aspect ratio and model."""
    if model_id in _QWEN2_SERIES:
        return _QWEN2_SIZES.get(aspect, _QWEN2_SIZES["square"])
    return _QWEN_MAX_SIZES.get(aspect, _QWEN_MAX_SIZES["square"])


def _load_dashscope_config() -> Dict[str, Any]:
    """Read ``image_gen`` from config.yaml (returns {} on any failure)."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen config: %s", exc)
        return {}


def _resolve_model() -> Tuple[str, Dict[str, Any]]:
    """Decide which model to use and return ``(model_id, meta)``."""
    env_override = os.environ.get("DASHSCOPE_IMAGE_MODEL")
    if env_override and env_override in _MODELS:
        return env_override, _MODELS[env_override]

    cfg = _load_dashscope_config()
    dashscope_cfg = (
        cfg.get("dashscope") if isinstance(cfg.get("dashscope"), dict) else {}
    )
    candidate: Optional[str] = None
    if isinstance(dashscope_cfg, dict):
        value = dashscope_cfg.get("model")
        if isinstance(value, str) and value in _MODELS:
            candidate = value
    if candidate is None:
        top = cfg.get("model")
        if isinstance(top, str) and top in _MODELS:
            candidate = top

    if candidate is not None:
        return candidate, _MODELS[candidate]

    return DEFAULT_MODEL, _MODELS[DEFAULT_MODEL]


def _get_native_endpoint() -> str:
    """Return the DashScope native multimodal-generation endpoint URL.

    The native API lives at ``/api/v1/services/aigc/multimodal-generation/...``
    which is separate from the OpenAI-compatible ``/compatible-mode/v1/...``
    endpoint used for chat completions.  If the user's ``image_gen.base_url``
    config points at the compatible-mode endpoint we strip that suffix and
    substitute the native API base.

    Resolution order:

    1. ``DASHSCOPE_BASE_URL`` env var (operator override).
    2. ``image_gen.base_url`` in ``config.yaml``, with compatible-mode suffix
       stripped if present.
    3. Default: ``https://dashscope.aliyuncs.com/api/v1`` (China domestic).
    """
    # 1) Env var override — use as-is, appending /api/v1 only if missing.
    env_url = os.environ.get("DASHSCOPE_BASE_URL")
    if env_url:
        base = env_url.rstrip("/")
        # Strip compatible-mode suffix if present.
        if base.endswith("/compatible-mode/v1"):
            base = base[: -len("/compatible-mode/v1")]
        if not base.endswith("/api/v1"):
            if base.endswith("/api"):
                base += "/v1"
            else:
                base += "/api/v1"
        return f"{base}/services/aigc/multimodal-generation/generation"

    # 2) Config.yaml image_gen.base_url — used for LLM (compatible-mode);
    #    strip compatible-mode suffix then attach the native API path.
    try:
        cfg = _load_dashscope_config()
        cfg_url = cfg.get("base_url")
        if isinstance(cfg_url, str) and cfg_url.strip():
            base = cfg_url.strip().rstrip("/")
            # The typical value is .../compatible-mode/v1 for chat.
            # Image gen uses the native API path.
            if base.endswith("/compatible-mode/v1"):
                base = base[: -len("/compatible-mode/v1")]
            if not base.endswith("/api/v1"):
                if base.endswith("/api"):
                    base += "/v1"
                else:
                    base += "/api/v1"
            return f"{base}/services/aigc/multimodal-generation/generation"
    except Exception:
        pass

    # 3) Default: China domestic endpoint.
    return (
        "https://dashscope.aliyuncs.com/api/v1"
        "/services/aigc/multimodal-generation/generation"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_image_url(response_data: Dict[str, Any]) -> Optional[str]:
    """Extract the first image URL from a DashScope multimodal-generation response.

    Expected shape::

        {
            "output": {
                "choices": [{
                    "message": {
                        "content": [{"image": "https://..."}]
                    }
                }]
            }
        }
    """
    try:
        choices = response_data["output"]["choices"]
        if not choices:
            return None
        content = choices[0]["message"]["content"]
        if not content:
            return None
        return content[0]["image"]
    except (KeyError, IndexError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class DashScopeImageGenProvider(ImageGenProvider):
    """DashScope Qwen-Image backend via native multimodal-generation API."""

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def display_name(self) -> str:
        return "DashScope (Qwen Image)"

    def is_available(self) -> bool:
        if not os.environ.get("DASHSCOPE_API_KEY"):
            return False
        return True

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": model_id,
                "display": meta["display"],
                "speed": meta["speed"],
                "strengths": meta["strengths"],
                "price": meta.get("price", "varies"),
            }
            for model_id, meta in _MODELS.items()
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "DashScope (Qwen Image)",
            "badge": "paid",
            "tag": (
                "qwen-image-2.0-pro, qwen-image-2.0, qwen-image-max, "
                "qwen-image-plus — Alibaba Cloud Qwen-Image generation"
            ),
            "env_vars": [
                {
                    "key": "DASHSCOPE_API_KEY",
                    "prompt": "DashScope API key",
                    "url": "https://bailian.console.aliyun.com/?apiKey=1",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text"], "max_reference_images": 0}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider="dashscope",
                aspect_ratio=aspect,
            )

        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            return error_response(
                error=(
                    "DASHSCOPE_API_KEY not set. Set it in ~/.hermes/.env "
                    "or via environment variable. Get a key at "
                    "https://bailian.console.aliyun.com/?apiKey=1"
                ),
                error_type="auth_required",
                provider="dashscope",
                aspect_ratio=aspect,
            )

        try:
            import requests
        except ImportError:
            return error_response(
                error="requests Python package not installed",
                error_type="missing_dependency",
                provider="dashscope",
                aspect_ratio=aspect,
            )

        model_id, meta = _resolve_model()
        size = _size_for(aspect, model_id)
        endpoint = _get_native_endpoint()

        payload: Dict[str, Any] = {
            "model": model_id,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ],
            },
            "parameters": {
                "size": size,
                "n": 1,
                "prompt_extend": True,
                "watermark": False,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=120,
            )
        except requests.exceptions.Timeout:
            return error_response(
                error="DashScope image generation timed out (120s)",
                error_type="timeout",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        except requests.exceptions.RequestException as exc:
            logger.debug("DashScope request failed", exc_info=True)
            return error_response(
                error=f"DashScope request failed: {exc}",
                error_type="network_error",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        if resp.status_code != 200:
            err_detail = resp.text[:500] if resp.text else "(empty body)"
            logger.debug(
                "DashScope returned %d: %s", resp.status_code, err_detail
            )
            return error_response(
                error=(
                    f"DashScope image generation failed "
                    f"({resp.status_code}): {err_detail}"
                ),
                error_type="api_error",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            data = resp.json()
        except ValueError:
            return error_response(
                error="DashScope returned non-JSON response",
                error_type="parse_error",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Check for API-level error.
        if "code" in data and data.get("code") != "":
            code = data.get("code", "unknown")
            message = data.get("message", "Unknown error")
            return error_response(
                error=f"DashScope API error [{code}]: {message}",
                error_type="api_error",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        image_url_resp = _extract_image_url(data)
        if not image_url_resp:
            return error_response(
                error="DashScope returned no image URL in response",
                error_type="empty_response",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        # Cache the image locally (DashScope URLs expire after 24h).
        try:
            saved_path = save_url_image(
                image_url_resp, prefix=f"dashscope_{model_id}"
            )
            image_ref = str(saved_path)
        except Exception as exc:
            logger.warning(
                "Could not cache DashScope image %s (%s); using bare URL.",
                image_url_resp,
                exc,
            )
            image_ref = image_url_resp

        return success_response(
            image=image_ref,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            provider="dashscope",
            modality="text",
            extra={"size": size},
        )


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Plugin entry point — wire ``DashScopeImageGenProvider`` into the registry."""
    ctx.register_image_gen_provider(DashScopeImageGenProvider())
