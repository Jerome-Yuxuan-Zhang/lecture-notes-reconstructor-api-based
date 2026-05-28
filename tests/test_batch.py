from __future__ import annotations

import json
from pathlib import Path

from lecture_reconstructor.batch import generate_batch, list_batch_folders
from lecture_reconstructor.models import GenerationConfig
from lecture_reconstructor.providers import get_provider


class DummyBatchClient:
    created = 0

    def __init__(self) -> None:
        DummyBatchClient.created += 1
        self.calls = 0

    def chat(self, messages: list[dict], **kwargs: object) -> str:
        self.calls += 1
        if self.calls == 1:
            return "outline"
        return json.dumps(
            {
                "lecture_html": "<h1>Glossary</h1><div class='formula-card'>$$x^{2}$$</div>",
                "self_check": "# self check",
            }
        )

    def ocr_image(self, image_path: Path) -> str:
        return image_path.name


def _config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        input_dir=tmp_path / "input",
        output_root=tmp_path / "outputs",
        provider=get_provider("Qwen"),
        api_key="test",
        project_name="course",
    )


def test_list_batch_folders_sorts_by_name(tmp_path: Path) -> None:
    root = tmp_path / "input"
    (root / "moduleB").mkdir(parents=True)
    (root / "moduleA").mkdir()
    (root / "z.txt").write_text("ignored", encoding="utf-8")

    assert [path.name for path in list_batch_folders(root)] == ["moduleA", "moduleB"]


def test_generate_batch_uses_fresh_client_per_folder(tmp_path: Path) -> None:
    DummyBatchClient.created = 0
    root = tmp_path / "input"
    (root / "module2").mkdir(parents=True)
    (root / "module1").mkdir()
    (root / "module1" / "a.md").write_text("A", encoding="utf-8")
    (root / "module2" / "b.md").write_text("B", encoding="utf-8")

    results = generate_batch(_config(tmp_path), DummyBatchClient)

    assert len(results) == 2
    assert DummyBatchClient.created == 2
    assert "module1" in results[0].output_dir.name
    assert "module2" in results[1].output_dir.name
