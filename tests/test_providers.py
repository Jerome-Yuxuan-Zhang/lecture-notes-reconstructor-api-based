from __future__ import annotations

import pytest

from lecture_reconstructor.api_client import ApiConfigurationError, OpenAICompatibleClient
from lecture_reconstructor.providers import get_provider


def test_provider_presets_are_openai_compatible() -> None:
    qwen = get_provider("Qwen")
    deepseek = get_provider("DeepSeek")

    assert qwen.base_url.endswith("/compatible-mode/v1")
    assert qwen.model == "qwen3.7-max"
    assert deepseek.base_url == "https://api.deepseek.com"
    assert deepseek.model == "deepseek-v4-pro"


def test_api_key_required() -> None:
    with pytest.raises(ApiConfigurationError):
        OpenAICompatibleClient(get_provider("Qwen"), "")
