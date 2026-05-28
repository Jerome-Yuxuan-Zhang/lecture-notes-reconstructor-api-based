from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Protocol

from .generator import generate_lecture
from .material import extract_materials, scan_materials
from .models import GenerationConfig, GenerationResult


class BatchClient(Protocol):
    def chat(self, messages: list[dict], **kwargs: object) -> str:
        ...

    def ocr_image(self, image_path: Path) -> str:
        ...


ClientFactory = Callable[[], BatchClient]
LogFn = Callable[[str], None]


def list_batch_folders(input_root: Path) -> list[Path]:
    root = Path(input_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {root}")
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name.casefold())


def generate_batch(
    config: GenerationConfig,
    client_factory: ClientFactory,
    *,
    log: LogFn | None = None,
) -> list[GenerationResult]:
    folders = list_batch_folders(config.input_dir)
    if not folders:
        raise ValueError("Batch mode needs at least one direct subfolder under the input folder.")

    results: list[GenerationResult] = []
    total = len(folders)
    for index, folder in enumerate(folders, start=1):
        module_name = folder.name
        module_project = f"{config.project_name}_{module_name}" if config.project_name else module_name
        module_config = replace(config, input_dir=folder, project_name=module_project)
        client = client_factory()

        _log(log, f"[{index}/{total}] Starting module: {module_name}")
        _log(log, f"[{index}/{total}] Scanning materials.")
        documents = scan_materials(folder)
        _log(log, f"[{index}/{total}] Extracting text and OCR content.")
        documents = extract_materials(documents, client, module_config)
        _log(log, f"[{index}/{total}] Generating lecture with a fresh API context.")
        result = generate_lecture(documents, module_config, client, log=log)
        results.append(result)
        _log(log, f"[{index}/{total}] Finished module: {module_name}")

    return results


def _log(log: LogFn | None, message: str) -> None:
    if log:
        log(message)
