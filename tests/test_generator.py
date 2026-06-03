from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from lecture_reconstructor.generator import _build_material_digest, _sanitize_currency_symbols, generate_lecture
from lecture_reconstructor.html_assets import LECTURE_CSS, ensure_full_html
from lecture_reconstructor.models import GenerationConfig, MaterialDocument
from lecture_reconstructor.providers import get_provider
from lecture_reconstructor.reference_search import search_references


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


class PromptCaptureClient:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls.append(messages)
        if len(self.calls) == 1:
            return "Outline: investment banking needs deeper explanation"
        return """<<<LECTURE_HTML>>>
<h1>Glossary</h1><p>Investment banking</p>
<<<END_LECTURE_HTML>>>
<<<SELF_CHECK>>>
# self check
<<<END_SELF_CHECK>>>"""


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


class MainLectureOnlyClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "Outline: Chapter 1 Test"
        return """<<<LECTURE_HTML>>>
<h1>Glossary</h1>
<p>Payoff diagrams clarify the hedge.</p>
<figure>
  <img src="assets/fig_1_1_payoff.png" alt="payoff">
  <figcaption>Forward payoff diagram.</figcaption>
</figure>
<<<END_LECTURE_HTML>>>
<<<SELF_CHECK>>>
# self check
<<<END_SELF_CHECK>>>"""


class FigureScriptClient:
    def __init__(self) -> None:
        self.calls = 0
        self.last_prompt = ""

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        self.last_prompt = messages[-1]["content"]
        return """<<<FIGURE_SCRIPT:chapter_1/fig_1_1_payoff.py>>>
from pathlib import Path
Path('assets').mkdir(exist_ok=True)
Path('assets/fig_1_1_payoff.png').write_text('ok', encoding='utf-8')
<<<END_FIGURE_SCRIPT>>>"""


class NoFigureMainClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "Outline: Chapter 1 Test"
        return """<<<LECTURE_HTML>>>
<h1>Glossary</h1>
<p>Forward contracts are central to this module.</p>
<<<END_LECTURE_HTML>>>
<<<SELF_CHECK>>>
# self check
<<<END_SELF_CHECK>>>"""


class FigureSpecClient:
    def chat(self, messages: list[dict], **kwargs: object) -> str:
        return """<<<FIGURE_SPEC>>>
path: assets/fig_1_1_forward_contract.png
alt: Forward contract payoff
caption: Forward contract payoff as the future spot rate changes
insert_after: Forward contracts
<<<END_FIGURE_SPEC>>>

<<<FIGURE_SCRIPT:chapter_1/fig_1_1_forward_contract.py>>>
from pathlib import Path
Path('assets').mkdir(exist_ok=True)
Path('assets/fig_1_1_forward_contract.png').write_text('ok', encoding='utf-8')
<<<END_FIGURE_SCRIPT>>>"""


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


def test_material_digest_keeps_up_to_80k_chars_by_default(tmp_path: Path) -> None:
    doc_path = tmp_path / "long.md"
    text = "A" * 79000 + "CHAPTER10_MARKER"
    doc_path.write_text(text, encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path="long.md",
            material_type="md",
            text=text,
            status="extracted",
        )
    ]

    digest = _build_material_digest(docs)

    assert "CHAPTER10_MARKER" in digest
    assert "已截断" not in digest


def test_material_digest_separates_reference_materials(tmp_path: Path) -> None:
    primary_path = tmp_path / "lecture.md"
    reference_path = tmp_path / "reference" / "textbook.md"
    reference_path.parent.mkdir()
    primary_text = "PRIMARY_MARKER"
    reference_text = "R" * 9000 + "REFERENCE_TAIL"
    docs = [
        MaterialDocument(
            source_path=primary_path,
            relative_path="lecture.md",
            material_type="md",
            text=primary_text,
            status="extracted",
            role="primary",
        ),
        MaterialDocument(
            source_path=reference_path,
            relative_path="reference/textbook.md",
            material_type="md",
            text=reference_text,
            status="extracted",
            role="reference",
        ),
    ]

    digest = _build_material_digest(docs)

    assert "PRIMARY MATERIALS" in digest
    assert "REFERENCE INDEX" in digest
    assert "RETRIEVED REFERENCE EXCERPTS" in digest
    assert "PRIMARY_MARKER" in digest
    assert "REFERENCE_TAIL" not in digest
    assert "不要纳入逐页覆盖" in digest


def test_reference_search_retrieves_relevant_textbook_passages(tmp_path: Path) -> None:
    ref_path = tmp_path / "references" / "textbook.md"
    ref_path.parent.mkdir()
    docs = [
        MaterialDocument(
            source_path=ref_path,
            relative_path="references/textbook.md",
            material_type="md",
            text=(
                "Bond duration measures interest-rate sensitivity.\n\n"
                "Investment banking includes underwriting, advisory services, and securities distribution."
            ),
            status="extracted",
            role="reference",
        )
    ]

    hits = search_references(docs, "Explain investment banking in financial institutions")

    assert hits
    assert "Investment banking includes underwriting" in hits[0].text


def test_generation_uses_reference_index_for_outline_and_hits_for_final_prompt(tmp_path: Path) -> None:
    primary_path = tmp_path / "slides.md"
    reference_path = tmp_path / "references" / "textbook.md"
    reference_path.parent.mkdir()
    docs = [
        MaterialDocument(
            source_path=primary_path,
            relative_path="slides.md",
            material_type="md",
            text="Investment banking",
            status="extracted",
            role="primary",
        ),
        MaterialDocument(
            source_path=reference_path,
            relative_path="references/textbook.md",
            material_type="md",
            text="Investment banking includes underwriting, M&A advisory, and securities distribution.",
            status="extracted",
            role="reference",
        ),
    ]
    client = PromptCaptureClient()

    result = generate_lecture(docs, _config(tmp_path), client)

    outline_prompt = client.calls[0][-1]["content"]
    final_prompt = client.calls[1][-1]["content"]
    assert "REFERENCE INDEX" in outline_prompt
    assert "underwriting, M&A advisory" not in outline_prompt
    assert "RETRIEVED REFERENCE EXCERPTS" in final_prompt
    assert "underwriting, M&A advisory" in final_prompt
    assert (result.output_dir / "reference_hits.json").exists()


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


def test_two_stage_generation_uses_figure_client_for_scripts(tmp_path: Path) -> None:
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
    main_client = MainLectureOnlyClient()
    figure_client = FigureScriptClient()

    result = generate_lecture(docs, _config(tmp_path), main_client, figure_client=figure_client)

    assert main_client.calls == 2
    assert figure_client.calls == 1
    assert "assets/fig_1_1_payoff.png" in figure_client.last_prompt
    assert "Forward payoff diagram" in figure_client.last_prompt
    assert (result.output_dir / "assets" / "fig_1_1_payoff.png").exists()
    html = result.html_path.read_text(encoding="utf-8")
    assert "lecture-module-heading" in html
    assert "模块：note" in html
    assert "Module: note" in html


def test_figure_specs_are_inserted_when_html_has_no_asset_refs(tmp_path: Path) -> None:
    doc_path = tmp_path / "M3.1_Lecture_Ch08-Ch10_Transaction-and-Translation-Exposure.pdf"
    doc_path.write_text("Chapter 8 Transaction Exposure", encoding="utf-8")
    docs = [
        MaterialDocument(
            source_path=doc_path,
            relative_path=doc_path.name,
            material_type="pdf",
            text="Chapter 8 Transaction Exposure\nForward contracts are central.",
            status="extracted",
        )
    ]

    result = generate_lecture(docs, _config(tmp_path), NoFigureMainClient(), figure_client=FigureSpecClient())

    assert (result.output_dir / "assets" / "fig_1_1_forward_contract.png").exists()
    html = result.html_path.read_text(encoding="utf-8")
    assert 'src="assets/fig_1_1_forward_contract.png"' in html
    assert "Forward contract payoff as the future spot rate changes" in html
    assert "Transaction and Translation Exposure" in html
    assert "Module: M3.1 Lecture Ch08 Ch10 Transaction and Translation Exposure" in html


def test_sanitize_currency_symbols_prevents_mathjax_currency_errors() -> None:
    text = (
        "S = \\$1.50/€ and spot is $1.20/€ with $300,000 or €750,000. "
        "Cost is \\(\\text{\\$}4,545,455\\) and rate is $\\text{\\$}1.50/\\text{EUR}$."
    )

    sanitized = _sanitize_currency_symbols(text)

    assert "S = 1.50\\,\\$/\\euro" in sanitized
    assert "\\(1.20\\,\\$/\\euro\\)" in sanitized
    assert "\\(300,000\\,\\$\\)" in sanitized
    assert "\\(750,000\\,\\euro\\)" in sanitized
    assert "\\(4,545,455\\,\\$\\)" in sanitized
    assert "\\(1.50\\,\\$/\\euro\\)" in sanitized
    assert "€" not in sanitized
    assert "\\mathrm{USD" not in sanitized
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
