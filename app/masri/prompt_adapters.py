"""
Prompt Adapter Layer — adapts LLM prompts per model family.

Different model families perform best with different prompt strategies:
- Claude: XML tags, evidence citations, conservative conclusions
- DeepSeek: Single objective, explicit JSON schema, low temperature
- Llama: JSON-only emphasis, no explanation
- Qwen: Structured examples, good JSON output
- Gemma: Extractive only, small chunks
- Kimi/Moonshot: Broad context, rigid output format
- Default: Current behavior (works for GPT-4, Mistral, etc.)

Usage:
    from app.masri.prompt_adapters import get_adapter
    adapter = get_adapter(model_name)
    system = adapter.adapt_system(base_prompt)
    chunk_size = adapter.adapt_chunk_size(default=10)
    temperature = adapter.adapt_temperature(default=0.3)
"""

import logging
import re

logger = logging.getLogger(__name__)


class BaseAdapter:
    """Default adapter — works for GPT-4, Mistral, and unknown models."""

    name = "default"

    def adapt_system(self, prompt):
        """Wrap or modify the system prompt for this model family."""
        return prompt

    def adapt_chunk_size(self, default=10):
        """Return optimal chunk size for this model."""
        return default

    def adapt_temperature(self, default=0.3):
        """Return capped temperature for this model."""
        return default

    def adapt_max_tokens(self, default=4096):
        """Return max tokens for this model."""
        return default

    def adapt_json_instruction(self):
        """Return model-specific JSON output instruction."""
        return "You MUST respond with ONLY valid JSON. No explanation, no markdown, no code fences."


class ClaudeAdapter(BaseAdapter):
    """Claude (Anthropic) — XML tags, evidence citations, conservative conclusions."""

    name = "claude"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "<output_format>\n"
            "Respond with ONLY valid JSON. No explanation outside the JSON.\n"
            "For each mapping, cite specific evidence from the data.\n"
            "Be conservative: only mark 'compliant' when data clearly confirms it.\n"
            "</output_format>"
        )

    def adapt_chunk_size(self, default=10):
        return 15  # Claude handles larger context well

    def adapt_json_instruction(self):
        return (
            "<instructions>\n"
            "Return ONLY valid JSON. No markdown, no explanation.\n"
            "Cite specific data points as evidence for each mapping.\n"
            "</instructions>"
        )


class DeepSeekAdapter(BaseAdapter):
    """DeepSeek — single objective, explicit JSON schema, low temperature."""

    name = "deepseek"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "CRITICAL: Your ONLY task is to output valid JSON. "
            "Do NOT include any text before or after the JSON object. "
            "Do NOT use markdown code fences. "
            "Output MUST start with {{ and end with }}."
        )

    def adapt_chunk_size(self, default=10):
        return 8  # Smaller chunks for reliability

    def adapt_temperature(self, default=0.3):
        return min(default, 0.1)  # Force low temperature

    def adapt_json_instruction(self):
        return (
            "Output ONLY a JSON object. Start with { and end with }. "
            "No markdown. No explanation. No code fences."
        )


class LlamaAdapter(BaseAdapter):
    """Llama (Meta) — JSON-only emphasis, no explanation."""

    name = "llama"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "[IMPORTANT] You are a JSON-output-only assistant. "
            "Return ONLY the JSON object. No explanation, no preamble, no markdown formatting. "
            "Your response must be parseable by json.loads() directly."
        )

    def adapt_chunk_size(self, default=10):
        return 10

    def adapt_json_instruction(self):
        return (
            "Return ONLY valid JSON. No markdown code blocks. "
            "No text before or after the JSON. Response must start with {."
        )


class QwenAdapter(BaseAdapter):
    """Qwen — structured examples, good JSON output."""

    name = "qwen"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "Always respond in valid JSON format. "
            "Follow the exact schema specified in the prompt. "
            "Do not add extra fields or change field names."
        )

    def adapt_chunk_size(self, default=10):
        return 10

    def adapt_json_instruction(self):
        return "Respond with valid JSON only. Match the exact schema specified."


class GemmaAdapter(BaseAdapter):
    """Gemma (Google) — extractive only, small chunks, low temperature."""

    name = "gemma"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "Extract information directly from the provided data. "
            "Do not infer or speculate beyond what is explicitly stated. "
            "Output valid JSON only."
        )

    def adapt_chunk_size(self, default=10):
        return 5  # Small context window

    def adapt_temperature(self, default=0.3):
        return min(default, 0.1)

    def adapt_max_tokens(self, default=4096):
        return min(default, 2048)

    def adapt_json_instruction(self):
        return "Output valid JSON only. Extract from data, do not speculate."


class KimiAdapter(BaseAdapter):
    """Kimi/Moonshot — broad context, rigid output format."""

    name = "kimi"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "You have a large context window. Use all provided data. "
            "Output MUST be valid JSON following the exact format specified. "
            "Do not add commentary or explanation outside the JSON."
        )

    def adapt_chunk_size(self, default=10):
        return 12  # Can handle slightly larger chunks

    def adapt_json_instruction(self):
        return (
            "Return valid JSON only. Follow the exact output format specified. "
            "No commentary outside the JSON object."
        )


# Model detection patterns — order matters (first match wins)
_ADAPTER_PATTERNS = [
    (re.compile(r"claude", re.I), ClaudeAdapter),
    (re.compile(r"deepseek", re.I), DeepSeekAdapter),
    (re.compile(r"llama|meta-llama", re.I), LlamaAdapter),
    (re.compile(r"qwen", re.I), QwenAdapter),
    (re.compile(r"gemma", re.I), GemmaAdapter),
    (re.compile(r"kimi|moonshot", re.I), KimiAdapter),
]

# Cache adapters by model name
_adapter_cache = {}


def get_adapter(model_name):
    """Get the appropriate prompt adapter for a model name.

    Args:
        model_name: Model identifier (e.g., "claude-sonnet-4-20250514",
                     "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                     "deepseek-chat", "gpt-4o")

    Returns:
        Adapter instance for the model family.
    """
    if not model_name:
        return BaseAdapter()

    if model_name in _adapter_cache:
        return _adapter_cache[model_name]

    for pattern, adapter_cls in _ADAPTER_PATTERNS:
        if pattern.search(model_name):
            adapter = adapter_cls()
            _adapter_cache[model_name] = adapter
            logger.debug("Prompt adapter for %s: %s", model_name, adapter.name)
            return adapter

    adapter = BaseAdapter()
    _adapter_cache[model_name] = adapter
    return adapter


def get_adapter_for_feature(feature):
    """Get the adapter for the model assigned to a specific feature tier.

    Resolves feature → tier → provider+model → adapter.
    """
    try:
        from app.masri.llm_service import LLMService
        routing = LLMService.get_feature_routing(feature)
        if routing and routing.get("model"):
            return get_adapter(routing["model"])
        # Fallback: use the primary model
        config = LLMService._get_config()
        if config and config.get("model_name"):
            return get_adapter(config["model_name"])
    except Exception:
        pass
    return BaseAdapter()
