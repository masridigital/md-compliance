"""
Masri Digital Compliance Platform — LLM Service Layer

Multi-provider LLM abstraction supporting OpenAI, Anthropic, Azure OpenAI,
and Ollama.  All calls go through a single ``LLMService`` façade that reads
configuration from the database (``SettingsLLM``) and enforces per-tenant
token budgets and rate limits.  Tracks per-provider cost estimates.
"""

import json
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _get_cache():
    """Get the Flask-Caching instance, or None if unavailable."""
    try:
        from app import cache
        return cache
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pricing table — per 1M tokens (input / output)
# Update these when providers change pricing.
# ---------------------------------------------------------------------------

MODEL_PRICING = {
    # Anthropic
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-20250506": {"input": 0.80, "output": 4.0},
    # Aliases
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0},

    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.0, "output": 60.0},
    "o1-mini": {"input": 3.0, "output": 12.0},
    "o3-mini": {"input": 1.10, "output": 4.40},

    # Together AI (representative models — prices vary by model size)
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": {"input": 0.18, "output": 0.18},
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": {"input": 0.88, "output": 0.88},
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": {"input": 3.50, "output": 3.50},
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {"input": 0.88, "output": 0.88},
    "deepseek-ai/DeepSeek-R1": {"input": 3.00, "output": 3.00},
    "deepseek-ai/DeepSeek-R1-Distill-Llama-70B": {"input": 0.88, "output": 0.88},
    "deepseek-ai/DeepSeek-V3": {"input": 0.90, "output": 0.90},
    "Qwen/Qwen2.5-72B-Instruct-Turbo": {"input": 0.90, "output": 0.90},
    "Qwen/Qwen2.5-7B-Instruct-Turbo": {"input": 0.20, "output": 0.20},
    "google/gemma-2-27b-it": {"input": 0.80, "output": 0.80},
    "google/gemma-2-9b-it": {"input": 0.30, "output": 0.30},
    "mistralai/Mixtral-8x7B-Instruct-v0.1": {"input": 0.60, "output": 0.60},
    "mistralai/Mistral-7B-Instruct-v0.3": {"input": 0.20, "output": 0.20},
}

# Provider-level fallback pricing (when exact model not in table)
PROVIDER_DEFAULT_PRICING = {
    "anthropic": {"input": 3.0, "output": 15.0},      # Sonnet-tier default
    "openai": {"input": 2.50, "output": 10.0},         # GPT-4o default
    "azure_openai": {"input": 2.50, "output": 10.0},   # Same as OpenAI
    "together": {"input": 0.88, "output": 0.88},       # 70B-tier default
    "together_ai": {"input": 0.88, "output": 0.88},
}


_together_pricing_loaded = False


def _get_model_pricing(model: str, provider: str = "") -> dict:
    """Look up per-1M-token pricing for a model, with provider fallback."""
    global _together_pricing_loaded
    # Exact match
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Prefix match (handles versioned model IDs like claude-sonnet-4-20250514)
    for key in MODEL_PRICING:
        if model.startswith(key) or key.startswith(model):
            return MODEL_PRICING[key]
    # Lazy-load Together AI cached pricing on first miss for a together model
    if not _together_pricing_loaded and provider in ("together", "together_ai"):
        _together_pricing_loaded = True
        try:
            TogetherAIPricingClient.get_cached_pricing()
            # Retry exact match after loading
            if model in MODEL_PRICING:
                return MODEL_PRICING[model]
        except Exception:
            pass
    # Provider fallback
    return PROVIDER_DEFAULT_PRICING.get(provider, {"input": 1.0, "output": 1.0})


def _calculate_cost(prompt_tokens: int, completion_tokens: int, model: str, provider: str) -> float:
    """Calculate cost in USD for a single API call."""
    pricing = _get_model_pricing(model, provider)
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------

class _BaseProvider:
    """Common interface every provider adapter must implement."""

    def __init__(self, config):
        self.config = config

    def chat(self, messages: list, **kwargs) -> dict:
        """
        Send a chat completion request.

        Args:
            messages: list of {"role": ..., "content": ...} dicts
            **kwargs: model-specific overrides (temperature, max_tokens, etc.)

        Returns:
            dict with keys: content (str), usage (dict), model (str), provider (str)
        """
        raise NotImplementedError


class OpenAIProvider(_BaseProvider):
    """OpenAI (api.openai.com) chat completions."""

    def chat(self, messages, **kwargs):
        import openai

        api_key = self.config.get("api_key", "")
        client = openai.OpenAI(api_key=api_key, timeout=90.0)

        model = kwargs.pop("model", self.config.get("model_name", "gpt-4o"))
        temperature = kwargs.pop("temperature", 0.3)
        max_tokens = kwargs.pop("max_tokens", 4096)

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        choice = resp.choices[0]
        return {
            "content": choice.message.content,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            },
            "model": resp.model,
            "provider": "openai",
        }


class AnthropicProvider(_BaseProvider):
    """Anthropic (api.anthropic.com) messages API."""

    def chat(self, messages, **kwargs):
        import anthropic

        api_key = self.config.get("api_key", "")
        client = anthropic.Anthropic(api_key=api_key, timeout=90.0)

        model = kwargs.pop("model", self.config.get("model_name", "claude-sonnet-4-20250514"))
        max_tokens = kwargs.pop("max_tokens", 4096)
        temperature = kwargs.pop("temperature", 0.3)

        # Anthropic requires system prompt separate from messages
        system = None
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        create_kwargs = {
            "model": model,
            "messages": filtered,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            create_kwargs["system"] = system

        resp = client.messages.create(**create_kwargs)

        content = ""
        for block in resp.content:
            if block.type == "text":
                content += block.text

        return {
            "content": content,
            "usage": {
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
                "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
            },
            "model": resp.model,
            "provider": "anthropic",
        }


class AzureOpenAIProvider(_BaseProvider):
    """Azure OpenAI Service chat completions."""

    def chat(self, messages, **kwargs):
        import openai

        api_key = self.config.get("api_key", "")
        endpoint = self.config.get("azure_endpoint", "")
        deployment = self.config.get("azure_deployment", "")

        client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-06-01",
            timeout=90.0,
        )

        temperature = kwargs.pop("temperature", 0.3)
        max_tokens = kwargs.pop("max_tokens", 4096)

        resp = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        choice = resp.choices[0]
        return {
            "content": choice.message.content,
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            },
            "model": deployment,
            "provider": "azure_openai",
        }


class TogetherAIProvider(_BaseProvider):
    """Together AI — OpenAI-compatible API for open-source models."""

    def chat(self, messages, **kwargs):
        import openai

        api_key = self.config.get("api_key")
        model = kwargs.pop("model", self.config.get("model_name", "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"))
        temperature = kwargs.pop("temperature", 0.3)
        max_tokens = kwargs.pop("max_tokens", 4096)

        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.together.xyz/v1",
            timeout=90.0,
        )

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        usage = response.usage

        return {
            "content": choice.message.content,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
            "model": response.model,
            "provider": "together",
        }


# Provider registry
_PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "azure_openai": AzureOpenAIProvider,
    "together": TogetherAIProvider,
    "together_ai": TogetherAIProvider,  # alias — UI stores as together_ai
}


# ---------------------------------------------------------------------------
# Rate-limit / budget tracking (in-memory, resets on restart)
# ---------------------------------------------------------------------------

class _UsageTracker:
    """Simple in-memory per-tenant usage tracker."""

    def __init__(self):
        self._tokens = {}   # tenant_id -> total_tokens used
        self._calls = {}    # tenant_id -> [(timestamp, ...)]

    def record(self, tenant_id: str, total_tokens: int):
        self._tokens.setdefault(tenant_id, 0)
        self._tokens[tenant_id] += total_tokens
        self._calls.setdefault(tenant_id, [])
        self._calls[tenant_id].append(time.time())

    def tokens_used(self, tenant_id: str) -> int:
        return self._tokens.get(tenant_id, 0)

    def calls_in_last_hour(self, tenant_id: str) -> int:
        cutoff = time.time() - 3600
        calls = self._calls.get(tenant_id, [])
        # Prune old entries
        recent = [t for t in calls if t >= cutoff]
        self._calls[tenant_id] = recent
        return len(recent)


_usage = _UsageTracker()


# ---------------------------------------------------------------------------
# Service façade
# ---------------------------------------------------------------------------

class LLMService:
    """
    Stateless service façade for LLM operations.

    Reads config from SettingsLLM in the database. Enforces optional
    per-tenant token budgets and hourly rate limits.
    """

    @staticmethod
    def _get_config() -> dict:
        """
        Load the active LLM configuration.

        Checks ConfigStore providers first (the unified provider store),
        then falls back to SettingsLLM for backwards compatibility.

        Returns:
            dict with provider, model_name, api_key (decrypted), etc.
            None if no LLM is configured.
        """
        import json as _json

        # Primary source: ConfigStore llm_additional_providers
        try:
            from app.models import ConfigStore
            from app.masri.settings_service import decrypt_value
            record = ConfigStore.find("llm_additional_providers")
            if record and record.value:
                providers = _json.loads(record.value)
                # Use first provider with an API key
                for key, cfg in providers.items():
                    if cfg.get("api_key_enc"):
                        api_key = ""
                        try:
                            api_key = decrypt_value(cfg["api_key_enc"])
                        except Exception:
                            pass
                        if api_key:
                            return {
                                "provider": cfg.get("provider", key),
                                "model_name": cfg.get("model_name", ""),
                                "api_key": api_key,
                                "azure_endpoint": cfg.get("azure_endpoint", ""),
                                "azure_deployment": cfg.get("azure_deployment", ""),
                                "ollama_base_url": "",
                                "token_budget_per_tenant": 0,
                                "rate_limit_per_hour": 0,
                            }
        except Exception:
            pass

        # Fallback: SettingsLLM (legacy)
        try:
            from app.masri.settings_service import SettingsService
            llm = SettingsService.get_active_llm_config()
            if llm is None:
                return None
            config = {
                "provider": llm.provider,
                "model_name": llm.model_name,
                "azure_endpoint": getattr(llm, "azure_endpoint", ""),
                "azure_deployment": getattr(llm, "azure_deployment", ""),
                "ollama_base_url": getattr(llm, "ollama_base_url", ""),
                "token_budget_per_tenant": getattr(llm, "token_budget_per_tenant", 0),
                "rate_limit_per_hour": getattr(llm, "rate_limit_per_hour", 0),
            }
            if llm.api_key_enc:
                try:
                    config["api_key"] = llm.get_api_key()
                except Exception:
                    config["api_key"] = ""
            else:
                config["api_key"] = ""
            return config
        except Exception:
            return None

    @staticmethod
    def _get_provider(config: dict) -> _BaseProvider:
        provider_name = config.get("provider", "openai")
        cls = _PROVIDERS.get(provider_name)
        if cls is None:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")
        return cls(config)

    @staticmethod
    def is_enabled() -> bool:
        """Check whether LLM functionality is enabled and configured."""
        try:
            config = LLMService._get_config()
            return config is not None
        except Exception:
            return False

    # Feature → Tier mapping (hardcoded, not user-configurable)
    # Users configure 4 tiers, not 10+ individual features.
    FEATURE_TIERS = {
        # Tier 1 — Extraction: high-volume structured parsing, cheapest models
        "data_parsing": "extraction",
        "summarize": "extraction",
        "evidence_interpret": "extraction",

        # Tier 2 — Mapping: compliance control mapping, needs good JSON output
        "auto_map": "mapping",
        "control_assess": "mapping",
        "risk_score": "mapping",

        # Tier 3 — Analysis: recommendations + gap analysis, needs reasoning
        "assist_gaps": "analysis",
        "gap_narrative": "analysis",

        # Tier 4 — Advanced: policy drafting, risk profiles, complex analysis
        "policy_draft": "advanced",
        "user_risk_profile": "advanced",
        "device_risk_profile": "advanced",
    }

    @staticmethod
    def get_feature_routing(feature: str) -> dict:
        """Get the provider+model for a feature via its tier assignment.

        Routing priority:
        1. Direct per-feature override (legacy, if set)
        2. Tier-based routing (recommended)
        3. Default primary config

        Redis-cached for 5 minutes.

        Returns:
            dict with 'provider' and 'model' keys, or None for default.
        """
        # Check Redis cache for the full routing config
        c = _get_cache()
        data = None
        if c:
            try:
                data = c.get("llm_feature_models")
            except Exception:
                pass
        if data is None:
            try:
                from app.models import ConfigStore
                import json
                record = ConfigStore.find("llm_feature_models")
                if record and record.value:
                    data = json.loads(record.value)
                    if c:
                        try:
                            c.set("llm_feature_models", data, timeout=300)
                        except Exception:
                            pass
            except Exception:
                pass
        if not data:
            return None
        try:
            if data.get("sameForAll", True):
                tiers = data.get("tiers", {})
                same_provider = tiers.get("_sameProvider")
                same_model = tiers.get("_sameModel")
                if same_provider:
                    return {"provider": same_provider, "model": same_model or ""}
                return None

            tiers = data.get("tiers", {})
            if tiers:
                tier = LLMService.FEATURE_TIERS.get(feature, "standard")
                tier_config = tiers.get(tier)
                if tier_config and isinstance(tier_config, dict) and tier_config.get("provider"):
                    return tier_config

            routing = data.get("models", {}).get(feature)
            if routing and isinstance(routing, dict):
                return routing
            if routing and isinstance(routing, str):
                return {"model": routing}
        except Exception:
            pass
        return None

    @staticmethod
    def _store_debug(entry):
        """Store an LLM debug entry in ConfigStore (ring buffer, max 50)."""
        try:
            import json
            from app.models import ConfigStore
            from app import db
            key = "llm_debug_log"
            existing = []
            rec = ConfigStore.find(key)
            if rec and rec.value:
                try:
                    existing = json.loads(rec.value)
                except Exception:
                    existing = []
            existing.insert(0, entry)
            existing = existing[:50]  # Keep last 50 calls
            ConfigStore.upsert(key, json.dumps(existing, default=str))
            db.session.commit()
        except Exception:
            pass  # Never crash the LLM call for debug logging

    @staticmethod
    def get_debug_log(limit=50):
        """Get stored LLM debug entries."""
        try:
            import json
            from app.models import ConfigStore
            rec = ConfigStore.find("llm_debug_log")
            if rec and rec.value:
                entries = json.loads(rec.value)
                return entries[:limit]
        except Exception:
            pass
        return []

    @staticmethod
    def _record_cost(provider: str, model: str, prompt_tokens: int,
                     completion_tokens: int, cost: float, feature: str = None,
                     tenant_id: str = None):
        """Persist cost data to ConfigStore for usage tracking.

        Structure in ConfigStore("llm_cost_tracker"):
        {
            "totals": {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
            "by_provider": {
                "anthropic": {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
                ...
            },
            "by_model": {
                "claude-sonnet-4-20250514": {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
                ...
            },
            "daily": {
                "2026-04-12": {"cost": 0.0, "calls": 0},
                ...
            },
            "recent": [  # last 200 calls
                {"ts": "...", "provider": "...", "model": "...", "cost": 0.001, ...},
            ]
        }
        """
        try:
            from app.models import ConfigStore
            from app import db

            key = "llm_cost_tracker"
            rec = ConfigStore.find(key)
            data = {}
            if rec and rec.value:
                try:
                    data = json.loads(rec.value)
                except Exception:
                    data = {}

            # Initialize structure
            if "totals" not in data:
                data["totals"] = {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
            if "by_provider" not in data:
                data["by_provider"] = {}
            if "by_model" not in data:
                data["by_model"] = {}
            if "daily" not in data:
                data["daily"] = {}
            if "recent" not in data:
                data["recent"] = []

            # Update totals
            data["totals"]["cost"] = round(data["totals"]["cost"] + cost, 6)
            data["totals"]["prompt_tokens"] += prompt_tokens
            data["totals"]["completion_tokens"] += completion_tokens
            data["totals"]["calls"] += 1

            # Update per-provider
            if provider not in data["by_provider"]:
                data["by_provider"][provider] = {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
            prov = data["by_provider"][provider]
            prov["cost"] = round(prov["cost"] + cost, 6)
            prov["prompt_tokens"] += prompt_tokens
            prov["completion_tokens"] += completion_tokens
            prov["calls"] += 1

            # Update per-model
            if model not in data["by_model"]:
                data["by_model"][model] = {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
            mdl = data["by_model"][model]
            mdl["cost"] = round(mdl["cost"] + cost, 6)
            mdl["prompt_tokens"] += prompt_tokens
            mdl["completion_tokens"] += completion_tokens
            mdl["calls"] += 1

            # Update daily
            today = datetime.utcnow().strftime("%Y-%m-%d")
            if today not in data["daily"]:
                data["daily"][today] = {"cost": 0.0, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
            data["daily"][today]["cost"] = round(data["daily"][today]["cost"] + cost, 6)
            data["daily"][today]["calls"] += 1
            data["daily"][today]["prompt_tokens"] += prompt_tokens
            data["daily"][today]["completion_tokens"] += completion_tokens

            # Prune daily entries older than 90 days
            cutoff = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            data["daily"] = {d: v for d, v in data["daily"].items() if d >= cutoff}

            # Add to recent calls (ring buffer, max 200)
            data["recent"].insert(0, {
                "ts": datetime.utcnow().isoformat(),
                "provider": provider,
                "model": model,
                "feature": feature,
                "tenant_id": tenant_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost,
            })
            data["recent"] = data["recent"][:200]

            ConfigStore.upsert(key, json.dumps(data, default=str))
            db.session.commit()
            # Invalidate Redis cache so next read gets fresh data
            c = _get_cache()
            if c:
                try:
                    c.delete("llm_cost_data")
                except Exception:
                    pass
        except Exception:
            pass  # Never crash the LLM call for cost tracking

    @staticmethod
    def get_cost_data() -> dict:
        """Retrieve the full cost tracking data (Redis-cached, 30s TTL)."""
        _empty = {"totals": {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
                  "by_provider": {}, "by_model": {}, "daily": {}, "recent": []}
        # Try Redis cache first
        c = _get_cache()
        if c:
            try:
                cached = c.get("llm_cost_data")
                if cached is not None:
                    return cached
            except Exception:
                pass
        try:
            from app.models import ConfigStore
            rec = ConfigStore.find("llm_cost_tracker")
            if rec and rec.value:
                data = json.loads(rec.value)
                # Store in Redis cache (30s TTL)
                if c:
                    try:
                        c.set("llm_cost_data", data, timeout=30)
                    except Exception:
                        pass
                return data
        except Exception:
            pass
        return _empty

    @staticmethod
    def reset_cost_data():
        """Reset all cost tracking data (admin action)."""
        try:
            from app.models import ConfigStore
            from app import db
            ConfigStore.upsert("llm_cost_tracker", json.dumps({
                "totals": {"cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
                "by_provider": {}, "by_model": {}, "daily": {}, "recent": [],
            }))
            db.session.commit()
            # Invalidate Redis cache
            c = _get_cache()
            if c:
                try:
                    c.delete("llm_cost_data")
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def get_feature_model(feature: str) -> str:
        """Get the model name for a feature (backward compat)."""
        routing = LLMService.get_feature_routing(feature)
        if routing:
            return routing.get("model")
        return None

    @staticmethod
    def _get_fallback_config(failed_provider: str) -> dict:
        """Load the fallback provider config when a tier's provider fails."""
        try:
            from app.models import ConfigStore
            import json
            record = ConfigStore.find("llm_feature_models")
            if record and record.value:
                data = json.loads(record.value)
                tiers = data.get("tiers", {})
                fallback_key = tiers.get("fallback_provider", "")
                if fallback_key and fallback_key != failed_provider:
                    # Try loading the fallback provider's config
                    alt = LLMService._get_provider_config(fallback_key)
                    if alt:
                        return alt
            # Default fallback: try the primary config
            primary = LLMService._get_config()
            if primary and primary.get("provider") != failed_provider:
                return primary
        except Exception:
            pass
        return None

    @staticmethod
    def _get_provider_config(provider_key: str) -> dict:
        """Load a named provider config from ConfigStore.

        Single source of truth: ConfigStore("llm_additional_providers").
        Redis-cached for 5 minutes to avoid hitting Postgres on every LLM call.
        """
        cache_key = f"llm_provider_cfg:{provider_key}"
        c = _get_cache()
        if c:
            try:
                cached = c.get(cache_key)
                if cached is not None:
                    return cached if cached != "__none__" else None
            except Exception:
                pass
        try:
            from app.models import ConfigStore
            import json
            record = ConfigStore.find("llm_additional_providers")
            if record and record.value:
                extras = json.loads(record.value)
                config = extras.get(provider_key, {})
                if not config:
                    if c:
                        try:
                            c.set(cache_key, "__none__", timeout=300)
                        except Exception:
                            pass
                    return None
                # Decrypt API key if present
                if config.get("api_key_enc"):
                    from app.masri.settings_service import decrypt_value
                    config["api_key"] = decrypt_value(config["api_key_enc"])
                    del config["api_key_enc"]
                if c:
                    try:
                        c.set(cache_key, config, timeout=300)
                    except Exception:
                        pass
                return config
        except Exception:
            pass
        return None

    @staticmethod
    def chat(messages: list, tenant_id: str = None, feature: str = None, **kwargs) -> dict:
        """
        Send a chat completion request through the configured provider.

        Supports per-feature provider routing: each feature (auto_map, assist_gaps,
        web_research, data_parsing, etc.) can use a different provider+model.

        Args:
            messages: list of {"role": ..., "content": ...} dicts
            tenant_id: optional, for budget/rate-limit enforcement
            feature: optional feature name for per-feature provider routing
            **kwargs: overrides passed to the provider (temperature, max_tokens, etc.)

        Returns:
            dict with keys: content, usage, model, provider

        Raises:
            RuntimeError: if LLM is not configured or limits exceeded
        """
        # Start with default config
        config = LLMService._get_config()
        if config is None:
            raise RuntimeError("LLM is not configured or not enabled")

        # Per-feature provider+model override
        if feature and "model" not in kwargs:
            routing = LLMService.get_feature_routing(feature)
            if routing:
                # If routing specifies a different provider, load that provider's config
                if routing.get("provider") and routing["provider"] != config["provider"]:
                    alt_config = LLMService._get_provider_config(routing["provider"])
                    if alt_config:
                        # Merge: use the alt provider but keep rate limits from primary
                        rate_limit = config.get("rate_limit_per_hour")
                        token_budget = config.get("token_budget_per_tenant")
                        config = alt_config
                        config["rate_limit_per_hour"] = rate_limit
                        config["token_budget_per_tenant"] = token_budget
                if routing.get("model"):
                    kwargs["model"] = routing["model"]
                elif routing.get("provider"):
                    # No model specified in tier — use provider's default model
                    prov_cfg = LLMService._get_provider_config(routing["provider"])
                    if prov_cfg and prov_cfg.get("model_name"):
                        kwargs["model"] = prov_cfg["model_name"]

        # Enforce rate limit
        if tenant_id and config.get("rate_limit_per_hour"):
            calls = _usage.calls_in_last_hour(tenant_id)
            if calls >= config["rate_limit_per_hour"]:
                raise RuntimeError(
                    f"Rate limit exceeded: {calls}/{config['rate_limit_per_hour']} "
                    f"calls in the last hour"
                )

        # Enforce token budget
        if tenant_id and config.get("token_budget_per_tenant"):
            used = _usage.tokens_used(tenant_id)
            if used >= config["token_budget_per_tenant"]:
                raise RuntimeError(
                    f"Token budget exhausted: {used}/{config['token_budget_per_tenant']}"
                )

        provider = LLMService._get_provider(config)

        # Debug log: capture every LLM call for troubleshooting
        debug_entry = {
            "ts": datetime.utcnow().isoformat() if 'datetime' in dir() else __import__('datetime').datetime.utcnow().isoformat(),
            "provider": config.get("provider"),
            "model": kwargs.get("model", config.get("model_name", "")),
            "feature": feature,
            "tenant_id": tenant_id,
            "msg_count": len(messages),
            "system_prompt_len": len(messages[0]["content"]) if messages and messages[0]["role"] == "system" else 0,
            "user_prompt_len": sum(len(m["content"]) for m in messages if m["role"] == "user"),
        }

        # Apply prompt adapter based on model family (CLAUDE.md rule #14)
        try:
            from app.masri.prompt_adapters import get_adapter
            model_name = kwargs.get("model", config.get("model_name", ""))
            adapter = get_adapter(model_name)
            adapted_messages = []
            for m in messages:
                if m["role"] == "system":
                    adapted_messages.append({"role": "system", "content": adapter.adapt_system(m["content"])})
                else:
                    adapted_messages.append(m)
            messages = adapted_messages
            # Adapt temperature if not explicitly overridden to a non-default value
            if "temperature" in kwargs:
                kwargs["temperature"] = adapter.adapt_temperature(kwargs["temperature"])
        except Exception:
            pass  # Graceful fallback: use original messages if adapter fails

        try:
            result = provider.chat(messages, **kwargs)
            debug_entry["status"] = "ok"
            debug_entry["response_len"] = len(result.get("content", ""))
            debug_entry["tokens"] = result.get("usage", {}).get("total_tokens", 0)
            LLMService._store_debug(debug_entry)
        except Exception as e:
            debug_entry["status"] = "error"
            debug_entry["error"] = str(e)[:300]
            LLMService._store_debug(debug_entry)
            logger.error("LLM call failed (%s/%s): %s", config.get("provider"), feature, e)
            # Try fallback provider if configured
            fallback = LLMService._get_fallback_config(config.get("provider"))
            if fallback:
                try:
                    logger.info("Falling back to %s for %s", fallback.get("provider"), feature)
                    fb_provider = LLMService._get_provider(fallback)
                    result = fb_provider.chat(messages, **kwargs)
                    result["fallback"] = True
                    result["original_provider"] = config.get("provider")
                    if tenant_id:
                        _usage.record(tenant_id, result["usage"]["total_tokens"])
                    # Track fallback cost
                    try:
                        fb_usage = result.get("usage", {})
                        fb_cost = _calculate_cost(
                            fb_usage.get("prompt_tokens", 0),
                            fb_usage.get("completion_tokens", 0),
                            result.get("model", ""),
                            result.get("provider", fallback.get("provider", "")),
                        )
                        result["cost"] = fb_cost
                        LLMService._record_cost(
                            provider=result.get("provider", fallback.get("provider", "")),
                            model=result.get("model", ""),
                            prompt_tokens=fb_usage.get("prompt_tokens", 0),
                            completion_tokens=fb_usage.get("completion_tokens", 0),
                            cost=fb_cost,
                            feature=feature,
                            tenant_id=tenant_id,
                        )
                    except Exception:
                        pass
                    return result
                except Exception as e2:
                    logger.error("Fallback also failed (%s): %s", fallback.get("provider"), e2)
            raise RuntimeError(f"LLM call failed for provider {config.get('provider', 'unknown')}. Check API key and model configuration.") from e

        # Track usage
        if tenant_id:
            _usage.record(tenant_id, result["usage"]["total_tokens"])

        # Track cost
        try:
            usage = result.get("usage", {})
            cost = _calculate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
                result.get("model", kwargs.get("model", config.get("model_name", ""))),
                result.get("provider", config.get("provider", "")),
            )
            result["cost"] = cost
            LLMService._record_cost(
                provider=result.get("provider", config.get("provider", "")),
                model=result.get("model", ""),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                cost=cost,
                feature=feature,
                tenant_id=tenant_id,
            )
        except Exception:
            pass  # Never fail the main call for cost tracking

        return result

    @staticmethod
    def summarise(text: str, tenant_id: str = None, max_length: int = 300) -> str:
        """
        Convenience method: summarise a block of text.

        Returns:
            Summary string.
        """
        from app.masri.prompt_adapters import get_adapter_for_feature
        _adapter = get_adapter_for_feature("summarize")
        messages = [
            {"role": "system", "content": _adapter.adapt_system(
                f"You are a concise summariser. Summarise the following in under {max_length} words."
            )},
            {"role": "user", "content": text},
        ]
        result = LLMService.chat(messages, tenant_id=tenant_id, feature="summarize",
                                 temperature=_adapter.adapt_temperature(0.2))
        return result["content"]

    @staticmethod
    def assess_control(control_description: str, evidence_text: str,
                       tenant_id: str = None) -> dict:
        """
        Assess a compliance control against provided evidence.

        Returns:
            dict with keys: status (compliant/partial/non_compliant/unknown),
                            confidence (0-100), explanation (str),
                            recommendations (list[str])
        """
        from app.masri.prompt_adapters import get_adapter_for_feature
        _adapter = get_adapter_for_feature("control_assess")
        messages = [
            {
                "role": "system",
                "content": _adapter.adapt_system(
                    "You are a compliance assessment assistant. Evaluate whether "
                    "the provided evidence satisfies the control requirement. "
                    f"{_adapter.adapt_json_instruction()} "
                    "Respond with valid JSON containing: "
                    '{"status": "compliant|partial|non_compliant|unknown", '
                    '"confidence": <0-100>, '
                    '"explanation": "<brief explanation>", '
                    '"recommendations": ["<action items>"]}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Control Requirement\n{control_description}\n\n"
                    f"## Evidence\n{evidence_text}"
                ),
            },
        ]

        result = LLMService.chat(messages, tenant_id=tenant_id, feature="control_assess",
                                 temperature=_adapter.adapt_temperature(0.1))
        content = result["content"].strip()

        # Try to parse JSON from the response
        try:
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            parsed = {
                "status": "unknown",
                "confidence": 0,
                "explanation": content,
                "recommendations": [],
            }

        return parsed

    @staticmethod
    def generate_policy_draft(framework: str, control_ref: str,
                              organisation_context: str = "",
                              tenant_id: str = None) -> str:
        """
        Generate a policy draft for a given control.

        Returns:
            Markdown-formatted policy text.
        """
        from app.masri.prompt_adapters import get_adapter_for_feature
        _adapter = get_adapter_for_feature("policy_draft")
        messages = [
            {
                "role": "system",
                "content": _adapter.adapt_system(
                    "You are a compliance policy writer. Generate a clear, "
                    "professional policy document in Markdown format for the "
                    "given compliance control. Include sections: Purpose, Scope, "
                    "Policy Statement, Responsibilities, and Review Schedule."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Framework: {framework}\n"
                    f"Control reference: {control_ref}\n"
                    f"Organisation context: {organisation_context or 'General'}"
                ),
            },
        ]

        result = LLMService.chat(
            messages, tenant_id=tenant_id, feature="policy_draft",
            temperature=_adapter.adapt_temperature(0.4),
            max_tokens=_adapter.adapt_max_tokens(2048),
        )
        return result["content"]

    @staticmethod
    def get_usage(tenant_id: str) -> dict:
        """Return current usage stats for a tenant."""
        return {
            "tokens_used": _usage.tokens_used(tenant_id),
            "calls_last_hour": _usage.calls_in_last_hour(tenant_id),
        }


# ---------------------------------------------------------------------------
# Provider billing API clients
# ---------------------------------------------------------------------------

class AnthropicBillingClient:
    """Fetch real usage & cost data from Anthropic's Admin API.

    Requires an Admin API key (sk-ant-admin...) stored in ConfigStore
    or the regular Anthropic API key if it happens to be an admin key.
    """

    BASE_URL = "https://api.anthropic.com"

    @staticmethod
    def _get_admin_key() -> str:
        """Retrieve the Anthropic admin API key.

        Priority: ConfigStore("anthropic_admin_key") > regular Anthropic provider key.
        """
        try:
            from app.models import ConfigStore
            from app.masri.settings_service import decrypt_value
            rec = ConfigStore.find("anthropic_admin_key")
            if rec and rec.value:
                return decrypt_value(rec.value)
        except Exception:
            pass
        # Fallback: try the regular Anthropic provider key
        try:
            config = LLMService._get_provider_config("anthropic")
            if config and config.get("api_key", "").startswith("sk-ant-admin"):
                return config["api_key"]
        except Exception:
            pass
        return ""

    @staticmethod
    def fetch_cost_report(starting_at: str, ending_at: str = None,
                          group_by: list = None) -> dict:
        """Fetch cost report from Anthropic Admin API.

        Args:
            starting_at: RFC 3339 timestamp (e.g. "2026-04-01T00:00:00Z")
            ending_at: RFC 3339 timestamp (optional, defaults to now)
            group_by: list of "workspace_id" and/or "description"

        Returns:
            dict with cost report data or error
        """
        import requests as req

        admin_key = AnthropicBillingClient._get_admin_key()
        if not admin_key:
            return {"error": "No Anthropic admin API key configured"}

        params = {"starting_at": starting_at, "bucket_width": "1d"}
        if ending_at:
            params["ending_at"] = ending_at
        if group_by:
            for g in group_by:
                params.setdefault("group_by[]", [])
                if isinstance(params["group_by[]"], list):
                    params["group_by[]"].append(g)
                else:
                    params["group_by[]"] = [params["group_by[]"], g]

        headers = {
            "x-api-key": admin_key,
            "anthropic-version": "2023-06-01",
        }

        try:
            resp = req.get(
                f"{AnthropicBillingClient.BASE_URL}/v1/organizations/cost_report",
                params=params, headers=headers, timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Anthropic API returned {resp.status_code}", "detail": resp.text[:500]}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def save_admin_key(admin_key: str):
        """Save the Anthropic admin API key (encrypted)."""
        from app.models import ConfigStore
        from app.masri.settings_service import encrypt_value
        from app import db
        ConfigStore.upsert("anthropic_admin_key", encrypt_value(admin_key))
        db.session.commit()

    @staticmethod
    def fetch_usage_report(starting_at: str, ending_at: str = None,
                           group_by: list = None, bucket_width: str = "1d") -> dict:
        """Fetch usage report from Anthropic Admin API.

        Args:
            starting_at: RFC 3339 timestamp
            ending_at: RFC 3339 timestamp (optional)
            group_by: list of grouping dimensions (model, workspace_id, etc.)
            bucket_width: "1m", "1h", or "1d"

        Returns:
            dict with usage report data or error
        """
        import requests as req

        admin_key = AnthropicBillingClient._get_admin_key()
        if not admin_key:
            return {"error": "No Anthropic admin API key configured"}

        params = {"starting_at": starting_at, "bucket_width": bucket_width}
        if ending_at:
            params["ending_at"] = ending_at
        if group_by:
            for g in group_by:
                params.setdefault("group_by[]", [])
                if isinstance(params["group_by[]"], list):
                    params["group_by[]"].append(g)
                else:
                    params["group_by[]"] = [params["group_by[]"], g]

        headers = {
            "x-api-key": admin_key,
            "anthropic-version": "2023-06-01",
        }

        try:
            resp = req.get(
                f"{AnthropicBillingClient.BASE_URL}/v1/organizations/usage_report/messages",
                params=params, headers=headers, timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Anthropic API returned {resp.status_code}", "detail": resp.text[:500]}
        except Exception as e:
            return {"error": str(e)}


class TogetherAIPricingClient:
    """Fetch live model pricing from Together AI's /v1/models endpoint.

    Together AI's models endpoint returns pricing data per model.
    We cache this in ConfigStore and refresh daily.
    """

    MODELS_URL = "https://api.together.xyz/v1/models"
    CACHE_KEY = "together_model_pricing"
    CACHE_TTL_HOURS = 24

    @staticmethod
    def _get_api_key() -> str:
        """Get the Together AI API key from config."""
        try:
            config = LLMService._get_provider_config("together")
            if config and config.get("api_key"):
                return config["api_key"]
            config = LLMService._get_provider_config("together_ai")
            if config and config.get("api_key"):
                return config["api_key"]
        except Exception:
            pass
        import os
        return os.environ.get("TOGETHER_API_KEY", "")

    @staticmethod
    def fetch_and_cache_pricing() -> dict:
        """Fetch model pricing from Together AI API and cache it.

        Returns dict of {model_id: {"input": price_per_1M, "output": price_per_1M}}
        """
        import requests as req

        api_key = TogetherAIPricingClient._get_api_key()
        if not api_key:
            return {"error": "No Together AI API key configured"}

        try:
            resp = req.get(
                TogetherAIPricingClient.MODELS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            if resp.status_code != 200:
                return {"error": f"Together API returned {resp.status_code}"}

            models = resp.json()
            pricing = {}

            for model in models:
                model_id = model.get("id", "")
                if not model_id:
                    continue
                # Together AI returns pricing in different formats:
                # Some have "pricing" dict, some have separate fields
                price_data = model.get("pricing", {})
                if isinstance(price_data, dict):
                    input_price = price_data.get("input", price_data.get("base", 0))
                    output_price = price_data.get("output", price_data.get("base", input_price))
                    if input_price or output_price:
                        pricing[model_id] = {
                            "input": float(input_price),
                            "output": float(output_price),
                        }

            # Cache to Redis (primary, 24h TTL) + ConfigStore (persistent fallback)
            if pricing:
                cache_data = {
                    "pricing": pricing,
                    "_fetched": datetime.utcnow().isoformat(),
                    "_model_count": len(pricing),
                }
                # Redis cache — 24 hours
                c = _get_cache()
                if c:
                    try:
                        c.set("together_pricing", cache_data,
                              timeout=TogetherAIPricingClient.CACHE_TTL_HOURS * 3600)
                    except Exception:
                        pass
                # ConfigStore — persistent fallback
                try:
                    from app.models import ConfigStore
                    from app import db
                    ConfigStore.upsert(TogetherAIPricingClient.CACHE_KEY,
                                       json.dumps(cache_data, default=str))
                    db.session.commit()
                except Exception:
                    pass

                # Also update the in-memory MODEL_PRICING dict
                for model_id, prices in pricing.items():
                    MODEL_PRICING[model_id] = prices

                logger.info("Cached Together AI pricing for %d models", len(pricing))

            return {"models": len(pricing), "pricing": pricing}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_cached_pricing() -> dict:
        """Get cached pricing from Redis → ConfigStore → fresh fetch."""
        # 1. Try Redis cache (fastest)
        c = _get_cache()
        if c:
            try:
                cached = c.get("together_pricing")
                if cached is not None:
                    for model_id, prices in cached.get("pricing", {}).items():
                        MODEL_PRICING[model_id] = prices
                    return cached
            except Exception:
                pass
        # 2. Try ConfigStore (persistent)
        try:
            from app.models import ConfigStore
            rec = ConfigStore.find(TogetherAIPricingClient.CACHE_KEY)
            if rec and rec.value:
                data = json.loads(rec.value)
                fetched = data.get("_fetched", "")
                if fetched:
                    fetched_dt = datetime.fromisoformat(fetched)
                    age_hours = (datetime.utcnow() - fetched_dt).total_seconds() / 3600
                    if age_hours < TogetherAIPricingClient.CACHE_TTL_HOURS:
                        # Load into memory + backfill Redis
                        for model_id, prices in data.get("pricing", {}).items():
                            MODEL_PRICING[model_id] = prices
                        if c:
                            try:
                                remaining_s = int((TogetherAIPricingClient.CACHE_TTL_HOURS - age_hours) * 3600)
                                c.set("together_pricing", data, timeout=max(remaining_s, 60))
                            except Exception:
                                pass
                        return data
                    logger.info("Together AI pricing cache stale (%.1fh), refreshing", age_hours)
        except Exception:
            pass
        # 3. No cache or stale — fetch fresh
        result = TogetherAIPricingClient.fetch_and_cache_pricing()
        if "error" not in result:
            return {"pricing": result.get("pricing", {}), "_fetched": datetime.utcnow().isoformat(), "_model_count": result.get("models", 0)}
        return result
