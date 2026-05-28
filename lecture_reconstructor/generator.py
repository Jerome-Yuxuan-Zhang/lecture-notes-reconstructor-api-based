from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from .charts import create_material_mix_chart
from .html_assets import ensure_full_html
from .models import GenerationConfig, GenerationResult, MaterialDocument
from .packaging import package_output


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.25,
        max_tokens: int = 8192,
        stream: bool = False,
    ) -> str:
        ...


LogFn = Callable[[str], None]


def generate_lecture(
    documents: list[MaterialDocument],
    config: GenerationConfig,
    client: ChatClient,
    *,
    prompt_template: str | None = None,
    log: LogFn | None = None,
) -> GenerationResult:
    errors: list[str] = []
    _log(log, "Creating output package folder.")
    output_dir = _create_output_dir(config.output_root, config.project_name)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    _log(log, "Writing source index.")
    source_index = [doc.to_dict() for doc in documents]
    (output_dir / "source_index.json").write_text(
        json.dumps(source_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    chart_path = create_material_mix_chart(documents, assets_dir)
    if chart_path:
        _log(log, f"Created chart asset: {chart_path.name}")

    material_digest = _build_material_digest(documents)
    prompt = prompt_template or _load_prompt_template()

    _log(log, "Generating structure draft.")
    outline = client.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": _outline_prompt(material_digest)},
        ],
        temperature=config.temperature,
        max_tokens=min(config.max_tokens, 4096),
        stream=config.stream,
    )

    _log(log, "Generating lecture HTML and self-check.")
    response = client.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "assistant", "content": f"结构草案如下：\n{outline}"},
            {"role": "user", "content": _lecture_prompt(material_digest, chart_path)},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        stream=config.stream,
    )

    lecture_html, self_check = _parse_generation_response(response)
    lecture_html = ensure_full_html(lecture_html, title=config.project_name)
    if chart_path and "fig_0_1_material_mix.png" not in lecture_html:
        lecture_html = lecture_html.replace(
            "</main>",
            '<figure><img src="assets/fig_0_1_material_mix.png" alt="Material type coverage"></figure>\n</main>',
        )

    html_path = output_dir / "lecture.html"
    html_path.write_text(lecture_html, encoding="utf-8")
    self_check_path = output_dir / "self_check.md"
    self_check_path.write_text(self_check or _fallback_self_check(documents), encoding="utf-8")

    coverage_summary = _coverage_summary(documents)
    manifest = {
        "project_name": config.project_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "provider": config.provider.to_dict(),
        "input_dir": str(config.input_dir),
        "files": len(documents),
        "coverage_summary": coverage_summary,
        "errors": errors,
    }
    manifest["provider"]["api_key_env"] = config.provider.api_key_env
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "run.log").write_text("\n".join(_runtime_lines(documents, errors)), encoding="utf-8")

    _log(log, "Creating zip package.")
    zip_path = package_output(output_dir)
    return GenerationResult(
        output_dir=output_dir,
        html_path=html_path,
        zip_path=zip_path,
        errors=errors,
        coverage_summary=coverage_summary,
    )


def _create_output_dir(output_root: Path, project_name: str) -> Path:
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    safe_project = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", project_name).strip("_") or "lecture"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = output_root / f"{stamp}_{safe_project}"
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{stamp}_{safe_project}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _load_prompt_template() -> str:
    template = Path(__file__).resolve().parent.parent / "templates" / "lecture_prompt.md"
    if template.exists():
        return template.read_text(encoding="utf-8")
    return "你是讲义重构助手。生成完整中文 HTML 讲义和 HTML 外部自检。"


def _build_material_digest(documents: list[MaterialDocument], limit_per_doc: int = 8000) -> str:
    blocks: list[str] = []
    for index, doc in enumerate(documents, start=1):
        text = doc.text.strip() or "[无可抽取文字]"
        if len(text) > limit_per_doc:
            text = text[:limit_per_doc] + "\n[该文件内容过长，已截断供本轮生成使用。]"
        warning = f"\nWarnings: {'; '.join(doc.warnings)}" if doc.warnings else ""
        blocks.append(
            f"### Source {index}: {doc.relative_path}\n"
            f"Type: {doc.material_type}\nStatus: {doc.status}{warning}\n\n{text}"
        )
    return "\n\n".join(blocks)


def _outline_prompt(material_digest: str) -> str:
    return (
        "请根据以下课程材料建立讲义重构大纲、术语候选表和逐页/逐文件覆盖清单。"
        "不要输出最终 HTML，只输出结构草案。\n\n"
        f"{material_digest}"
    )


def _lecture_prompt(material_digest: str, chart_path: Path | None) -> str:
    chart_hint = ""
    if chart_path:
        chart_hint = (
            "\n程序已经生成材料类型覆盖图：assets/fig_0_1_material_mix.png。"
            "如有合适位置，可在 HTML 中用相对路径引用。"
        )
    return (
        "请生成最终交付物。必须只返回一个 JSON 对象，键为 lecture_html 和 self_check。"
        "lecture_html 是完整 HTML 文档，self_check 是 HTML 外部的“自检 / 覆盖核对”。"
        "HTML 内部顺序必须是：术语表、10 分钟速记区、主体理论闭环重构、必要前置补全、全部例题与习题完整解答。"
        "公式块、卡片、字体、MathJax、assets 相对路径、逐页覆盖核对都要遵守系统规范。"
        f"{chart_hint}\n\n课程材料如下：\n{material_digest}"
    )


def _parse_generation_response(response: str) -> tuple[str, str]:
    text = response.strip()
    json_text = _extract_json(text)
    if json_text:
        try:
            data = json.loads(json_text)
            return str(data.get("lecture_html", "")), str(data.get("self_check", ""))
        except json.JSONDecodeError:
            pass

    html_match = re.search(r"```html\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    lecture_html = html_match.group(1).strip() if html_match else text
    self_check = ""
    marker = "自检 / 覆盖核对"
    if marker in lecture_html and "</html>" in lecture_html.lower():
        tail_index = lecture_html.lower().rfind("</html>") + len("</html>")
        self_check = lecture_html[tail_index:].strip()
        lecture_html = lecture_html[:tail_index]
    return lecture_html, self_check


def _extract_json(text: str) -> str | None:
    fenced = re.search(r"```json\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    return None


def _coverage_summary(documents: list[MaterialDocument]) -> dict[str, object]:
    statuses = Counter(doc.status for doc in documents)
    types = Counter(doc.material_type for doc in documents)
    return {
        "total_files": len(documents),
        "by_status": dict(statuses),
        "by_type": dict(types),
        "warning_count": sum(len(doc.warnings) for doc in documents),
    }


def _fallback_self_check(documents: list[MaterialDocument]) -> str:
    rows = [
        "# 自检 / 覆盖核对",
        "",
        "| 页码/文件 | 所属模块 | 主要知识点 | 讲义对应位置 | 图表或例题是否已重构 | 覆盖状态 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for doc in documents:
        rows.append(
            f"| {doc.relative_path} | 待模型细分 | 已纳入生成材料 | lecture.html | 见正文 | "
            f"{'覆盖完整' if doc.status == 'extracted' else '需重点复习'} |"
        )
    rows.extend(
        [
            "",
            "- 术语表、星级、公式卡片、特殊块、关键词、英文注释、直白解释、易混对照、MathJax、assets 图表和版式需在人工验收时复核。",
        ]
    )
    return "\n".join(rows)


def _runtime_lines(documents: list[MaterialDocument], errors: list[str]) -> list[str]:
    lines = [f"Files processed: {len(documents)}"]
    lines.extend(f"{doc.status}: {doc.relative_path}" for doc in documents)
    lines.extend(f"ERROR: {error}" for error in errors)
    return lines


def _log(log: LogFn | None, message: str) -> None:
    if log:
        log(message)
