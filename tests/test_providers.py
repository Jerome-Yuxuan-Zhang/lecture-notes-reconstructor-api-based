from __future__ import annotations

import pytest

from lecture_reconstructor.api_client import ApiConfigurationError, OpenAICompatibleClient
from lecture_reconstructor.providers import get_provider


def test_provider_presets_are_openai_compatible() -> None:
    qwen = get_provider("Qwen")
    deepseek = get_provider("DeepSeek")

    assert qwen.base_url.endswith("/compatible-mode/v1")
    assert qwen.model == "qwen3.7-max"
    assert qwen.max_output_tokens == 65536
    assert deepseek.base_url == "https://api.deepseek.com"
    assert deepseek.model == "deepseek-v4-pro"


def test_api_key_required() -> None:
    with pytest.raises(ApiConfigurationError):
        OpenAICompatibleClient(get_provider("Qwen"), "")


def test_qwen_max_tokens_are_clamped_to_provider_limit() -> None:
    class FakeCompletions:
        def __init__(self) -> None:
            self.kwargs = {}

        def create(self, **kwargs):
            self.kwargs = kwargs

            class Message:
                content = "ok"

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self) -> None:
            self.chat = FakeChat()

    client = OpenAICompatibleClient(get_provider("Qwen"), "test")
    fake = FakeOpenAI()
    client.client = fake

    response = client.chat([{"role": "user", "content": "hello"}], max_tokens=180000)

    assert response == "ok"
    assert fake.chat.completions.kwargs["max_tokens"] == 65536
