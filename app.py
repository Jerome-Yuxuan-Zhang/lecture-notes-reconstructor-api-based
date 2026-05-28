from __future__ import annotations

import asyncio
from html import escape
import os
from pathlib import Path
from typing import Any

from nicegui import app as nice_app
from nicegui import ui

from lecture_reconstructor.api_client import ApiConfigurationError, OpenAICompatibleClient
from lecture_reconstructor.batch import generate_batch, list_batch_folders
from lecture_reconstructor.generator import generate_lecture
from lecture_reconstructor.material import extract_materials, scan_materials
from lecture_reconstructor.models import GenerationConfig, ProviderConfig
from lecture_reconstructor.providers import PROVIDERS
from lecture_reconstructor.settings import (
    SETTINGS_PATH,
    delete_api_key,
    load_api_key,
    load_settings,
    save_api_key,
    save_settings,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = ROOT / "outputs"
DEFAULT_MAX_TOKENS = 180000
MAX_TOKEN_LIMIT = 200000


class TaskState:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.result_html = ""
        self.history: list[dict[str, str]] = []
        self.running = False

    def log(self, message: str) -> None:
        self.logs.append(message)


state = TaskState()


def load_provider_catalog(settings: dict[str, Any]) -> dict[str, ProviderConfig]:
    catalog = {name: ProviderConfig(**provider.to_dict()) for name, provider in PROVIDERS.items()}
    for name, raw in (settings.get("custom_providers") or {}).items():
        try:
            catalog[name] = ProviderConfig(**raw)
        except TypeError:
            continue
    return catalog


def provider_from_catalog(catalog: dict[str, ProviderConfig], name: str) -> ProviderConfig:
    provider = catalog.get(name) or catalog.get("Qwen") or next(iter(catalog.values()))
    return ProviderConfig(**provider.to_dict())


def initial_settings() -> dict[str, Any]:
    settings = load_settings()
    catalog = load_provider_catalog(settings)
    provider_name = settings.get("provider") if settings.get("provider") in catalog else "Qwen"
    provider = provider_from_catalog(catalog, provider_name)
    settings["provider"] = provider.name
    settings["input_dir"] = settings.get("input_dir") or str(ROOT)
    settings["output_root"] = settings.get("output_root") or str(DEFAULT_OUTPUT_ROOT)
    settings["base_url"] = settings.get("base_url") or provider.base_url
    settings["model"] = settings.get("model") or provider.model
    settings["api_key_env"] = settings.get("api_key_env") or provider.api_key_env
    settings["max_tokens"] = int(settings.get("max_tokens") or DEFAULT_MAX_TOKENS)
    settings["custom_providers"] = settings.get("custom_providers") or {}
    settings["batch_mode"] = bool(settings.get("batch_mode", False))
    return settings


def preview_iframe_html(document_html: str) -> str:
    srcdoc = escape(document_html, quote=True)
    return (
        '<iframe '
        f'srcdoc="{srcdoc}" '
        'style="width:100%; min-height:720px; border:0; background:white;" '
        'sandbox="allow-scripts allow-same-origin">'
        "</iframe>"
    )


def pick_directory(initial_dir: str | None = None) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected = filedialog.askdirectory(initialdir=initial_dir or str(ROOT), title="选择文件夹")
    root.destroy()
    return selected


async def browse_directory(target_input: Any) -> None:
    selected = await asyncio.to_thread(pick_directory, target_input.value or str(ROOT))
    if selected:
        target_input.value = selected
        target_input.update()


@ui.page("/")
def main_page() -> None:
    ui.add_head_html(
        """
        <style>
        body { background: #f6f4ef; }
        .nicegui-content { padding: 0; }
        .workspace-card {
          border: 1px solid #d8d2c8;
          border-radius: 8px;
          background: rgba(255,255,255,0.88);
          box-shadow: 0 10px 28px rgba(30, 25, 18, 0.08);
        }
        .mono-log {
          font-family: "Cascadia Mono", Consolas, monospace;
          white-space: pre-wrap;
        }
        </style>
        """
    )

    settings = initial_settings()
    provider_catalog = load_provider_catalog(settings)

    with ui.row().classes("w-full min-h-screen no-wrap"):
        with ui.column().classes("w-72 p-5 bg-[#252a31] text-white gap-4"):
            ui.label("讲义重构工作台").classes("text-2xl font-bold")
            ui.label("Lecture Reconstructor").classes("text-sm opacity-70")
            ui.separator().classes("bg-white/20")
            ui.label("任务").classes("text-xs uppercase tracking-widest opacity-60")
            ui.button("生成讲义", icon="auto_stories").props("flat color=white").classes("justify-start")
            ui.button("历史输出", icon="history").props("flat color=white").classes("justify-start")
            ui.button("API 设置", icon="settings").props("flat color=white").classes("justify-start")
            ui.space()
            ui.label("安全策略").classes("text-xs uppercase tracking-widest opacity-60")
            ui.markdown("默认不保存 API Key。\n\n勾选记住时写入系统钥匙串。\n\n输出包不会包含密钥。").classes("text-sm opacity-80")

        with ui.column().classes("flex-1 p-6 gap-5"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-1"):
                    ui.label("从材料文件夹生成教科书级 HTML 讲义").classes("text-3xl font-bold text-[#252a31]")
                    ui.label("可单模块生成，也可按 input 下的子文件夹批量生成。").classes("text-[#6f675d]")
                status_badge = ui.badge("Idle", color="grey").classes("text-base px-3 py-2")

            with ui.tabs().classes("w-full") as tabs:
                tab_setup = ui.tab("配置")
                tab_materials = ui.tab("材料")
                tab_run = ui.tab("运行")
                tab_preview = ui.tab("预览")
                tab_history = ui.tab("历史")

            with ui.tab_panels(tabs, value=tab_setup).classes("w-full bg-transparent"):
                with ui.tab_panel(tab_setup).classes("p-0"):
                    with ui.card().classes("workspace-card w-full p-5"):
                        ui.label("任务配置").classes("text-xl font-semibold")
                        with ui.grid(columns=2).classes("w-full gap-4"):
                            with ui.row().classes("w-full items-end gap-2"):
                                input_dir = ui.input("输入材料文件夹", value=settings["input_dir"]).props("outlined clearable").classes("flex-1")
                                ui.button("浏览", icon="folder_open", on_click=lambda: asyncio.create_task(browse_directory(input_dir))).props("outline")
                            with ui.row().classes("w-full items-end gap-2"):
                                output_root = ui.input("输出根目录", value=settings["output_root"]).props("outlined clearable").classes("flex-1")
                                ui.button("浏览", icon="folder_open", on_click=lambda: asyncio.create_task(browse_directory(output_root))).props("outline")
                            project_name = ui.input("项目名", value=settings["project_name"]).props("outlined clearable")
                            provider_select = ui.select(
                                list(provider_catalog.keys()),
                                value=settings["provider"],
                                label="API 提供商",
                            ).props("outlined")
                            model_select = ui.select([], label="常用模型").props("outlined")
                            model = ui.input("模型名称（可手动覆盖）", value=settings["model"]).props("outlined clearable")
                            base_url = ui.input("Base URL", value=settings["base_url"]).props("outlined clearable")
                            api_key = ui.input("API Key", password=True, password_toggle_button=True).props("outlined")
                            env_hint = ui.input("环境变量", value=settings["api_key_env"]).props("outlined clearable")
                            custom_name = ui.input("保存为自定义提供商名称", value="").props("outlined clearable")
                            temperature = ui.number("Temperature", value=settings["temperature"], min=0, max=2, step=0.05).props("outlined")
                            max_tokens = ui.number(
                                "Max output tokens",
                                value=settings["max_tokens"],
                                min=1024,
                                max=MAX_TOKEN_LIMIT,
                                step=1024,
                            ).props("outlined")

                        with ui.row().classes("items-center gap-6 mt-3"):
                            stream = ui.switch("流式生成", value=bool(settings["stream"]))
                            vision_ocr = ui.switch("视觉 OCR", value=bool(settings["enable_vision_ocr"]))
                            batch_mode = ui.switch("批量子文件夹模式", value=bool(settings["batch_mode"]))
                            remember_key = ui.switch("记住 API Key（系统钥匙串）", value=bool(settings["remember_api_key"]))
                            test_label = ui.label("").classes("text-sm")

                        ui.label("批量模式：输入目录应包含 module1、module2 等一级子文件夹；程序按字母顺序逐个生成，每个子文件夹使用全新的 API 上下文。").classes("text-xs text-[#6f675d]")

                        def current_settings() -> dict[str, Any]:
                            return {
                                "input_dir": input_dir.value or "",
                                "output_root": output_root.value or "",
                                "project_name": project_name.value or "lecture",
                                "provider": provider_select.value,
                                "base_url": base_url.value or "",
                                "model": model.value or "",
                                "api_key_env": env_hint.value or "",
                                "custom_providers": {
                                    name: provider.to_dict()
                                    for name, provider in provider_catalog.items()
                                    if name not in PROVIDERS
                                },
                                "temperature": float(temperature.value or 0.25),
                                "max_tokens": int(max_tokens.value or DEFAULT_MAX_TOKENS),
                                "stream": bool(stream.value),
                                "enable_vision_ocr": bool(vision_ocr.value),
                                "batch_mode": bool(batch_mode.value),
                                "remember_api_key": bool(remember_key.value),
                            }

                        def resolve_api_key() -> str:
                            return api_key.value or os.getenv(env_hint.value or "", "") or load_api_key(provider_select.value)

                        def refresh_model_options(provider: ProviderConfig) -> None:
                            options = provider.models or [provider.model]
                            if model.value and model.value not in options:
                                options = [model.value, *options]
                            model_select.options = options
                            model_select.value = model.value if model.value in options else provider.model
                            model_select.update()

                        def sync_provider(load_saved_key: bool = True) -> None:
                            provider = provider_from_catalog(provider_catalog, provider_select.value)
                            base_url.value = provider.base_url
                            model.value = provider.model
                            env_hint.value = provider.api_key_env
                            api_key.value = os.getenv(provider.api_key_env, "")
                            if load_saved_key and not api_key.value:
                                api_key.value = load_api_key(provider.name)
                            refresh_model_options(provider)
                            base_url.update()
                            model.update()
                            env_hint.update()
                            api_key.update()

                        def sync_model_from_select() -> None:
                            if model_select.value:
                                model.value = model_select.value
                                model.update()

                        def save_custom_provider() -> None:
                            name = (custom_name.value or "").strip()
                            if not name:
                                ui.notify("请先填写自定义提供商名称。", color="warning")
                                return
                            provider_catalog[name] = ProviderConfig(
                                name=name,
                                base_url=base_url.value or "",
                                model=model.value or "",
                                api_key_env=env_hint.value or f"{name.upper()}_API_KEY",
                                supports_vision=bool(vision_ocr.value),
                                models=[model.value] if model.value else [],
                            )
                            provider_select.options = list(provider_catalog.keys())
                            provider_select.value = name
                            provider_select.update()
                            save_settings(current_settings())
                            ui.notify(f"已保存自定义提供商：{name}", color="positive")

                        def save_current_config() -> None:
                            path = save_settings(current_settings())
                            if remember_key.value and api_key.value:
                                if save_api_key(provider_select.value, api_key.value):
                                    ui.notify("配置已保存，API Key 已写入系统钥匙串。", color="positive")
                                else:
                                    ui.notify("配置已保存，但系统钥匙串不可用，API Key 未保存。", color="warning")
                            else:
                                delete_api_key(provider_select.value)
                                ui.notify(f"配置已保存：{path}", color="positive")

                        def reload_config() -> None:
                            nonlocal settings, provider_catalog
                            settings = initial_settings()
                            provider_catalog = load_provider_catalog(settings)
                            input_dir.value = settings["input_dir"]
                            output_root.value = settings["output_root"]
                            project_name.value = settings["project_name"]
                            provider_select.options = list(provider_catalog.keys())
                            provider_select.value = settings["provider"]
                            base_url.value = settings["base_url"]
                            model.value = settings["model"]
                            env_hint.value = settings["api_key_env"]
                            temperature.value = settings["temperature"]
                            max_tokens.value = settings["max_tokens"]
                            stream.value = settings["stream"]
                            vision_ocr.value = settings["enable_vision_ocr"]
                            batch_mode.value = settings["batch_mode"]
                            remember_key.value = settings["remember_api_key"]
                            api_key.value = os.getenv(env_hint.value or "", "") or load_api_key(provider_select.value)
                            refresh_model_options(provider_from_catalog(provider_catalog, provider_select.value))
                            ui.notify("配置已重新加载。", color="positive")

                        provider_select.on_value_change(lambda _: sync_provider())
                        model_select.on_value_change(lambda _: sync_model_from_select())
                        refresh_model_options(provider_from_catalog(provider_catalog, provider_select.value))
                        if settings["remember_api_key"]:
                            api_key.value = load_api_key(provider_select.value) or os.getenv(env_hint.value or "", "")
                        else:
                            api_key.value = os.getenv(env_hint.value or "", "")

                        async def test_api() -> None:
                            try:
                                provider = provider_from_catalog(provider_catalog, provider_select.value)
                                provider.base_url = base_url.value
                                provider.model = model.value
                                provider.api_key_env = env_hint.value
                                provider.supports_vision = bool(vision_ocr.value)
                                client = OpenAICompatibleClient(provider, resolve_api_key())
                                text = await asyncio.to_thread(
                                    client.chat,
                                    [{"role": "user", "content": "请只回复 OK。"}],
                                    max_tokens=16,
                                )
                                test_label.text = f"连通成功：{text[:40]}"
                                ui.notify("API 连接成功。", color="positive")
                            except Exception as exc:  # noqa: BLE001
                                test_label.text = f"连通失败：{exc}"
                                ui.notify(str(exc), color="negative")

                        with ui.row().classes("gap-3 mt-3"):
                            ui.button("测试 API", icon="wifi_tethering", on_click=test_api).props("color=primary")
                            ui.button("保存配置", icon="save", on_click=save_current_config).props("color=secondary")
                            ui.button("保存为自定义", icon="add", on_click=save_custom_provider).props("color=secondary outline")
                            ui.button("重新加载", icon="refresh", on_click=reload_config).props("flat")
                        ui.label(f"配置文件：{SETTINGS_PATH}").classes("text-xs text-[#6f675d]")

                with ui.tab_panel(tab_materials).classes("p-0"):
                    with ui.card().classes("workspace-card w-full p-5"):
                        ui.label("材料清单").classes("text-xl font-semibold")
                        material_table = ui.table(
                            columns=[
                                {"name": "relative_path", "label": "文件", "field": "relative_path", "align": "left"},
                                {"name": "material_type", "label": "类型", "field": "material_type"},
                                {"name": "status", "label": "状态", "field": "status"},
                            ],
                            rows=[],
                            row_key="relative_path",
                        ).classes("w-full")

                        def scan_only() -> None:
                            try:
                                if batch_mode.value:
                                    folders = list_batch_folders(Path(input_dir.value))
                                    material_table.rows = [
                                        {
                                            "relative_path": folder.name,
                                            "material_type": "folder",
                                            "status": f"batch item {index}/{len(folders)}",
                                        }
                                        for index, folder in enumerate(folders, start=1)
                                    ]
                                    ui.notify(f"发现 {len(folders)} 个子文件夹，将按字母顺序批量处理。", color="positive")
                                else:
                                    docs = scan_materials(Path(input_dir.value))
                                    material_table.rows = [doc.to_dict() for doc in docs]
                                    ui.notify(f"发现 {len(docs)} 个支持的材料文件。", color="positive")
                                material_table.update()
                            except Exception as exc:  # noqa: BLE001
                                ui.notify(str(exc), color="negative")

                        ui.button("扫描材料", icon="folder_open", on_click=scan_only).props("color=primary")

                with ui.tab_panel(tab_run).classes("p-0"):
                    with ui.card().classes("workspace-card w-full p-5"):
                        ui.label("生成进度").classes("text-xl font-semibold")
                        progress = ui.linear_progress(value=0).classes("w-full")
                        log_area = ui.textarea("实时日志").classes("w-full mono-log").props("outlined autogrow readonly")
                        error_area = ui.textarea("错误面板").classes("w-full mono-log").props("outlined autogrow readonly")

                        def refresh_logs() -> None:
                            log_area.value = "\n".join(state.logs[-300:])
                            error_area.value = "\n".join(state.errors[-100:])
                            log_area.update()
                            error_area.update()

                        async def run_generation() -> None:
                            if state.running:
                                ui.notify("已有任务正在运行。", color="warning")
                                return
                            state.running = True
                            state.logs.clear()
                            state.errors.clear()
                            status_badge.text = "Running"
                            status_badge.props("color=orange")
                            progress.value = 0.05
                            refresh_logs()
                            try:
                                provider = provider_from_catalog(provider_catalog, provider_select.value)
                                provider.base_url = base_url.value
                                provider.model = model.value
                                provider.api_key_env = env_hint.value
                                provider.supports_vision = bool(vision_ocr.value)
                                key = resolve_api_key()
                                if not key:
                                    raise ApiConfigurationError("缺少 API Key，不能生成。")
                                config = GenerationConfig(
                                    input_dir=Path(input_dir.value),
                                    output_root=Path(output_root.value),
                                    provider=provider,
                                    api_key=key,
                                    project_name=project_name.value or "lecture",
                                    temperature=float(temperature.value or 0.25),
                                    max_tokens=int(max_tokens.value or DEFAULT_MAX_TOKENS),
                                    stream=bool(stream.value),
                                    enable_vision_ocr=bool(vision_ocr.value),
                                )

                                def make_client() -> OpenAICompatibleClient:
                                    fresh_provider = ProviderConfig(**provider.to_dict())
                                    return OpenAICompatibleClient(fresh_provider, key)

                                if batch_mode.value:
                                    state.log("Batch mode enabled. Each subfolder uses a fresh API context.")
                                    folders = list_batch_folders(config.input_dir)
                                    material_table.rows = [
                                        {
                                            "relative_path": folder.name,
                                            "material_type": "folder",
                                            "status": f"pending {index}/{len(folders)}",
                                        }
                                        for index, folder in enumerate(folders, start=1)
                                    ]
                                    material_table.update()
                                    results = await asyncio.to_thread(generate_batch, config, make_client, log=state.log)
                                    progress.value = 1.0
                                    for result in results:
                                        state.history.insert(
                                            0,
                                            {
                                                "output_dir": str(result.output_dir),
                                                "html_path": str(result.html_path),
                                                "zip_path": str(result.zip_path),
                                            },
                                        )
                                    if results:
                                        state.result_html = results[-1].html_path.read_text(encoding="utf-8")
                                        preview_frame.set_content(preview_iframe_html(state.result_html))
                                    history_table.rows = state.history
                                    history_table.update()
                                    status_badge.text = "Done"
                                    status_badge.props("color=green")
                                    ui.notify(f"批量生成完成：{len(results)} 个子文件夹。", color="positive")
                                    return

                                client = make_client()
                                state.log("Scanning materials.")
                                docs = await asyncio.to_thread(scan_materials, config.input_dir)
                                progress.value = 0.2
                                material_table.rows = [doc.to_dict() for doc in docs]
                                material_table.update()
                                refresh_logs()

                                state.log("Extracting text and OCR content.")
                                docs = await asyncio.to_thread(extract_materials, docs, client, config)
                                progress.value = 0.45
                                material_table.rows = [doc.to_dict() for doc in docs]
                                material_table.update()
                                refresh_logs()

                                result = await asyncio.to_thread(generate_lecture, docs, config, client, log=state.log)
                                progress.value = 1.0
                                state.result_html = result.html_path.read_text(encoding="utf-8")
                                state.history.insert(
                                    0,
                                    {
                                        "output_dir": str(result.output_dir),
                                        "html_path": str(result.html_path),
                                        "zip_path": str(result.zip_path),
                                    },
                                )
                                history_table.rows = state.history
                                history_table.update()
                                preview_frame.set_content(preview_iframe_html(state.result_html))
                                status_badge.text = "Done"
                                status_badge.props("color=green")
                                ui.notify(f"生成完成：{result.output_dir}", color="positive")
                            except Exception as exc:  # noqa: BLE001
                                state.errors.append(str(exc))
                                status_badge.text = "Failed"
                                status_badge.props("color=red")
                                ui.notify(str(exc), color="negative")
                            finally:
                                state.running = False
                                refresh_logs()

                        ui.button("开始生成", icon="play_arrow", on_click=run_generation).props("color=primary size=lg")

                with ui.tab_panel(tab_preview).classes("p-0"):
                    with ui.card().classes("workspace-card w-full p-5"):
                        ui.label("HTML 预览").classes("text-xl font-semibold")
                        preview_frame = ui.html("<div style='padding:24px;color:#777'>生成后将在这里预览 lecture.html。</div>").classes(
                            "w-full min-h-[620px] bg-white border"
                        )

                with ui.tab_panel(tab_history).classes("p-0"):
                    with ui.card().classes("workspace-card w-full p-5"):
                        ui.label("历史输出").classes("text-xl font-semibold")
                        history_table = ui.table(
                            columns=[
                                {"name": "output_dir", "label": "输出文件夹", "field": "output_dir", "align": "left"},
                                {"name": "html_path", "label": "HTML", "field": "html_path", "align": "left"},
                                {"name": "zip_path", "label": "ZIP", "field": "zip_path", "align": "left"},
                            ],
                            rows=state.history,
                        ).classes("w-full")


if __name__ in {"__main__", "__mp_main__"}:
    nice_app.native.window_args["title"] = "Lecture Reconstructor"
    ui.run(title="Lecture Reconstructor", reload=False, port=8080)
