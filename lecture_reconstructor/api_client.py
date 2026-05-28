from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from .models import ProviderConfig


class ApiConfigurationError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, provider: ProviderConfig, api_key: str):
        if not api_key:
            raise ApiConfigurationError("API key is required before generation.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ApiConfigurationError(
                "The openai package is required. Install dependencies with: pip install -r requirements.txt"
            ) from exc
        self.provider = provider
        self.client = OpenAI(api_key=api_key, base_url=provider.base_url)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.25,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.provider.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.provider.extra_body:
            kwargs["extra_body"] = self.provider.extra_body

        if not stream:
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        chunks = self.client.chat.completions.create(stream=True, **kwargs)
        parts: list[str] = []
        for chunk in chunks:
            delta = chunk.choices[0].delta.content or ""
            parts.append(delta)
        return "".join(parts)

    def ocr_image(
        self,
        image_path: Path,
        *,
        prompt: str = "请完整识别图片中的文字、公式、表格结构和图示含义。保留页码线索，不要编造看不见的内容。",
    ) -> str:
        if not self.provider.supports_vision:
            raise ApiConfigurationError(f"{self.provider.name} is not configured for vision OCR.")
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                ],
            }
        ]
        return self.chat(messages, max_tokens=4096)
