from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from lecture_reconstructor.generator import _sanitize_currency_symbols, generate_lecture
from lecture_reconstructor.html_assets import LECTURE_CSS, ensure_full_html
from lecture_reconstructor.models import GenerationConfig, MaterialDocument
from lecture_reconstructor.providers import get_provider


class DummyChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "Outline: Chapter 1 Test"
        return json.dumps(
            {
                "lecture_html": "<h1>Glossary</h1><div class='formula-card'><div class='formula-body'>$$x^{2}$$</div></div>",
                "self_check": "# self check",
                "figure_scripts": [
                    {
                        "path": "chapter_1/fig_1_1_test.py",
                        "code": "from pathlib import Path\nPath('assets/fig_1_1_test.png').write_text('ok', encoding='utf-8')",
                    }
                ],
            },
            ensure_ascii=False,
        )


class MarkerChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "Outline: Chapter 1 Test"
        return """<<<LECTURE_HTML>>>
<h1>Glossary</h1><p><img src="assets/fig_1_1_marker.png" alt="marker"></p>
<<<END_LECTURE_HTML>>>

<<<SELF_CHECK>>>
# self check
<<<END_SELF_CHECK>>>

<<<FIGURE_SCRIPT:chapter_1/fig_1_1_marker.py>>>
from pathlib import Path
Path('assets/fig_1_1_marker.png').write_text('ok', encoding='utf-8')
<<<END_FIGURE_SCRIPT>>>"""


class MissingAssetChatClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "Outline: Chapter 1 Test"
        return """<<<LECTURE_HTML>>>
<h1>Glossary</h1><p><img src="assets/missing.png" alt="missing"></p>
<<<END_LECTURE_HTML>>>
<<<SELF_CHECK>>>
# self check
<<<END_SELF_CHECK>>>"""


def _config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        input_dir=tmp_path,
        output_root=tmp_path / "outputs",
        provider=get_provider("Qwen"),
        api_key="test",
        project_name="course",
    )


def test_generate_lecture_writes_expected_package(tmp_path: Path) -> None:
    doc_path = tmp_path / "note.md"
    doc_path.write_text("Concept A", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="note.md",
            material_type="md",
            text="Concept A",
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
    scripts_dir = result.output_dir / "script4course"
    assert (scripts_dir / "README.md").exists()
    assert (scripts_dir / "chapter_1" / "fig_1_1_test.py").exists()
    assert (result.output_dir / "assets" / "fig_1_1_test.png").exists()

    html = result.html_path.read_text(encoding="utf-8")
    assert "MathJax" in html
    assert "tex-chtml.js" in html
    assert "tex-svg.js" not in html
    assert "inlineMath: [['\\\\(', '\\\\)']]" in html
    assert "['$', '$']" not in html
    assert "[tex]/unicode" in html
    assert "pounds: ['\\\\unicode{x00A3}', 0]" in html
    assert ".formula-card" in html
    assert "base64" not in html
    assert "assets/fig_0_1_material_mix.png" not in html
    assert "formula-card" in LECTURE_CSS

    with ZipFile(result.zip_path) as archive:
        names = archive.namelist()
    assert any(name.endswith("lecture.html") for name in names)
    assert any("script4course/" in name for name in names)


def test_output_directory_names_are_unique(tmp_path: Path) -> None:
    doc_path = tmp_path / "note.md"
    doc_path.write_text("Concept A", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="note.md",
            material_type="md",
            text="Concept A",
            status="extracted",
        )
    ]

    first = generate_lecture(docs, _config(tmp_path), DummyChatClient())
    second = generate_lecture(docs, _config(tmp_path), DummyChatClient())

    assert first.output_dir != second.output_dir
    assert first.output_dir.exists()
    assert second.output_dir.exists()


def test_marker_response_writes_and_runs_figure_scripts(tmp_path: Path) -> None:
    doc_path = tmp_path / "note.md"
    doc_path.write_text("Concept A", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="note.md",
            material_type="md",
            text="Concept A",
            status="extracted",
        )
    ]

    result = generate_lecture(docs, _config(tmp_path), MarkerChatClient())

    assert (result.output_dir / "assets" / "fig_1_1_marker.png").exists()
    assert (result.output_dir / "script4course" / "chapter_1" / "fig_1_1_marker.py").exists()
    assert result.errors == []


def test_missing_referenced_assets_are_reported(tmp_path: Path) -> None:
    doc_path = tmp_path / "note.md"
    doc_path.write_text("Concept A", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="note.md",
            material_type="md",
            text="Concept A",
            status="extracted",
        )
    ]

    result = generate_lecture(docs, _config(tmp_path), MissingAssetChatClient())

    assert "Referenced asset was not generated: assets/missing.png" in result.errors


def test_sanitize_currency_symbols_prevents_mathjax_currency_errors() -> None:
    text = (
        "S = \\$1.50/€ and spot is $1.20/€ with $300,000 or €750,000. "
        "Cost is \\(\\text{\\$}4,545,455\\) and rate is $\\text{\\$}1.50/\\text{EUR}$."
    )

    sanitized = _sanitize_currency_symbols(text)

    assert "S = 1.50\\,\\mathrm{USD/EUR}" in sanitized
    assert "\\(1.20\\,\\mathrm{USD/EUR}\\)" in sanitized
    assert "\\(300,000\\,\\mathrm{USD}\\)" in sanitized
    assert "\\(750,000\\,\\mathrm{EUR}\\)" in sanitized
    assert "\\(4,545,455\\,\\mathrm{USD}\\)" in sanitized
    assert "\\(1.50\\,\\mathrm{USD/EUR}\\)" in sanitized
    assert "€" not in sanitized
    assert "\\text{\\$}" not in sanitized


def test_ensure_full_html_replaces_unsafe_mathjax_config() -> None:
    html = """<!doctype html>
<html>
<head>
<script>
window.MathJax = {
  tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
</head>
<body><p>Cost is $100.</p></body>
</html>"""

    normalized = ensure_full_html(html)

    assert "tex-chtml.js" in normalized
    assert "tex-svg.js" not in normalized
    assert "['$', '$']" not in normalized
    assert "inlineMath: [['\\\\(', '\\\\)']]" in normalized
    assert "[tex]/unicode" in normalized
    assert "bitcoin: ['\\\\unicode{x20BF}', 0]" in normalized
