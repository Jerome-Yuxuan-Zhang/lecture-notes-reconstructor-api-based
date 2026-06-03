from __future__ import annotations

from pathlib import Path

from lecture_reconstructor.material import extract_materials, scan_materials
from lecture_reconstructor.models import GenerationConfig
from lecture_reconstructor.providers import get_provider


class DummyVisionClient:
    def ocr_image(self, image_path: Path) -> str:
        return f"OCR:{image_path.name}"


def _config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        input_dir=tmp_path,
        output_root=tmp_path / "outputs",
        provider=get_provider("Qwen"),
        api_key="test",
    )


def test_scan_materials_recurses_and_filters(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.txt").write_text("B", encoding="utf-8")
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / "textbook.md").write_text("book", encoding="utf-8")
    (tmp_path / "20260528_153603_lecture").mkdir()
    (tmp_path / "20260528_153603_lecture" / "self_check.md").write_text("old output", encoding="utf-8")
    (tmp_path / "ignore.exe").write_text("x", encoding="utf-8")

    docs = scan_materials(tmp_path)

    assert [doc.relative_path for doc in docs] == ["a.md", "nested/b.txt", "reference/textbook.md"]
    assert {doc.material_type for doc in docs} == {"md", "txt"}
    roles = {doc.relative_path: doc.role for doc in docs}
    assert roles["a.md"] == "primary"
    assert roles["reference/textbook.md"] == "reference"


def test_extract_text_and_image_ocr(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"not really an image but unused by dummy")
    docs = scan_materials(tmp_path)

    extracted = extract_materials(docs, DummyVisionClient(), _config(tmp_path))

    by_name = {doc.relative_path: doc for doc in extracted}
    assert by_name["note.txt"].text == "hello"
    assert by_name["image.png"].text == "OCR:image.png"
    assert by_name["image.png"].status == "extracted"
