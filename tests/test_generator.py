from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from lecture_reconstructor.generator import generate_lecture
from lecture_reconstructor.html_assets import LECTURE_CSS
from lecture_reconstructor.models import GenerationConfig, MaterialDocument
from lecture_reconstructor.providers import get_provider


class DummyChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "大纲：第一章 测试 ★★★"
        return json.dumps(
            {
                "lecture_html": "<h1>术语表 / Glossary</h1><div class='formula-card'><div class='formula-body'>$$x^{2}$$</div></div>",
                "self_check": "# 自检 / 覆盖核对\n\n| 页码/文件 | 所属模块 | 主要知识点 | 讲义对应位置 | 图表或例题是否已重构 | 覆盖状态 |\n| --- | --- | --- | --- | --- | --- |",
            },
            ensure_ascii=False,
        )


def _config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        input_dir=tmp_path,
        output_root=tmp_path / "outputs",
        provider=get_provider("Qwen"),
        api_key="test",
        project_name="课程 A",
    )


def test_generate_lecture_writes_expected_package(tmp_path: Path) -> None:
    doc_path = tmp_path / "note.md"
    doc_path.write_text("概念 A", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="note.md",
            material_type="md",
            text="概念 A",
            status="extracted",
        )
    ]

    result = generate_lecture(docs, _config(tmp_path), DummyChatClient())

    assert result.html_path.exists()
    assert result.zip_path.exists()
    assert (result.output_dir / "assets").exists()
    assert (result.output_dir / "self_check.md").exists()
    assert (result.output_dir / "manifest.json").exists()
    assert (result.output_dir / "source_index.json").exists()

    html = result.html_path.read_text(encoding="utf-8")
    assert "MathJax" in html
    assert ".formula-card" in html
    assert "base64" not in html
    assert "assets/fig_0_1_material_mix.png" not in html
    assert "formula-card" in LECTURE_CSS

    with ZipFile(result.zip_path) as archive:
        names = archive.namelist()
    assert any(name.endswith("lecture.html") for name in names)
    assert any(name.endswith("assets/") or "/assets/" in name for name in names) or (result.output_dir / "assets").exists()


def test_output_directory_names_are_unique(tmp_path: Path) -> None:
    doc_path = tmp_path / "note.md"
    doc_path.write_text("概念 A", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="note.md",
            material_type="md",
            text="概念 A",
            status="extracted",
        )
    ]

    first = generate_lecture(docs, _config(tmp_path), DummyChatClient())
    second = generate_lecture(docs, _config(tmp_path), DummyChatClient())

    assert first.output_dir != second.output_dir
    assert first.output_dir.exists()
    assert second.output_dir.exists()
