from __future__ import annotations

from .models import ProviderConfig


PROVIDERS: dict[str, ProviderConfig] = {
    "Qwen": ProviderConfig(
        name="Qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-max",
        api_key_env="DASHSCOPE_API_KEY",
        supports_vision=True,
        max_output_tokens=65536,
        models=[
            "qwen3.7-max",
            "qwen3-max",
            "qwen-plus",
            "qwen-turbo",
            "qwen-vl-plus",
            "qwen-vl-max",
        ],
    ),
    "DeepSeek": ProviderConfig(
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-pro",
        api_key_env="DEEPSEEK_API_KEY",
        supports_vision=True,
        models=[
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    ),
    "OpenAI": ProviderConfig(
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-5",
        api_key_env="OPENAI_API_KEY",
        supports_vision=True,
        models=[
            "gpt-5",
            "gpt-5-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "o3",
            "o4-mini",
        ],
    ),
    "OpenRouter": ProviderConfig(
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-sonnet-4",
        api_key_env="OPENROUTER_API_KEY",
        supports_vision=True,
        models=[
            "anthropic/claude-sonnet-4",
            "openai/gpt-5",
            "google/gemini-2.5-pro",
            "deepseek/deepseek-chat",
            "qwen/qwen3-max",
        ],
    ),
    "SiliconFlow": ProviderConfig(
        name="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        model="Qwen/Qwen3-235B-A22B-Instruct-2507",
        api_key_env="SILICONFLOW_API_KEY",
        supports_vision=True,
        models=[
            "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "Qwen/Qwen3-30B-A3B-Instruct-2507",
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
        ],
    ),
    "Moonshot": ProviderConfig(
        name="Moonshot",
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k2-0905-preview",
        api_key_env="MOONSHOT_API_KEY",
        supports_vision=False,
        models=[
            "kimi-k2-0905-preview",
            "moonshot-v1-128k",
            "moonshot-v1-32k",
            "moonshot-v1-8k",
        ],
    ),
    "Zhipu": ProviderConfig(
        name="Zhipu",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.5",
        api_key_env="ZHIPU_API_KEY",
        supports_vision=True,
        models=[
            "glm-4.5",
            "glm-4.5-air",
            "glm-4-plus",
            "glm-4v-plus",
        ],
    ),
    "MiniMax": ProviderConfig(
        name="MiniMax",
        base_url="https://api.minimax.chat/v1",
        model="MiniMax-M1",
        api_key_env="MINIMAX_API_KEY",
        supports_vision=True,
        models=[
            "MiniMax-M1",
            "MiniMax-Text-01",
            "MiniMax-VL-01",
        ],
    ),
    "Custom": ProviderConfig(
        name="Custom",
        base_url="https://example.com/v1",
        model="your-model-name",
        api_key_env="CUSTOM_OPENAI_API_KEY",
        supports_vision=True,
        models=[
            "your-model-name",
        ],
    ),
}


def get_provider(name: str) -> ProviderConfig:
    try:
        provider = PROVIDERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {name}") from exc
    return ProviderConfig(**provider.to_dict())
