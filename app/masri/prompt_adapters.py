"""
Masri Digital Compliance Platform — Prompt Adapter Layer

Model-family-specific adapters that customize LLM prompts, chunk sizes,
temperatures, and output instructions for optimal results per model.

Usage:
    from app.masri.prompt_adapters import get_adapter
    adapter = get_adapter(model_name)
    system = adapter.adapt_system(base_system_prompt)
    chunk_size = adapter.adapt_chunk_size(default_chunk_size)
    temperature = adapter.adapt_temperature(default_temperature)
"""

import logging

logger = logging.getLogger(__name__)


class _BaseAdapter:
    """Default adapter — current behavior, works for most models."""

    name = "default"

    def adapt_system(self, prompt):
        """Wrap or modify the system prompt for this model family."""
        return prompt

    def adapt_chunk_size(self, default):
        """Return optimal chunk size for this model."""
        return default

    def adapt_temperature(self, default):
        """Return optimal temperature for this model."""
        return default

    def adapt_json_instruction(self):
        """Return model-specific JSON output instruction to append."""
        return "Respond with ONLY valid JSON. No explanation, no markdown."

    def adapt_max_tokens(self, default):
        """Return optimal max_tokens for this model."""
        return default


class ClaudeAdapter(_BaseAdapter):
    """Anthropic Claude models — excellent at structured output with XML tags."""

    name = "claude"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "<output_format>\n"
            "Return ONLY valid JSON. Use evidence citations from the data provided. "
            "Be conservative in compliance conclusions — if evidence is ambiguous, "
            "mark as 'partial' rather than 'compliant'. Never fabricate evidence.\n"
            "</output_format>"
        )

    def adapt_chunk_size(self, default):
        return 15

    def adapt_json_instruction(self):
        return (
            "<instructions>\n"
            "Return ONLY valid JSON matching the schema above. "
            "No explanation outside the JSON object. "
            "Cite specific data points as evidence.\n"
            "</instructions>"
        )


class DeepSeekAdapter(_BaseAdapter):
    """DeepSeek models — good at reasoning but need strict JSON constraints."""

    name = "deepseek"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "CRITICAL: You must output ONLY a single JSON object. "
            "Do not include any text before or after the JSON. "
            "Do not use markdown code fences. "
            "Focus on ONE objective: mapping controls to compliance status."
        )

    def adapt_chunk_size(self, default):
        return 8

    def adapt_temperature(self, default):
        return min(default, 0.1)

    def adapt_json_instruction(self):
        return (
            "OUTPUT RULES: Return exactly one JSON object. "
            "No text, no explanation, no code blocks. Just JSON."
        )


class LlamaAdapter(_BaseAdapter):
    """Meta Llama models — strong general purpose, needs JSON emphasis."""

    name = "llama"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "IMPORTANT: Your entire response must be valid JSON only. "
            "Do not include any explanation, commentary, or markdown formatting. "
            "Start your response with {{ and end with }}."
        )

    def adapt_chunk_size(self, default):
        return 10

    def adapt_json_instruction(self):
        return (
            "Your response must be pure JSON. Start with { and end with }. "
            "No other text allowed."
        )


class KimiAdapter(_BaseAdapter):
    """Moonshot/Kimi models — good with broad context, need rigid output format."""

    name = "kimi"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "Use ALL available context to inform your analysis. "
            "Cross-reference different data points to build a complete picture. "
            "Output must be strictly valid JSON — no explanation text."
        )

    def adapt_chunk_size(self, default):
        return 12

    def adapt_json_instruction(self):
        return (
            "Return valid JSON only. Cross-reference all available data sources. "
            "Be thorough but output only the JSON structure specified."
        )


class GemmaAdapter(_BaseAdapter):
    """Google Gemma models — smaller, best for extractive tasks only."""

    name = "gemma"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "EXTRACTIVE TASK ONLY: Look at the data provided and extract "
            "relevant findings for each control. Do not infer or cross-reference "
            "across data sources. Map only what is directly stated in the data. "
            "Output valid JSON only."
        )

    def adapt_chunk_size(self, default):
        return 5

    def adapt_temperature(self, default):
        return min(default, 0.1)

    def adapt_max_tokens(self, default):
        return min(default, 2048)

    def adapt_json_instruction(self):
        return (
            "Extract findings directly from the data. Do not infer. "
            "Return valid JSON only. No cross-source analysis."
        )


class QwenAdapter(_BaseAdapter):
    """Alibaba Qwen models — good JSON output, benefits from structured examples."""

    name = "qwen"

    def adapt_system(self, prompt):
        return (
            f"{prompt}\n\n"
            "Follow this exact JSON schema for your response:\n"
            '{{"mappings": [{{"project_control_id": "ID", "notes": "Finding details", '
            '"status": "compliant|partial|non_compliant"}}], '
            '"risks": [{{"title": "Risk title", "description": "Details", '
            '"severity": "critical|high|medium|low"}}]}}\n\n'
            "Respond with ONLY the JSON object. No other text."
        )

    def adapt_chunk_size(self, default):
        return 10

    def adapt_json_instruction(self):
        return (
            "Follow the JSON schema exactly. Include all required fields. "
            "Return valid JSON only — no markdown, no explanation."
        )


# Adapter registry — detection patterns mapped to adapter classes
_ADAPTERS = [
    (["claude"], ClaudeAdapter),
    (["deepseek"], DeepSeekAdapter),
    (["llama", "meta-llama"], LlamaAdapter),
    (["kimi", "moonshot"], KimiAdapter),
    (["gemma"], GemmaAdapter),
    (["qwen"], QwenAdapter),
]


def get_adapter(model_name):
    """Get the appropriate prompt adapter for a model name.

    Args:
        model_name: The model identifier string (e.g., "claude-sonnet-4-20250514",
                    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "deepseek-chat")

    Returns:
        An adapter instance for the detected model family.
    """
    if not model_name:
        return _BaseAdapter()

    model_lower = model_name.lower()
    for patterns, adapter_cls in _ADAPTERS:
        for pattern in patterns:
            if pattern in model_lower:
                return adapter_cls()

    return _BaseAdapter()
