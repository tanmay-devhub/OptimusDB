"""LLM clients — Groq, Mistral (Codestral), and Cerebras.

All three providers expose OpenAI-compatible chat endpoints, so one class
covers them all — only the base URL, default model, and API-key env var
differ. Pick a provider three ways:

    client = get_client()                    # reads LLM_PROVIDER env, default "groq"
    client = get_client("mistral")           # explicit
    client = MistralClient(model="...")      # explicit subclass

Configuration lives in ``project/.env`` (auto-loaded):

    GROQ_API_KEY=...            (required for provider=groq)
    MISTRAL_API_KEY=...         (required for provider=mistral)
    CEREBRAS_API_KEY=...        (required for provider=cerebras)
    LLM_PROVIDER=groq           (optional — which one /optimize uses)
    GROQ_MODEL / MISTRAL_MODEL / CEREBRAS_MODEL  (optional model overrides)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


# Load .env from project/ (walk up from this file's directory).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # llm/ → backend/ → project/
load_dotenv(_PROJECT_ROOT / ".env")


# Provider registry. Adding a fourth OpenAI-compatible backend is one entry.
PROVIDERS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
    },
    "mistral": {
        # Standard Mistral API endpoint — Codestral is served here as
        # `codestral-latest`. The separate free `codestral.mistral.ai`
        # endpoint has been merged.
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "codestral-latest",
        "api_key_env": "MISTRAL_API_KEY",
        "model_env": "MISTRAL_MODEL",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "default_model": "llama-3.3-70b",
        "api_key_env": "CEREBRAS_API_KEY",
        "model_env": "CEREBRAS_MODEL",
    },
}


@dataclass
class LLMResponse:
    """One completion + telemetry needed to compare providers."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class LLMClient:
    """Unified OpenAI-compatible chat client. Provider chosen at init."""

    def __init__(
        self,
        provider: str,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        """Configure the client for one provider.

        Args:
            provider: Key into ``PROVIDERS``. One of: groq, mistral, cerebras.
            api_key:  Explicit key. Falls back to the provider's env var.
            model:    Explicit model id. Falls back to ``<PROVIDER>_MODEL`` env,
                      then the provider's default.
        """
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown provider {provider!r}. "
                f"Valid: {sorted(PROVIDERS)}"
            )
        cfg = PROVIDERS[provider]
        key = api_key or os.getenv(cfg["api_key_env"])
        if not key:
            raise RuntimeError(
                f"{cfg['api_key_env']} not set for provider {provider!r}. "
                f"Add it to project/.env or export it."
            )
        self.provider = provider
        self.model = model or os.getenv(cfg["model_env"]) or cfg["default_model"]
        self._client = OpenAI(api_key=key, base_url=cfg["base_url"])

    def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """Send a two-message chat completion, return the assistant reply."""
        start = time.perf_counter_ns()
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        latency_ms = (time.perf_counter_ns() - start) / 1_000_000
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=self.model,
            provider=self.provider,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
            latency_ms=latency_ms,
        )


class GroqClient(LLMClient):
    """Groq / Llama 3.3 70B — fast fallback / debounce hints (per PLANNING.md)."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__("groq", api_key=api_key, model=model)


class MistralClient(LLMClient):
    """Mistral / Codestral — primary rewrite path (SQL-specialized model)."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__("mistral", api_key=api_key, model=model)


class CerebrasClient(LLMClient):
    """Cerebras — batch benchmark runs; fastest inference on Llama."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        super().__init__("cerebras", api_key=api_key, model=model)


def get_client(provider: str | None = None) -> LLMClient:
    """Return the LLM client for ``provider`` (or the env-configured default).

    Precedence: explicit arg → ``LLM_PROVIDER`` env → "groq".
    """
    provider = (provider or os.getenv("LLM_PROVIDER") or "groq").lower()
    return LLMClient(provider=provider)


def available_providers() -> dict[str, dict[str, str | bool]]:
    """Report which providers have API keys set (without leaking the keys)."""
    out: dict[str, dict[str, str | bool]] = {}
    for name, cfg in PROVIDERS.items():
        out[name] = {
            "base_url": cfg["base_url"],
            "default_model": cfg["default_model"],
            "api_key_env": cfg["api_key_env"],
            "configured": bool(os.getenv(cfg["api_key_env"])),
        }
    return out


# -----------------------------------------------------------------------------
# Smoke test — list providers and ping whichever have keys.
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("Provider status:")
    for name, info in available_providers().items():
        mark = "✓" if info["configured"] else "·"
        print(f"  [{mark}] {name:8s}  model={info['default_model']:30s}  "
              f"key_env={info['api_key_env']}")

    print()
    print("Pinging configured providers:")
    for name, info in available_providers().items():
        if not info["configured"]:
            print(f"  [skip] {name}: no API key set")
            continue
        try:
            client = LLMClient(provider=name)
            resp = client.complete(
                system="Answer in exactly one word.",
                user="What is 2+2?",
            )
            print(f"  [ok ] {name} ({resp.model}): "
                  f"{resp.content.strip()!r}  "
                  f"latency={resp.latency_ms:.0f}ms  "
                  f"tokens={resp.input_tokens}→{resp.output_tokens}")
        except Exception as exc:
            print(f"  [err ] {name}: {type(exc).__name__}: {exc}")
