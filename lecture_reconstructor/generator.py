from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

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
    scripts_dir = output_dir / f"script4{_safe_name(config.project_name)}"
    assets_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    _log(log, "Writing source index.")
    source_index = [doc.to_dict() for doc in documents]
    (output_dir / "source_index.json").write_text(
        json.dumps(source_index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
            {"role": "user", "content": _lecture_prompt(material_digest)},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        stream=config.stream,
    )

    lecture_html, self_check, figure_scripts = _parse_generation_response(response)
    lecture_html = _sanitize_currency_symbols(lecture_html)
    self_check = _sanitize_currency_symbols(self_check)
    lecture_html = ensure_full_html(lecture_html, title=config.project_name)
    script_paths = _write_figure_scripts(scripts_dir, figure_scripts)
    script_errors = _run_figure_scripts(script_paths, output_dir)
    errors.extend(script_errors)
    errors.extend(_missing_asset_errors(lecture_html, output_dir))

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
    safe_project = _safe_name(project_name)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = output_root / f"{stamp}_{safe_project}"
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{stamp}_{safe_project}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value).strip("_") or "lecture"


def _load_prompt_template() -> str:
    root = Path(__file__).resolve().parent.parent
    agents = root / "AGENTS.md"
    if agents.exists():
        prompt = agents.read_text(encoding="utf-8")
        vocab = root / "vocab_5500.txt"
        if vocab.exists():
            prompt += (
                "\n\n---\n\n"
                "## 考研英语二 5500 词注释辅助\n\n"
                "项目根目录存在 `vocab_5500.txt`。生成讲义时，英文注释规则以 `AGENTS.md` 为准："
                "5500 大纲词之外的英文词汇需要补中文注释。该词表作为常用词白名单使用，"
                "不要把词表全文输出到讲义正文。\n"
            )
        return prompt
    template = root / "templates" / "lecture_prompt.md"
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


def _lecture_prompt(material_digest: str) -> str:
    return (
        "请生成最终交付物。为避免 JSON 转义损坏，必须严格按下面的分隔符格式返回，不要包裹 Markdown 代码块，"
        "不要输出解释文字。\n\n"
        "<<<LECTURE_HTML>>>\n"
        "这里放完整 lecture.html 内容\n"
        "<<<END_LECTURE_HTML>>>\n\n"
        "<<<SELF_CHECK>>>\n"
        "这里放 HTML 外部的“自检 / 覆盖核对”Markdown 内容\n"
        "<<<END_SELF_CHECK>>>\n\n"
        "如需要课程内容图表，每个图表脚本用一个脚本块。路径必须是相对路径，例如 chapter_8/fig_8_1_forward_payoff.py。"
        "脚本必须完整可运行，用 matplotlib + seaborn 生成对应 assets 图片。示例：\n"
        "<<<FIGURE_SCRIPT:chapter_8/fig_8_1_forward_payoff.py>>>\n"
        "import matplotlib.pyplot as plt\n"
        "import seaborn as sns\n"
        "...\n"
        "plt.savefig('assets/fig_8_1_forward_payoff.png', dpi=200, bbox_inches='tight')\n"
        "<<<END_FIGURE_SCRIPT>>>\n\n"
        "如果本章没有课程内容图表，不要写 FIGURE_SCRIPT 块。不要为材料来源分布、文件类型分布等元信息造图；图表只服务课程内容本身。"
        "HTML 内部顺序必须是：术语表、10 分钟速记区、主体理论闭环重构、必要前置补全、全部例题与习题完整解答。"
        "公式块、卡片、字体、MathJax、assets 相对路径、逐页覆盖核对都要遵守系统规范。"
        "公式里所有货币符号必须放进 \\text{} 并优先改用三字母货币代码；尤其不要写 S = \\$1.50/€，"
        "也不要写 \\text{€}、\\text{£}、\\text{¥}。应写 S = \\text{\\$}1.50/\\text{EUR} "
        "或 S = 1.50\\ \\text{USD}/\\text{EUR}。"
        "涉及 €、£、¥、$ 的金额、汇率、合约规模、计算过程都要做同样处理。\n\n"
        "课程材料如下：\n"
        f"{material_digest}"
    )


def _parse_generation_response(response: str) -> tuple[str, str, list[dict[str, str]]]:
    text = response.strip()
    marker_result = _parse_marker_response(text)
    if marker_result is not None:
        return marker_result

    json_text = _extract_json(text)
    if json_text:
        try:
            data = json.loads(json_text)
            scripts = data.get("figure_scripts", [])
            if not isinstance(scripts, list):
                scripts = []
            return str(data.get("lecture_html", "")), str(data.get("self_check", "")), scripts
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
    return lecture_html, self_check, []


def _parse_marker_response(text: str) -> tuple[str, str, list[dict[str, str]]] | None:
    lecture_match = re.search(
        r"<<<LECTURE_HTML>>>\s*(.*?)\s*<<<END_LECTURE_HTML>>>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not lecture_match:
        return None

    self_check_match = re.search(
        r"<<<SELF_CHECK>>>\s*(.*?)\s*<<<END_SELF_CHECK>>>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    scripts: list[dict[str, str]] = []
    for script_match in re.finditer(
        r"<<<FIGURE_SCRIPT:([^>\r\n]+)>>>\s*(.*?)\s*<<<END_FIGURE_SCRIPT>>>",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        scripts.append({"path": script_match.group(1).strip(), "code": script_match.group(2).strip()})

    return (
        lecture_match.group(1).strip(),
        self_check_match.group(1).strip() if self_check_match else "",
        scripts,
    )


def _write_figure_scripts(scripts_dir: Path, figure_scripts: list[dict[str, str]]) -> list[Path]:
    readme = scripts_dir / "README.md"
    readme.write_text(
        "# Figure generation scripts\n\n"
        "This folder stores Python scripts used to regenerate figures referenced by the lecture HTML.\n"
        "Scripts should write image files into the sibling `assets/` folder using relative paths.\n",
        encoding="utf-8",
    )
    script_paths: list[Path] = []
    for index, item in enumerate(figure_scripts, start=1):
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or f"fig_script_{index}.py")
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        safe_parts = [_safe_name(part) for part in Path(raw_path).parts if part not in {"", ".", ".."}]
        if not safe_parts:
            safe_parts = [f"fig_script_{index}.py"]
        if not safe_parts[-1].endswith(".py"):
            safe_parts[-1] = f"{safe_parts[-1]}.py"
        script_path = scripts_dir.joinpath(*safe_parts)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(code + "\n", encoding="utf-8")
        script_paths.append(script_path)
    return script_paths


def _run_figure_scripts(script_paths: list[Path], output_dir: Path) -> list[str]:
    errors: list[str] = []
    if not script_paths:
        return errors
    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    for script_path in script_paths:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=output_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            errors.append(
                f"Figure script failed: {script_path.relative_to(output_dir)}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
    return errors


def _missing_asset_errors(lecture_html: str, output_dir: Path) -> list[str]:
    errors: list[str] = []
    refs = sorted(set(re.findall(r"""src=["'](assets/[^"']+)["']""", lecture_html)))
    for ref in refs:
        asset_path = output_dir / ref
        if not asset_path.exists():
            errors.append(f"Referenced asset was not generated: {ref}")
    return errors


def _extract_json(text: str) -> str | None:
    fenced = re.search(r"```json\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    return None


def _sanitize_currency_symbols(text: str) -> str:
    text = re.sub(
        r"\\\$(\d[\d,]*(?:\.\d+)?)(\s*/\s*)([€¥£])",
        lambda match: rf"\text{{\$}}{match.group(1)}/\text{{{_currency_code(match.group(3))}}}",
        text,
    )
    text = re.sub(
        r"(?<!\\)\$(\d[\d,]*(?:\.\d+)?)(\s*/\s*)([€¥£])",
        lambda match: rf"\(\text{{\$}}{match.group(1)}/\text{{{_currency_code(match.group(3))}}}\)",
        text,
    )
    text = re.sub(
        r"(?<!\\)\$(\d[\d,]*(?:\.\d+)?)",
        lambda match: rf"\(\text{{\$}}{match.group(1)}\)",
        text,
    )
    text = re.sub(
        r"(?<!\\)([€¥£])(\d[\d,]*(?:\.\d+)?)",
        lambda match: rf"\(\text{{{_currency_code(match.group(1))}}}{match.group(2)}\)",
        text,
    )
    for symbol, code in {"€": "EUR", "£": "GBP", "¥": "JPY"}.items():
        text = text.replace(rf"\text{{{symbol}}}", rf"\text{{{code}}}")
        text = text.replace(symbol, code)
    return text


def _currency_code(symbol: str) -> str:
    return {"€": "EUR", "£": "GBP", "¥": "JPY"}.get(symbol, symbol)


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
