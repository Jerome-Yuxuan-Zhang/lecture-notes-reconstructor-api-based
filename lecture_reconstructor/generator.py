from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from .html_assets import ensure_full_html
from .models import GenerationConfig, GenerationResult, MaterialDocument
from .packaging import package_output
from .reference_search import format_reference_hits, reference_index, search_references


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
FIGURE_SCRIPT_TIMEOUT_SECONDS = 60


@dataclass(slots=True)
class FigureRunFailure:
    script_path: Path
    message: str
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    def format(self, output_dir: Path) -> str:
        reason = "timed out" if self.timed_out else "failed"
        return (
            f"Figure script {reason}: {self.script_path.relative_to(output_dir)}\n"
            f"{self.message}\nSTDOUT:\n{self.stdout}\nSTDERR:\n{self.stderr}"
        )


def generate_lecture(
    documents: list[MaterialDocument],
    config: GenerationConfig,
    client: ChatClient,
    *,
    figure_client: ChatClient | None = None,
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

    outline_digest = _build_material_digest(documents, include_reference_excerpts=False)
    prompt = prompt_template or _load_prompt_template()

    _log(log, "Generating structure draft.")
    outline = client.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": _outline_prompt(outline_digest)},
        ],
        temperature=config.temperature,
        max_tokens=min(config.max_tokens, 4096),
        stream=config.stream,
    )

    _log(log, "Searching reference materials for relevant backup excerpts.")
    reference_query = _build_reference_query(documents, outline)
    reference_hits = search_references(documents, reference_query)
    (output_dir / "reference_hits.json").write_text(
        json.dumps([hit.to_dict() for hit in reference_hits], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    material_digest = _build_material_digest(documents, reference_hits=reference_hits)

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

    inferred_title = _infer_course_title(documents, config.project_name)
    lecture_html, self_check, figure_scripts = _parse_generation_response(response)
    if figure_client is not None:
        _log(log, "Generating figure scripts with the figure API.")
        figure_response = figure_client.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "assistant", "content": f"Structure draft:\n{outline}"},
                {"role": "user", "content": _figure_script_prompt(material_digest, lecture_html)},
            ],
            temperature=config.temperature,
            max_tokens=min(config.max_tokens, 65536),
            stream=config.stream,
        )
        figure_scripts, figure_specs = _parse_figure_script_response(figure_response)
        lecture_html = _inject_missing_figures(lecture_html, figure_specs)
    lecture_html = _sanitize_currency_symbols(lecture_html)
    self_check = _sanitize_currency_symbols(self_check)
    lecture_html = _ensure_bilingual_heading(lecture_html, inferred_title)
    lecture_html = ensure_full_html(lecture_html, title=inferred_title)
    script_paths = _write_figure_scripts(scripts_dir, figure_scripts)
    script_errors = _repair_non_ascii_figure_scripts(
        script_paths,
        output_dir,
        figure_client=figure_client,
        config=config,
        log=log,
    )
    errors.extend(script_errors)
    script_errors = _run_figure_scripts(
        script_paths,
        output_dir,
        figure_client=figure_client,
        config=config,
        log=log,
    )
    errors.extend(script_errors)
    errors.extend(_missing_asset_errors(lecture_html, output_dir))

    html_path = output_dir / _html_filename(inferred_title)
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


def _html_filename(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", value).strip().rstrip(".") or "lecture"
    return f"{name}.html"


def _infer_course_title(documents: list[MaterialDocument], fallback: str) -> str:
    fallback_title = _topic_title_from_value(fallback)
    if fallback_title:
        return fallback_title
    candidates: list[str] = []
    for doc in documents:
        stem = Path(doc.relative_path).stem
        cleaned = _clean_title_candidate(stem)
        if cleaned:
            candidates.append(cleaned)
        for line in doc.text.splitlines()[:40]:
            line = line.strip()
            if not line or len(line) > 120:
                continue
            if re.search(r"(module|chapter|lecture|workshop|transaction|translation|exposure|风险|汇率|金融)", line, re.IGNORECASE):
                cleaned_line = _clean_title_candidate(line)
                if cleaned_line:
                    candidates.append(cleaned_line)
    if candidates:
        return max(candidates, key=_title_score)
    return fallback.strip() or "Lecture"


def _topic_title_from_value(value: str) -> str | None:
    raw_match = re.search(r"\bTopic[_\s-]*(\d+)_-_(.+)$", value, re.IGNORECASE)
    if raw_match:
        title = raw_match.group(2).replace("_", " ")
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            return f"Topic {int(raw_match.group(1))} - {title}"
    normalized = re.sub(r"[_-]+", " ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    match = re.search(r"\bTopic\s+(\d+)\s+(.+)$", normalized, re.IGNORECASE)
    if not match:
        return None
    title = match.group(2).strip()
    title = re.sub(r"^(lecture|module)\s+", "", title, flags=re.IGNORECASE).strip()
    if title:
        return f"Topic {int(match.group(1))} - {title}"
    return None


def _clean_title_candidate(value: str) -> str:
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"\b(pdf|pptx|docx|xlsx|csv|solution|reference|formula|sheet)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    return value


def _title_score(value: str) -> tuple[int, int]:
    keywords = re.findall(
        r"(module|chapter|lecture|transaction|translation|exposure|international|finance|风险|汇率|金融|交易|折算)",
        value,
        flags=re.IGNORECASE,
    )
    length_score = -abs(len(value) - 70)
    return len(keywords), length_score


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


def _build_material_digest(
    documents: list[MaterialDocument],
    limit_per_doc: int = 80000,
    *,
    include_reference_excerpts: bool = True,
    reference_hits: list | None = None,
) -> str:
    primary_blocks: list[str] = []
    for index, doc in enumerate(documents, start=1):
        is_reference = doc.role == "reference"
        if is_reference:
            continue
        doc_limit = limit_per_doc
        text = doc.text.strip() or "[无可抽取文字]"
        if len(text) > doc_limit:
            text = text[:doc_limit] + "\n[该文件内容过长，已截断供本轮生成使用。]"
        warning = f"\nWarnings: {'; '.join(doc.warnings)}" if doc.warnings else ""
        block = (
            f"### Source {index}: {doc.relative_path}\n"
            f"Type: {doc.material_type}\nRole: {doc.role}\nStatus: {doc.status}{warning}\n\n{text}"
        )
        primary_blocks.append(block)

    sections: list[str] = []
    if primary_blocks:
        sections.append(
            "## PRIMARY MATERIALS / 主讲材料\n"
            "These files define the lecture scope and must be covered in self-check.\n\n"
            + "\n\n".join(primary_blocks)
        )
    index = reference_index(documents)
    if index:
        sections.append(index)
    if include_reference_excerpts:
        sections.append(format_reference_hits(reference_hits or []))
    return "\n\n".join(sections)


def _build_reference_query(documents: list[MaterialDocument], outline: str, limit_per_doc: int = 12000) -> str:
    primary_parts = [
        f"{doc.relative_path}\n{doc.text[:limit_per_doc]}"
        for doc in documents
        if doc.role != "reference" and doc.text.strip()
    ]
    return (
        "Search reference materials for textbook passages that deepen concepts required by this outline "
        "and these primary lecture materials. Prioritize exact English terms and bilingual finance terms.\n\n"
        f"OUTLINE:\n{outline}\n\n"
        "PRIMARY MATERIALS:\n"
        + "\n\n".join(primary_parts)
    )


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
        "讲义正文中凡是需要图表的位置，必须先插入 <figure> 和 <img src=\"assets/fig_章号_序号_简述.png\"> 占位，"
        "并在 figcaption 或邻近段落清楚说明该图要表达什么。不要让图表只存在于 Python 脚本而 HTML 不引用。"
        "公式块、卡片、字体、MathJax、assets 相对路径、逐页覆盖核对都要遵守系统规范。"
        "所有数学只允许使用 \\(...\\) 和 \\[...\\] 分隔符；不要使用 $...$ 或 $$...$$。"
        "MathJax 必须使用 tex-chtml.js，加载 [tex]/unicode，并定义 \\pounds、\\euro、\\rupee、\\won、\\ruble、\\bitcoin 宏。"
        "公式里所有货币符号必须使用 MathJax 货币宏；尤其不要写 S = \\$1.50/€，"
        "也不要写裸 €、£、¥ 或 \\text{\\$}、\\text{$}、\\text{€}、\\text{£}、\\text{¥}。"
        "应写 S = 1.50\\,\\$/\\euro 或 S = 1.50\\,\\mathrm{USD}/\\euro。"
        "涉及 €、£、¥、$ 的金额、汇率、合约规模、计算过程都要做同样处理。\n\n"
        "课程材料如下：\n"
        f"{material_digest}"
    )


def _figure_script_prompt(material_digest: str, lecture_html: str) -> str:
    figure_targets = _figure_targets_summary(lecture_html)
    return (
        "请只生成图表 Python 脚本，不要生成或改写 HTML。DeepSeek 已经先生成 lecture.html，下面列出 HTML 中每个 "
        "assets 图片引用的位置和附近教学上下文；你必须为每个引用生成对应 Python 脚本。如果 HTML 中没有 assets 图片引用，"
        "你必须根据讲义内容和课程材料主动提出 1-3 张最必要的课程内容图，并为每张图同时返回 FIGURE_SPEC 和 FIGURE_SCRIPT。"
        "必须按以下分隔符返回。\n\n"
        "<<<FIGURE_SPEC>>>\n"
        "path: assets/fig_8_1_forward_payoff.png\n"
        "alt: Forward payoff diagram\n"
        "caption: 远期合约多头和空头的损益随到期即期汇率变化\n"
        "insert_after: 远期合约\n"
        "<<<END_FIGURE_SPEC>>>\n\n"
        "<<<FIGURE_SCRIPT:chapter_8/fig_8_1_forward_payoff.py>>>\n"
        "完整 Python 代码，使用 matplotlib + seaborn，保存到 assets/fig_8_1_forward_payoff.png\n"
        "<<<END_FIGURE_SCRIPT>>>\n\n"
        "要求：脚本必须可独立运行；必须创建 assets 目录；不得生成材料来源分布、文件类型分布等元信息图；"
        "只画课程概念、公式关系、损益曲线、流程或表格重构需要的图。保存路径必须和 HTML 引用的 assets 路径完全一致。\n\n"
        "Hard rule for every Python script: all visible plot text must be English-only ASCII. "
        "Do not put Chinese, CJK characters, mojibake, full-width punctuation, or Chinese font setup in Python figure scripts. "
        "Use labels such as Financial Markets, Depositors, Flow of Funds, Principal + Interest.\n\n"
        "HTML 图表目标和上下文如下：\n"
        f"{figure_targets}\n\n"
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


def _figure_targets_summary(lecture_html: str) -> str:
    refs = list(re.finditer(r"""src=["'](assets/[^"']+)["']""", lecture_html, re.IGNORECASE))
    if not refs:
        return (
            "HTML 中没有 assets 图片引用。请主动提出 1-3 张最必要的课程内容图，返回 FIGURE_SPEC 和 FIGURE_SCRIPT；"
            "软件会根据 FIGURE_SPEC 自动把 <figure> 插入 lecture.html。"
        )
    lines: list[str] = []
    for index, match in enumerate(refs, start=1):
        ref = match.group(1)
        start = max(0, match.start() - 900)
        end = min(len(lecture_html), match.end() + 900)
        context = re.sub(r"<[^>]+>", " ", lecture_html[start:end])
        context = re.sub(r"\s+", " ", context).strip()
        lines.append(f"{index}. {ref}\nContext: {context}")
    return "\n\n".join(lines)


def _parse_figure_script_response(response: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    marker_result = _parse_marker_response(response.strip())
    if marker_result is not None:
        return marker_result[2], _parse_figure_specs(response)
    json_text = _extract_json(response.strip())
    if json_text:
        try:
            data = json.loads(json_text)
            scripts = data.get("figure_scripts", [])
            specs = data.get("figure_specs", [])
            return scripts if isinstance(scripts, list) else [], specs if isinstance(specs, list) else []
        except json.JSONDecodeError:
            return [], []
    scripts: list[dict[str, str]] = []
    for script_match in re.finditer(
        r"<<<FIGURE_SCRIPT:([^>\r\n]+)>>>\s*(.*?)\s*<<<END_FIGURE_SCRIPT>>>",
        response,
        re.DOTALL | re.IGNORECASE,
    ):
        scripts.append({"path": script_match.group(1).strip(), "code": script_match.group(2).strip()})
    return scripts, _parse_figure_specs(response)


def _parse_figure_specs(response: str) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for spec_match in re.finditer(
        r"<<<FIGURE_SPEC>>>\s*(.*?)\s*<<<END_FIGURE_SPEC>>>",
        response,
        re.DOTALL | re.IGNORECASE,
    ):
        spec: dict[str, str] = {}
        for line in spec_match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            spec[key.strip().lower()] = value.strip()
        if spec.get("path"):
            specs.append(spec)
    return specs


def _inject_missing_figures(lecture_html: str, figure_specs: list[dict[str, str]]) -> str:
    existing_refs = set(re.findall(r"""src=["'](assets/[^"']+)["']""", lecture_html, re.IGNORECASE))
    additions: list[str] = []
    for spec in figure_specs:
        path = spec.get("path", "").replace("\\", "/")
        if not path.startswith("assets/") or path in existing_refs:
            continue
        alt = spec.get("alt") or spec.get("caption") or Path(path).stem
        caption = spec.get("caption") or alt
        figure_html = (
            "\n<figure>\n"
            f'  <img src="{path}" alt="{alt}">\n'
            f"  <figcaption>{caption}</figcaption>\n"
            "</figure>\n"
        )
        marker = spec.get("insert_after", "").strip()
        if marker and marker in lecture_html:
            insert_at = lecture_html.find(marker) + len(marker)
            lecture_html = lecture_html[:insert_at] + figure_html + lecture_html[insert_at:]
            existing_refs.add(path)
        else:
            additions.append(figure_html)
    if additions:
        if re.search(r"</body>", lecture_html, re.IGNORECASE):
            lecture_html = re.sub(r"</body>", "\n".join(additions) + "\n</body>", lecture_html, count=1, flags=re.IGNORECASE)
        else:
            lecture_html += "\n" + "\n".join(additions)
    return lecture_html


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


def _run_figure_scripts(
    script_paths: list[Path],
    output_dir: Path,
    *,
    figure_client: ChatClient | None = None,
    config: GenerationConfig | None = None,
    log: LogFn | None = None,
) -> list[str]:
    errors: list[str] = []
    if not script_paths:
        return errors
    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    for script_path in script_paths:
        failure = _run_single_figure_script(script_path, output_dir, env)
        if failure is None:
            continue
        if figure_client is not None:
            _log(log, f"Figure script failed; asking figure API to debug {script_path.name}.")
            fixed = _debug_figure_script(script_path, output_dir, failure, figure_client, config)
            if fixed:
                script_path.write_text(fixed + "\n", encoding="utf-8")
                retry_failure = _run_single_figure_script(script_path, output_dir, env)
                if retry_failure is None:
                    _log(log, f"Figure script repaired and executed: {script_path.name}.")
                    continue
                errors.append(
                    failure.format(output_dir)
                    + "\n\nRetry after figure API debug also failed:\n"
                    + retry_failure.format(output_dir)
                )
                continue
            errors.append(failure.format(output_dir) + "\n\nFigure API did not return a usable repaired script.")
            continue
        errors.append(failure.format(output_dir))
    return errors


def _repair_non_ascii_figure_scripts(
    script_paths: list[Path],
    output_dir: Path,
    *,
    figure_client: ChatClient | None = None,
    config: GenerationConfig | None = None,
    log: LogFn | None = None,
) -> list[str]:
    errors: list[str] = []
    for script_path in script_paths:
        code = script_path.read_text(encoding="utf-8", errors="replace")
        report = _non_ascii_report(code)
        if not report:
            continue
        if figure_client is None:
            errors.append(
                f"Figure script contains non-ASCII plot text and no figure API is available for repair: "
                f"{script_path.relative_to(output_dir)}\n{report}"
            )
            continue
        _log(log, f"Figure script contains non-ASCII text; asking figure API to rewrite {script_path.name}.")
        failure = FigureRunFailure(
            script_path=script_path,
            message=(
                "Non-ASCII characters were detected before execution. "
                "Rewrite every visible label/title/annotation/legend in English-only ASCII."
            ),
            stderr=report,
        )
        fixed = _debug_figure_script(script_path, output_dir, failure, figure_client, config)
        if not fixed:
            errors.append(
                f"Figure API did not return a usable ASCII-only repair for {script_path.relative_to(output_dir)}.\n{report}"
            )
            continue
        fixed_report = _non_ascii_report(fixed)
        if fixed_report:
            errors.append(
                f"Figure API repair still contains non-ASCII text for {script_path.relative_to(output_dir)}.\n"
                f"{fixed_report}"
            )
            continue
        script_path.write_text(fixed + "\n", encoding="utf-8")
    return errors


def _non_ascii_report(text: str, max_items: int = 12) -> str:
    items: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        chars = sorted({char for char in line if ord(char) > 127})
        if chars:
            sample = "".join(chars[:12])
            items.append(f"line {line_number}: {sample} | {line.strip()[:160]}")
            if len(items) >= max_items:
                break
    return "\n".join(items)


def _run_single_figure_script(script_path: Path, output_dir: Path, env: dict[str, str]) -> FigureRunFailure | None:
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=output_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=FIGURE_SCRIPT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_process_output(exc.stdout)
        stderr = _coerce_process_output(exc.stderr)
        return FigureRunFailure(
            script_path=script_path,
            message=f"Timed out after {FIGURE_SCRIPT_TIMEOUT_SECONDS} seconds.",
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )

    if result.returncode == 0:
        return None
    return FigureRunFailure(
        script_path=script_path,
        message=f"Exited with return code {result.returncode}.",
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _coerce_process_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _debug_figure_script(
    script_path: Path,
    output_dir: Path,
    failure: FigureRunFailure,
    figure_client: ChatClient,
    config: GenerationConfig | None,
) -> str | None:
    original_code = script_path.read_text(encoding="utf-8", errors="replace")
    response = figure_client.chat(
        [
            {
                "role": "system",
                "content": (
                    "You repair Python matplotlib/seaborn figure scripts. Return only one repaired "
                    "FIGURE_SCRIPT block. The script must terminate quickly, create required directories, "
                    "save the expected assets image, use MPLBACKEND=Agg-compatible code, and avoid network, "
                    "interactive windows, infinite loops, plt.show(), input(), or long font downloads. "
                    "All visible plot text must be English-only ASCII; remove Chinese, CJK characters, "
                    "mojibake, full-width punctuation, and Chinese font setup."
                ),
            },
            {
                "role": "user",
                "content": _figure_debug_prompt(script_path, output_dir, original_code, failure),
            },
        ],
        temperature=(config.temperature if config else 0.2),
        max_tokens=min(config.max_tokens if config else 8192, 32768),
        stream=False,
    )
    scripts, _ = _parse_figure_script_response(response)
    if scripts:
        code = str(scripts[0].get("code") or "").strip()
        return code or None
    match = re.search(r"```(?:python)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    stripped = response.strip()
    if "import " in stripped and "savefig" in stripped:
        return stripped
    return None


def _figure_debug_prompt(script_path: Path, output_dir: Path, original_code: str, failure: FigureRunFailure) -> str:
    relative_script = script_path.relative_to(output_dir).as_posix()
    expected_assets = sorted(set(re.findall(r"""assets[/\\][^"')\s]+\.png""", original_code)))
    expected_note = "\n".join(f"- {path.replace(chr(92), '/')}" for path in expected_assets) or "- infer from savefig path"
    return (
        "Repair this figure script. Keep the same script path and intended image outputs.\n"
        "Return exactly this format:\n\n"
        f"<<<FIGURE_SCRIPT:{relative_script}>>>\n"
        "# complete repaired Python code here\n"
        "<<<END_FIGURE_SCRIPT>>>\n\n"
        "Hard requirements:\n"
        f"- Must finish within {FIGURE_SCRIPT_TIMEOUT_SECONDS} seconds on retry.\n"
        "- Must use only local computation; no downloads, no web requests, no interactive input.\n"
        "- Must not call plt.show().\n"
        "- Must create the assets directory before saving.\n"
        "- Must contain only ASCII characters in the repaired Python source.\n"
        "- All visible labels, titles, legends, and annotations must be English-only ASCII.\n"
        "- Must save these expected image paths if present:\n"
        f"{expected_note}\n\n"
        "Failure report:\n"
        f"{failure.format(output_dir)}\n\n"
        "Original script:\n"
        "```python\n"
        f"{original_code}\n"
        "```"
    )


def _ensure_bilingual_heading(lecture_html: str, project_name: str) -> str:
    heading = _heading_html(project_name)
    if "lecture-module-heading" in lecture_html:
        return re.sub(
            r"<header\b[^>]*class=[\"'][^\"']*lecture-module-heading[^\"']*[\"'][^>]*>.*?</header>",
            heading,
            lecture_html,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return _insert_heading(lecture_html, heading)


def _heading_html(project_name: str) -> str:
    safe_title = project_name.strip() or "Lecture"
    return (
        '<header class="lecture-module-heading">\n'
        f"  <h1>{safe_title}</h1>\n"
        "</header>\n"
    )


def _insert_heading(lecture_html: str, heading: str) -> str:
    if re.search(r"<main\b[^>]*>", lecture_html, re.IGNORECASE):
        return re.sub(r"(<main\b[^>]*>)", rf"\1\n{heading}", lecture_html, count=1, flags=re.IGNORECASE)
    if re.search(r"<body\b[^>]*>", lecture_html, re.IGNORECASE):
        return re.sub(r"(<body\b[^>]*>)", rf"\1\n{heading}", lecture_html, count=1, flags=re.IGNORECASE)
    return heading + lecture_html

    safe_title = project_name.strip() or "Lecture"
    heading = (
        '<header class="lecture-module-heading">\n'
        f"  <h1>模块：{safe_title}</h1>\n"
        f"  <h2>Module: {safe_title}</h2>\n"
        "</header>\n"
    )
    if re.search(r"<main\b[^>]*>", lecture_html, re.IGNORECASE):
        return re.sub(r"(<main\b[^>]*>)", rf"\1\n{heading}", lecture_html, count=1, flags=re.IGNORECASE)
    if re.search(r"<body\b[^>]*>", lecture_html, re.IGNORECASE):
        return re.sub(r"(<body\b[^>]*>)", rf"\1\n{heading}", lecture_html, count=1, flags=re.IGNORECASE)
    return heading + lecture_html


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
        r"\$\\text\{(?:\\\$|\$)\}(\d[\d,]*(?:\.\d+)?)(\s*/\s*)\\text\{(USD|EUR|GBP|JPY)\}\$",
        lambda match: rf"\({match.group(1)}\,\$/{_currency_macro(match.group(3))}\)",
        text,
    )
    text = re.sub(
        r"\\\$(\d[\d,]*(?:\.\d+)?)(\s*/\s*)([€¥£])",
        lambda match: rf"{match.group(1)}\,\$/{_currency_macro(match.group(3))}",
        text,
    )
    text = re.sub(
        r"\\text\{(?:\\\$|\$)\}(\d[\d,]*(?:\.\d+)?)(\s*/\s*)\\text\{(USD|EUR|GBP|JPY)\}",
        lambda match: rf"{match.group(1)}\,\$/{_currency_macro(match.group(3))}",
        text,
    )
    text = re.sub(
        r"\\text\{(?:\\\$|\$)\}(\d[\d,]*(?:\.\d+)?)",
        lambda match: rf"{match.group(1)}\,\$",
        text,
    )
    text = re.sub(
        r"(?<!\\)\$(\d[\d,]*(?:\.\d+)?)(\s*/\s*)([€¥£])",
        lambda match: rf"\({match.group(1)}\,\$/{_currency_macro(match.group(3))}\)",
        text,
    )
    text = re.sub(
        r"(?<!\\)\$(\d[\d,]*(?:\.\d+)?)",
        lambda match: rf"\({match.group(1)}\,\$\)",
        text,
    )
    text = re.sub(
        r"(?<!\\)([€¥£])(\d[\d,]*(?:\.\d+)?)",
        lambda match: rf"\({match.group(2)}\,{_currency_macro(match.group(1))}\)",
        text,
    )
    for value, macro in {
        "EUR": r"\euro",
        "GBP": r"\pounds",
        "JPY": r"\yen",
        "€": r"\euro",
        "£": r"\pounds",
        "¥": r"\yen",
    }.items():
        text = text.replace(rf"\text{{{value}}}", macro)
    text = text.replace("€", r"\(\euro\)")
    text = text.replace("£", r"\(\pounds\)")
    text = text.replace("¥", r"\(\yen\)")
    text = re.sub(r"(?<!\\)\$(?![\d])", r"\\(\\$\\)", text)
    return text


def _currency_macro(value: str) -> str:
    return {
        "EUR": r"\euro",
        "GBP": r"\pounds",
        "JPY": r"\yen",
        "€": r"\euro",
        "£": r"\pounds",
        "¥": r"\yen",
    }.get(value, value)


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
