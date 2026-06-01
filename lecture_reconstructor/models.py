from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ProviderConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str
    supports_vision: bool = True
    max_output_tokens: int | None = None
    models: list[str] = field(default_factory=list)
    extra_body: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GenerationConfig:
    input_dir: Path
    output_root: Path
    provider: ProviderConfig
    api_key: str
    project_name: str = "lecture"
    temperature: float = 0.25
    max_tokens: int = 8192
    stream: bool = False
    enable_vision_ocr: bool = True


@dataclass(slots=True)
class MaterialDocument:
    source_path: Path
    relative_path: str
    material_type: str
    page_label: str | None = None
    text: str = ""
    image_path: Path | None = None
    status: str = "indexed"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        data["image_path"] = str(self.image_path) if self.image_path else None
        return data


@dataclass(slots=True)
class GenerationResult:
    output_dir: Path
    html_path: Path
    zip_path: Path
    errors: list[str]
    coverage_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "html_path": str(self.html_path),
            "zip_path": str(self.zip_path),
            "errors": self.errors,
            "coverage_summary": self.coverage_summary,
        }
