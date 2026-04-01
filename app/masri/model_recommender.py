"""
Masri Digital Compliance Platform — AI Model Recommendation Engine

Weekly job that researches available models across configured providers
and recommends the best model for each LLM tier based on:
- Cost efficiency (tokens per dollar)
- JSON output reliability (critical for compliance mapping)
- Reasoning capability (for analysis and policy tiers)
- Speed (for high-volume extraction tiers)

Runs as a scheduler task every 7 days. Uses a web-capable or advanced
LLM to evaluate model options and update recommendations.

Usage::

    from app.masri.model_recommender import refresh_model_recommendations
    recommendations = refresh_model_recommendations(app)
"""

import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Known model characteristics (fallback when LLM research unavailable)
KNOWN_MODELS = {
    "together_ai": {
        "meta-llama/Llama-3.3-70B-Instruct-Turbo": {
            "tier_fit": ["extraction", "mapping"],
            "strengths": "Fast, cheap, reliable JSON, good instruction following",
            "cost_tier": "low",
            "speed": "fast",
        },
        "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": {
            "tier_fit": ["mapping", "analysis"],
            "strengths": "Largest open model, strong reasoning, good for complex mapping",
            "cost_tier": "medium",
            "speed": "medium",
        },
        "Qwen/Qwen2.5-72B-Instruct-Turbo": {
            "tier_fit": ["extraction", "mapping"],
            "strengths": "Strong multilingual, good JSON, fast",
            "cost_tier": "low",
            "speed": "fast",
        },
        "deepseek-ai/DeepSeek-V3": {
            "tier_fit": ["mapping", "analysis"],
            "strengths": "Strong reasoning, cost-effective for complex tasks",
            "cost_tier": "low",
            "speed": "medium",
        },
        "moonshotai/Kimi-K2.5": {
            "tier_fit": ["extraction", "mapping"],
            "strengths": "Fast, good at structured output",
            "cost_tier": "low",
            "speed": "fast",
        },
    },
    "anthropic": {
        "claude-sonnet-4-20250514": {
            "tier_fit": ["analysis", "advanced"],
            "strengths": "Strong reasoning, excellent compliance analysis, reliable JSON",
            "cost_tier": "medium",
            "speed": "medium",
        },
        "claude-haiku-4-5-20251001": {
            "tier_fit": ["extraction", "mapping"],
            "strengths": "Fast, cheap, good for structured extraction",
            "cost_tier": "low",
            "speed": "fast",
        },
        "claude-opus-4-6": {
            "tier_fit": ["advanced"],
            "strengths": "Best reasoning, nuanced policy writing, deep analysis",
            "cost_tier": "high",
            "speed": "slow",
        },
    },
    "openai": {
        "gpt-4o": {
            "tier_fit": ["analysis", "advanced"],
            "strengths": "Strong reasoning, reliable JSON, good for compliance",
            "cost_tier": "medium",
            "speed": "medium",
        },
        "gpt-4o-mini": {
            "tier_fit": ["extraction", "mapping"],
            "strengths": "Fast, cheap, reliable JSON output",
            "cost_tier": "low",
            "speed": "fast",
        },
        "o3-mini": {
            "tier_fit": ["analysis", "advanced"],
            "strengths": "Strong reasoning at lower cost than full o3",
            "cost_tier": "medium",
            "speed": "medium",
        },
    },
}

TIER_REQUIREMENTS = {
    "extraction": {
        "priority": ["speed", "cost"],
        "needs": "Fast structured extraction, JSON parsing, data formatting. High volume — cost matters most.",
        "ideal": "Cheapest fast model with reliable JSON output",
    },
    "mapping": {
        "priority": ["json_reliability", "domain_knowledge"],
        "needs": "Map security findings to compliance controls. Must produce valid JSON with correct control IDs.",
        "ideal": "Model with strong instruction following and JSON reliability",
    },
    "analysis": {
        "priority": ["reasoning", "specificity"],
        "needs": "Generate specific remediation recommendations. Must reference actual findings by name.",
        "ideal": "Model with strong reasoning that can cite specific data points",
    },
    "advanced": {
        "priority": ["reasoning", "writing_quality"],
        "needs": "Policy drafting, risk narratives, user/device risk profiles. Long-form nuanced output.",
        "ideal": "Best available reasoning model — quality over cost",
    },
}


def refresh_model_recommendations(app):
    """Refresh model recommendations based on configured providers.

    1. Check which providers have API keys
    2. Fetch available model lists
    3. Use LLM to evaluate and recommend
    4. Store in ConfigStore

    Returns:
        dict with recommendations per tier
    """
    with app.app_context():
        from app.models import ConfigStore
        from app.masri.settings_service import SettingsService

        # 1. Gather configured providers and their available models
        configured_providers = {}

        # Primary provider
        try:
            primary = SettingsService.get_active_llm_config()
            if primary and primary.provider:
                configured_providers[primary.provider] = {
                    "is_primary": True,
                    "has_key": bool(primary.api_key_enc),
                    "current_model": primary.model_name,
                    "models": [],
                }
        except Exception:
            pass

        # Additional providers
        try:
            record = ConfigStore.find("llm_additional_providers")
            if record and record.value:
                extras = json.loads(record.value)
                for key, cfg in extras.items():
                    if cfg.get("api_key_enc"):
                        configured_providers[key] = {
                            "is_primary": False,
                            "has_key": True,
                            "current_model": cfg.get("model_name", ""),
                            "models": [],
                        }
        except Exception:
            pass

        if not configured_providers:
            logger.info("No LLM providers configured — skipping model recommendations")
            return None

        # 2. Fetch available models for each provider
        try:
            from app.masri.settings_routes import _fetch_models_for_provider
            for provider_key, info in configured_providers.items():
                if not info["has_key"]:
                    continue
                try:
                    # Get API key
                    api_key = None
                    if info["is_primary"]:
                        try:
                            primary = SettingsService.get_active_llm_config()
                            if primary:
                                api_key = primary.get_api_key()
                        except Exception:
                            pass
                    else:
                        try:
                            record = ConfigStore.find(f"llm_provider_{provider_key}")
                            if record and record.value:
                                cfg = json.loads(record.value)
                                if cfg.get("api_key_enc"):
                                    from app.masri.settings_service import decrypt_value
                                    api_key = decrypt_value(cfg["api_key_enc"])
                        except Exception:
                            pass

                    if api_key:
                        models = _fetch_models_for_provider(provider_key, api_key)
                        info["models"] = models[:50]  # Cap to avoid huge lists
                except Exception as e:
                    logger.debug("Could not fetch models for %s: %s", provider_key, e)
        except Exception:
            pass

        # 3. Generate recommendations from known model characteristics
        recommendations = _generate_recommendations(configured_providers)

        # Store immediately (knowledge-based) so polling finds results fast
        result = {
            "recommendations": recommendations,
            "configured_providers": list(configured_providers.keys()),
            "generated_at": datetime.utcnow().isoformat(),
            "source": "knowledge_base",
        }
        try:
            ConfigStore.upsert("llm_model_recommendations", json.dumps(result, default=str))
        except Exception:
            pass

        # 4. Try to enhance with LLM analysis (if available)
        try:
            from app.masri.llm_service import LLMService
            if LLMService.is_enabled():
                recommendations = _llm_enhanced_recommendations(
                    LLMService, configured_providers, recommendations
                )
                # Update with LLM-enhanced results
                result["recommendations"] = recommendations
                result["generated_at"] = datetime.utcnow().isoformat()
                result["source"] = "ai_enhanced"
                try:
                    ConfigStore.upsert("llm_model_recommendations", json.dumps(result, default=str))
                except Exception:
                    pass
        except Exception as e:
            logger.debug("LLM-enhanced recommendations skipped: %s", e)

        logger.info("Model recommendations updated: %s",
                     {t: r.get("model", "?") for t, r in recommendations.items()})
        return result


def _generate_recommendations(configured_providers):
    """Generate tier recommendations from known model characteristics."""
    recommendations = {}

    # Build pool of available models with characteristics
    available = []
    for provider, info in configured_providers.items():
        known = KNOWN_MODELS.get(provider, {})
        for model_id in info.get("models", []):
            chars = known.get(model_id, {})
            available.append({
                "provider": provider,
                "model": model_id,
                "tier_fit": chars.get("tier_fit", []),
                "strengths": chars.get("strengths", ""),
                "cost_tier": chars.get("cost_tier", "unknown"),
                "speed": chars.get("speed", "unknown"),
                "is_known": bool(chars),
            })

    # Also add known models that are in the provider's list
    for provider, info in configured_providers.items():
        known = KNOWN_MODELS.get(provider, {})
        for model_id, chars in known.items():
            if model_id not in [a["model"] for a in available]:
                if model_id in info.get("models", []) or not info.get("models"):
                    available.append({
                        "provider": provider,
                        "model": model_id,
                        "tier_fit": chars.get("tier_fit", []),
                        "strengths": chars.get("strengths", ""),
                        "cost_tier": chars.get("cost_tier", "unknown"),
                        "speed": chars.get("speed", "unknown"),
                        "is_known": True,
                    })

    # For each tier, find best match
    for tier_id, reqs in TIER_REQUIREMENTS.items():
        best = None
        best_score = -1

        for m in available:
            score = 0
            # Direct tier fit
            if tier_id in m.get("tier_fit", []):
                score += 10

            # Cost priority
            if "cost" in reqs["priority"] or "speed" in reqs["priority"]:
                if m["cost_tier"] == "low":
                    score += 5
                elif m["cost_tier"] == "medium":
                    score += 2

            if "speed" in reqs["priority"]:
                if m["speed"] == "fast":
                    score += 5
                elif m["speed"] == "medium":
                    score += 2

            # Reasoning priority
            if "reasoning" in reqs["priority"] or "writing_quality" in reqs["priority"]:
                if m["cost_tier"] == "high":
                    score += 3  # Usually better reasoning
                if m["cost_tier"] == "medium":
                    score += 5  # Best balance

            # Known model bonus
            if m["is_known"]:
                score += 2

            if score > best_score:
                best_score = score
                best = m

        if best:
            recommendations[tier_id] = {
                "provider": best["provider"],
                "model": best["model"],
                "reason": best.get("strengths", TIER_REQUIREMENTS[tier_id]["ideal"]),
                "score": best_score,
            }
        else:
            # Fallback to first configured provider
            first_provider = list(configured_providers.keys())[0]
            recommendations[tier_id] = {
                "provider": first_provider,
                "model": "",
                "reason": "Default — no specific match found",
                "score": 0,
            }

    return recommendations


def _llm_enhanced_recommendations(LLMService, configured_providers, base_recommendations):
    """Use LLM to select best battle-tested, cost-effective models per tier."""
    # Build context about available models
    provider_info = []
    for provider, info in configured_providers.items():
        model_count = len(info.get("models", []))
        models = info.get("models", [])[:30]
        provider_info.append(
            f"Provider: {provider} ({model_count} models)\n"
            f"Models: {', '.join(models)}"
        )

    try:
        result = LLMService.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI model procurement expert for an enterprise compliance platform. "
                        "Your job is to select the BEST model for each of 4 task tiers.\n\n"
                        "SELECTION CRITERIA (in order of priority):\n"
                        "1. BATTLE-TESTED: Prefer widely-adopted, production-proven models over new/experimental ones. "
                        "Models that have been available for months with proven track records are preferred.\n"
                        "2. BEST VALUE: Best performance per dollar. Don't pick the cheapest if it degrades quality. "
                        "Don't pick the most expensive if a mid-tier model handles the task equally well.\n"
                        "3. TASK FIT: Match model strengths to tier requirements.\n"
                        "4. JSON RELIABILITY: For Tiers 1-2, the model MUST produce clean JSON consistently.\n\n"
                        "TIER DEFINITIONS:\n"
                        "- extraction: High-volume data parsing, structured extraction, summarization. "
                        "Needs: fast, cheap, reliable JSON. Does NOT need strong reasoning.\n"
                        "- mapping: Map security findings to compliance controls. "
                        "Needs: good instruction following, reliable JSON, some domain knowledge.\n"
                        "- analysis: Generate remediation recommendations, gap analysis. "
                        "Needs: strong reasoning, ability to reference specific data points.\n"
                        "- advanced: Policy drafting, risk narratives, complex compliance writing. "
                        "Needs: best reasoning available, nuanced long-form output.\n\n"
                        "IMPORTANT: Only recommend models from the AVAILABLE providers listed below. "
                        "If a provider has no models listed, skip it.\n\n"
                        "Respond with ONLY valid JSON:\n"
                        '{"extraction":{"provider":"...","model":"exact model ID from the list","reason":"1 sentence why"},'
                        '"mapping":{"provider":"...","model":"exact model ID","reason":"..."},'
                        '"analysis":{"provider":"...","model":"exact model ID","reason":"..."},'
                        '"advanced":{"provider":"...","model":"exact model ID","reason":"..."}}'
                    ),
                },
                {
                    "role": "user",
                    "content": "AVAILABLE PROVIDERS AND MODELS:\n\n" + "\n\n".join(provider_info),
                },
            ],
            feature="assist_gaps",  # Tier 3 — needs reasoning
            temperature=0.1,
            max_tokens=800,
        )

        content = result["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        parsed = None
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            bs = content.find("{")
            be = content.rfind("}")
            if bs >= 0 and be > bs:
                try:
                    parsed = json.loads(content[bs:be + 1])
                except Exception:
                    pass

        if parsed:
            # Validate that recommended models are from configured providers
            for tier_id in ["extraction", "mapping", "analysis", "advanced"]:
                if tier_id in parsed:
                    rec = parsed[tier_id]
                    provider = rec.get("provider", "")
                    if provider in configured_providers:
                        base_recommendations[tier_id] = {
                            "provider": provider,
                            "model": rec.get("model", ""),
                            "reason": rec.get("reason", "AI recommended"),
                            "ai_enhanced": True,
                        }

    except Exception as e:
        logger.debug("LLM model recommendation failed: %s", e)

    return base_recommendations


def get_current_recommendations():
    """Get the most recent model recommendations from ConfigStore."""
    try:
        from app.models import ConfigStore
        record = ConfigStore.find("llm_model_recommendations")
        if record and record.value:
            return json.loads(record.value)
    except Exception:
        pass
    return None
