from __future__ import annotations

"""LLM provider registry and adapter layer used by the pipeline.

This module intentionally provides a small common surface (`model.prompt(...)`) so
the rest of the pipeline can stay provider-agnostic.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import boto3
import llm
import yaml
from dotenv import load_dotenv
from mako.template import Template
from openai import OpenAI

load_dotenv()


# Prompt templating helper used by prompt assembly.
def conditional_render(prompt: str, context: Dict[str, Any]):
    return Template(prompt).render(**context)


def parse_markdown_backticks(s: str, gemini_output: bool = False) -> str:
    # `gemini_output` is kept for backward compatibility with existing callers.
    _ = gemini_output
    if "```" not in s:
        return s.strip()
    s = s.split("```", 1)[-1].split("\n", 1)[-1]
    s = s.rsplit("```", 1)[0]
    return s.strip()


def prompt(model: Any, prompt_str: str) -> str:
    return model.prompt(prompt_str, stream=False).text()


def prompt_with_temp(model: Any, prompt_str: str, temperature: float = 0.7) -> str:
    model_id = getattr(model, "model_id", "")
    if "o1" in model_id or "gemini" in model_id:
        # Preserve previous behavior for these model families.
        return model.prompt(prompt_str, stream=False).text()
    return model.prompt(prompt_str, stream=False, temperature=temperature).text()


def get_model_name(model: Any) -> str:
    return getattr(model, "model_id", "unknown")


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    return v if v else default


@dataclass
class _SimpleLLMResponse:
    # Minimal response shape expected by downstream extraction code.
    _text: str
    _raw: Optional[Dict[str, Any]] = None
    _duration_ms: Optional[float] = None

    def text(self) -> str:
        return self._text

    def json(self) -> Dict[str, Any]:
        return self._raw or {}

    def duration_ms(self) -> float:
        return float(self._duration_ms or 0.0)


class Provider(Protocol):
    def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int] = None,
    ) -> _SimpleLLMResponse: ...


class BedrockProvider:
    # Optional provider kept for teams that still want AWS Bedrock.
    def __init__(self, *, region: Optional[str] = None, profile: Optional[str] = None):
        region_name = region or _env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "eu-west-1"
        session_kwargs: Dict[str, Any] = {"region_name": region_name}
        if profile:
            session_kwargs["profile_name"] = profile
        session = boto3.Session(**session_kwargs)
        self._client = session.client("bedrock-runtime")

    def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int] = None,
    ) -> _SimpleLLMResponse:
        started = time.perf_counter()
        # Prefer Converse API because it is model-family agnostic across Bedrock
        # providers (Anthropic, Nova, etc.) and avoids provider-specific payload
        # shape issues on InvokeModel.
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        inference_cfg: Dict[str, Any] = {
            "temperature": float(temperature),
            "maxTokens": int(max_tokens or 4096),
        }

        try:
            resp = self._client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig=inference_cfg,
            )
            data = resp
            parts: List[str] = []
            content_items = (
                ((resp.get("output") or {}).get("message") or {}).get("content")
                or []
            )
            for item in content_items:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item.get("text", "")))
        except Exception as converse_exc:
            is_anthropic = "anthropic" in str(model_id).lower()
            if not is_anthropic:
                raise RuntimeError(
                    "Bedrock converse call failed for non-Anthropic model/profile. "
                    "Fallback to Anthropic InvokeModel payload is unsafe for this model family. "
                    f"model_id={model_id}; error={converse_exc}"
                ) from converse_exc
            # Fallback for older/runtime-specific setups expecting InvokeModel with
            # Anthropic-style payload.
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": int(max_tokens or 4096),
                "temperature": float(temperature),
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            }

            resp = self._client.invoke_model(
                modelId=model_id,
                body=json.dumps(body).encode("utf-8"),
                accept="application/json",
                contentType="application/json",
            )
            data = json.loads(resp["body"].read())
            parts = []
            for item in (data.get("content", []) or []):
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))

        return _SimpleLLMResponse(
            _text="".join(parts).strip(),
            _raw={"provider": "bedrock", "model": model_id, "response": data},
            _duration_ms=(time.perf_counter() - started) * 1000.0,
        )


class OpenAICompatibleProvider:
    # Works for OpenAI itself and any endpoint implementing compatible chat APIs.
    def __init__(self, *, base_url: str, api_key: str):
        self._client = OpenAI(base_url=base_url, api_key=api_key)

    def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        temperature: float,
        max_tokens: Optional[int] = None,
    ) -> _SimpleLLMResponse:
        started = time.perf_counter()
        kwargs: Dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(temperature),
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = int(max_tokens)

        resp = self._client.chat.completions.create(**kwargs)
        text = ""
        if resp.choices and resp.choices[0].message:
            text = resp.choices[0].message.content or ""

        raw = resp.model_dump()
        return _SimpleLLMResponse(
            _text=text.strip(),
            _raw={"provider": "openai-compatible", "model": model_id, "response": raw},
            _duration_ms=(time.perf_counter() - started) * 1000.0,
        )


class OllamaProvider(OpenAICompatibleProvider):
    # Ollama exposes an OpenAI-compatible API under /v1.
    def __init__(self, *, base_url: Optional[str] = None, api_key: Optional[str] = None):
        ollama_base = base_url or _env("OLLAMA_BASE_URL", "http://localhost:11434/v1") or "http://localhost:11434/v1"
        ollama_key = api_key or _env("OLLAMA_API_KEY", "ollama") or "ollama"
        super().__init__(base_url=str(ollama_base), api_key=str(ollama_key))


class ModelHandle:
    # Adapter that normalizes all providers to the pipeline's `model.prompt(...)` contract.
    def __init__(
        self,
        *,
        name: str,
        model_id: str,
        provider: Provider,
        default_temperature: float = 0.7,
        default_max_tokens: Optional[int] = None,
    ):
        self.name = name
        self.model_id = model_id
        self._provider = provider
        self._default_temperature = float(default_temperature)
        self._default_max_tokens = default_max_tokens

    def prompt(
        self,
        prompt: str,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> _SimpleLLMResponse:
        if stream:
            raise NotImplementedError("Streaming not implemented.")
        return self._provider.generate(
            model_id=self.model_id,
            prompt=prompt,
            temperature=float(temperature if temperature is not None else self._default_temperature),
            max_tokens=max_tokens if max_tokens is not None else self._default_max_tokens,
        )


ModelSpec = Dict[str, Any]


MODEL_REGISTRY: Dict[str, ModelSpec] = {
    "claude-3.5-sonnet": {"type": "llm", "id": "claude-3.5-sonnet", "key_env": "ANTHROPIC_API_KEY"},
    "4o": {"type": "llm", "id": "4o", "key_env": "OPENAI_API_KEY"},
    "gpt-4o": {"type": "llm", "id": "gpt-4o", "key_env": "OPENAI_API_KEY"},
    "gpt-4o-mini": {"type": "llm", "id": "gpt-4o-mini", "key_env": "OPENAI_API_KEY"},
    "gpt-4.5-preview": {"type": "llm", "id": "gpt-4.5-preview", "key_env": "OPENAI_API_KEY"},
    "o1-preview": {"type": "llm", "id": "o1-preview", "key_env": "OPENAI_API_KEY"},
    "o1-mini": {"type": "llm", "id": "o1-mini", "key_env": "OPENAI_API_KEY"},
    "o1": {"type": "llm", "id": "o1", "key_env": "OPENAI_API_KEY"},
    "o3-mini": {"type": "llm", "id": "o3-mini", "key_env": "OPENAI_API_KEY"},
}


_DEFAULT_YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "llm_providers.yaml"


def _load_yaml_model_config() -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    cfg_override = _env("SPEC2CODE_LLM_CONFIG")
    cfg_path = Path(cfg_override if cfg_override else str(_DEFAULT_YAML_PATH))
    if not cfg_path.is_file():
        return {}, {}

    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    providers = data.get("providers", {}) or {}
    models = data.get("models", {}) or {}
    if not isinstance(providers, dict) or not isinstance(models, dict):
        raise ValueError("Invalid LLM YAML config: expected top-level 'providers' and 'models' mappings.")

    return providers, models


def _available_specs() -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    # YAML models override or extend built-in registry entries.
    providers, yaml_models = _load_yaml_model_config()
    merged_models: Dict[str, Dict[str, Any]] = dict(MODEL_REGISTRY)
    for model_name, spec in yaml_models.items():
        if not isinstance(spec, dict):
            raise ValueError(f"Model '{model_name}' in YAML config must be a mapping.")
        merged_models[model_name] = dict(spec)
    return providers, merged_models


def available_model_names() -> List[str]:
    _, merged_models = _available_specs()
    return sorted(merged_models.keys())


def _build_provider(provider_spec: Dict[str, Any]) -> Provider:
    provider_type = str(provider_spec.get("type", "")).strip()
    if provider_type == "bedrock":
        region = provider_spec.get("region") or _env(str(provider_spec.get("region_env", "AWS_REGION")))
        profile = provider_spec.get("profile")
        if not profile and provider_spec.get("profile_env"):
            profile = _env(str(provider_spec["profile_env"]))
        return BedrockProvider(region=region, profile=profile)

    if provider_type == "openai-compatible":
        base_url = provider_spec.get("base_url")
        if not base_url:
            base_url_env = provider_spec.get("base_url_env")
            if base_url_env:
                base_url = _env(str(base_url_env))
        if not base_url:
            raise RuntimeError("openai-compatible provider requires base_url (or base_url_env).")

        api_key = provider_spec.get("api_key")
        if not api_key and provider_spec.get("api_key_env"):
            api_key = _env(str(provider_spec["api_key_env"]))
        if not api_key:
            api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("openai-compatible provider requires api_key (or api_key_env/OPENAI_API_KEY).")
        return OpenAICompatibleProvider(base_url=str(base_url), api_key=str(api_key))

    if provider_type == "ollama":
        base_url = provider_spec.get("base_url")
        if not base_url and provider_spec.get("base_url_env"):
            base_url = _env(str(provider_spec["base_url_env"]))
        api_key = provider_spec.get("api_key")
        if not api_key and provider_spec.get("api_key_env"):
            api_key = _env(str(provider_spec["api_key_env"]))
        return OllamaProvider(base_url=str(base_url) if base_url else None, api_key=str(api_key) if api_key else None)

    raise ValueError(f"Unknown provider type: {provider_type}")


def build_model(name: str) -> Any:
    providers, specs = _available_specs()
    if name.startswith("bedrock-profile/"):
        model_id = name.split("/", 1)[1].strip()
        if not model_id:
            raise KeyError("Invalid model name 'bedrock-profile/' (missing profile id/arn).")
        provider = BedrockProvider(
            region=_env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "eu-west-1",
            profile=_env("AWS_PROFILE"),
        )
        return ModelHandle(
            name=name,
            model_id=model_id,
            provider=provider,
            default_max_tokens=4096,
        )

    if name.startswith("bedrock/"):
        model_id = name.split("/", 1)[1].strip()
        if not model_id:
            raise KeyError("Invalid model name 'bedrock/' (missing model id).")
        provider = BedrockProvider(
            region=_env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "eu-west-1",
            profile=_env("AWS_PROFILE"),
        )
        return ModelHandle(
            name=name,
            model_id=model_id,
            provider=provider,
            default_max_tokens=4096,
        )

    if name.startswith("bedrock:"):
        model_id = name.split(":", 1)[1].strip()
        if not model_id:
            raise KeyError("Invalid model name 'bedrock:' (missing model id).")
        provider = BedrockProvider(
            region=_env("AWS_REGION") or _env("AWS_DEFAULT_REGION") or "eu-west-1",
            profile=_env("AWS_PROFILE"),
        )
        return ModelHandle(
            name=name,
            model_id=model_id,
            provider=provider,
            default_max_tokens=4096,
        )

    if name not in specs:
        raise KeyError(f"Unknown model name '{name}'. Available: {sorted(specs.keys())}")

    spec = specs[name]
    if "provider" in spec:
        provider_name = str(spec["provider"])
        provider_spec = providers.get(provider_name)
        if not isinstance(provider_spec, dict):
            raise RuntimeError(f"Model '{name}' references unknown provider '{provider_name}'.")
        provider = _build_provider(provider_spec)
        model_id = str(spec.get("model") or spec.get("id") or "")
        if not model_id:
            raise RuntimeError(f"Model '{name}' must define 'model' (or 'id') in YAML config.")
        return ModelHandle(
            name=name,
            model_id=model_id,
            provider=provider,
            default_temperature=float(spec.get("default_temperature", 0.7)),
            default_max_tokens=int(spec["max_tokens"]) if spec.get("max_tokens") is not None else None,
        )

    model_type = spec.get("type", "llm")
    model_id = spec["id"]
    if model_type == "llm":
        model: llm.Model = llm.get_model(model_id)
        key_env = spec.get("key_env")
        if key_env:
            key = _env(str(key_env))
            if not key:
                raise RuntimeError(f"Missing environment variable: {key_env}")
            model.key = key
        return model

    if model_type == "bedrock":
        provider = BedrockProvider(
            region=_env(spec.get("region_env", "AWS_REGION")) or _env("AWS_DEFAULT_REGION") or "eu-west-1",
            profile=_env(spec.get("profile_env", "AWS_PROFILE")),
        )
        return ModelHandle(
            name=name,
            model_id=model_id,
            provider=provider,
            default_max_tokens=int(spec.get("max_tokens", 4096)),
        )

    raise ValueError(f"Unknown model type: {model_type}")


def build_models(names: Sequence[str]) -> Dict[str, Any]:
    return {n: build_model(n) for n in names}


def parse_dual_artifact(raw: str) -> Tuple[str, Optional[str], Dict[str, Any]]:
    s = raw.strip()

    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "c" in obj and "h" in obj:
            c = obj["c"]
            h = obj["h"]
            if isinstance(c, str) and isinstance(h, str):
                return c.strip(), h.strip(), {"format": "json"}
    except json.JSONDecodeError:
        pass

    c_only = parse_markdown_backticks(s)
    return c_only, None, {"format": "fallback"}
