"""
Masri Digital Compliance Platform — LLM Service Layer

Multi-provider LLM abstraction supporting OpenAI, Anthropic, Azure OpenAI,
and Ollama.  All calls go through a single ``LLMService`` façade that reads
configuration from the database (``SettingsLLM``) and enforces per-tenant
token budgets and rate limits.
"""

import json
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


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
        Load the active LLM configuration from the database.

        Returns:
            dict with provider, model_name, api_key (decrypted),
            azure_endpoint, azure_deployment, ollama_base_url,
            token_budget_per_tenant, rate_limit_per_hour.
        """
        from app.masri.settings_service import SettingsService

        llm = SettingsService.get_active_llm_config()
        if llm is None:
            return None

        config = {
            "provider": llm.provider,
            "model_name": llm.model_name,
            "azure_endpoint": llm.azure_endpoint,
            "azure_deployment": llm.azure_deployment,
            "ollama_base_url": llm.ollama_base_url,
            "token_budget_per_tenant": llm.token_budget_per_tenant,
            "rate_limit_per_hour": llm.rate_limit_per_hour,
        }

        # Decrypt API key
        if llm.api_key_enc:
            try:
                config["api_key"] = llm.get_api_key()
            except Exception:
                logger.warning("Failed to decrypt LLM API key")
                config["api_key"] = ""
        else:
            config["api_key"] = ""

        return config

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

        Returns:
            dict with 'provider' and 'model' keys, or None for default.
        """
        try:
            from app.models import ConfigStore
            import json
            record = ConfigStore.find("llm_feature_models")
            if record and record.value:
                data = json.loads(record.value)
                if data.get("sameForAll", True):
                    # Check if a specific "same for all" provider+model is set
                    tiers = data.get("tiers", {})
                    same_provider = tiers.get("_sameProvider")
                    same_model = tiers.get("_sameModel")
                    if same_provider:
                        return {"provider": same_provider, "model": same_model or ""}
                    return None

                # Check tier-based routing first
                tiers = data.get("tiers", {})
                if tiers:
                    tier = LLMService.FEATURE_TIERS.get(feature, "standard")
                    tier_config = tiers.get(tier)
                    if tier_config and isinstance(tier_config, dict) and tier_config.get("provider"):
                        return tier_config

                # Fallback: direct per-feature override (legacy)
                routing = data.get("models", {}).get(feature)
                if routing and isinstance(routing, dict):
                    return routing
                if routing and isinstance(routing, str):
                    return {"model": routing}
        except Exception:
            pass
        return None

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
        """
        try:
            from app.models import ConfigStore
            import json
            record = ConfigStore.find("llm_additional_providers")
            if record and record.value:
                extras = json.loads(record.value)
                config = extras.get(provider_key, {})
                if not config:
                    return None
                # Decrypt API key if present
                if config.get("api_key_enc"):
                    from app.masri.settings_service import decrypt_value
                    config["api_key"] = decrypt_value(config["api_key_enc"])
                    del config["api_key_enc"]
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

        try:
            result = provider.chat(messages, **kwargs)
        except Exception as e:
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
                    return result
                except Exception as e2:
                    logger.error("Fallback also failed (%s): %s", fallback.get("provider"), e2)
            raise RuntimeError(f"LLM call failed for provider {config.get('provider', 'unknown')}. Check API key and model configuration.") from e

        # Track usage
        if tenant_id:
            _usage.record(tenant_id, result["usage"]["total_tokens"])

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
