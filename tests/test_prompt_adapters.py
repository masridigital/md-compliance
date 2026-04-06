"""Tests for the prompt adapter layer.

These tests import prompt_adapters directly (no Flask app needed).
"""
import sys
import os
import pytest

# Add project root to path so we can import the module directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Direct import of the module (avoids app/__init__.py Flask dependency)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "prompt_adapters",
    os.path.join(os.path.dirname(__file__), '..', 'app', 'masri', 'prompt_adapters.py')
)
prompt_adapters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prompt_adapters)

get_adapter = prompt_adapters.get_adapter
ClaudeAdapter = prompt_adapters.ClaudeAdapter
DeepSeekAdapter = prompt_adapters.DeepSeekAdapter
LlamaAdapter = prompt_adapters.LlamaAdapter
KimiAdapter = prompt_adapters.KimiAdapter
GemmaAdapter = prompt_adapters.GemmaAdapter
QwenAdapter = prompt_adapters.QwenAdapter
_BaseAdapter = prompt_adapters._BaseAdapter


class TestGetAdapter:
    """Test model name detection and adapter selection."""

    def test_claude_detection(self):
        assert isinstance(get_adapter("claude-sonnet-4-20250514"), ClaudeAdapter)

    def test_claude_opus_detection(self):
        assert isinstance(get_adapter("claude-opus-4-20250514"), ClaudeAdapter)

    def test_deepseek_detection(self):
        assert isinstance(get_adapter("deepseek-chat"), DeepSeekAdapter)

    def test_llama_detection(self):
        assert isinstance(get_adapter("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"), LlamaAdapter)

    def test_llama_short_name(self):
        assert isinstance(get_adapter("llama-3.1-8b"), LlamaAdapter)

    def test_kimi_detection(self):
        assert isinstance(get_adapter("kimi-v1"), KimiAdapter)

    def test_moonshot_detection(self):
        assert isinstance(get_adapter("moonshot-v1-8k"), KimiAdapter)

    def test_gemma_detection(self):
        assert isinstance(get_adapter("gemma-2-9b"), GemmaAdapter)

    def test_qwen_detection(self):
        assert isinstance(get_adapter("qwen-2.5-72b"), QwenAdapter)

    def test_unknown_model_returns_default(self):
        assert isinstance(get_adapter("some-unknown-model-v3"), _BaseAdapter)

    def test_none_model_returns_default(self):
        assert isinstance(get_adapter(None), _BaseAdapter)

    def test_empty_string_returns_default(self):
        assert isinstance(get_adapter(""), _BaseAdapter)

    def test_case_insensitive(self):
        assert isinstance(get_adapter("CLAUDE-SONNET-4"), ClaudeAdapter)


class TestAdapterBehavior:
    """Test that adapters modify prompts/params correctly."""

    def test_default_adapter_passthrough(self):
        a = _BaseAdapter()
        assert a.adapt_system("test") == "test"
        assert a.adapt_chunk_size(10) == 10
        assert a.adapt_temperature(0.3) == 0.3
        assert a.adapt_max_tokens(3000) == 3000

    def test_claude_increases_chunk_size(self):
        assert ClaudeAdapter().adapt_chunk_size(10) == 15

    def test_deepseek_caps_temperature(self):
        a = DeepSeekAdapter()
        assert a.adapt_temperature(0.5) == 0.1
        assert a.adapt_temperature(0.05) == 0.05

    def test_gemma_reduces_chunk_and_tokens(self):
        a = GemmaAdapter()
        assert a.adapt_chunk_size(10) == 5
        assert a.adapt_max_tokens(4000) == 2048
        assert a.adapt_temperature(0.3) == 0.1

    def test_claude_adds_xml_tags(self):
        result = ClaudeAdapter().adapt_system("Base prompt")
        assert "<output_format>" in result
        assert "Base prompt" in result

    def test_deepseek_adds_strict_json(self):
        result = DeepSeekAdapter().adapt_system("Base prompt")
        assert "ONLY a single JSON object" in result

    def test_llama_chunk_size(self):
        assert LlamaAdapter().adapt_chunk_size(15) == 10

    def test_qwen_adds_schema_example(self):
        result = QwenAdapter().adapt_system("Base prompt")
        assert "mappings" in result
        assert "project_control_id" in result
