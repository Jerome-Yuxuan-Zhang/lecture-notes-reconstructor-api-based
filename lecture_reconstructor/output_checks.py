from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse


def validate_html_image_refs(html_path: Path) -> list[str]:
    html_path = Path(html_path)
    output_dir = html_path.parent
    html = html_path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    for ref in sorted(set(re.findall(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", html, re.IGNORECASE))):
        if ref.startswith(("http://", "https://", "data:", "mailto:")):
            if ref.startswith("data:"):
                errors.append(f"Image uses forbidden embedded data URI: {ref[:80]}")
            continue
        parsed = urlparse(ref)
        raw_path = unquote(parsed.path or ref).replace("\\", "/")
        if raw_path.startswith("/"):
            errors.append(f"Image path must be relative, not absolute: {ref}")
            continue
        image_path = (output_dir / raw_path).resolve()
        try:
            image_path.relative_to(output_dir.resolve())
        except ValueError:
            errors.append(f"Image path escapes output folder: {ref}")
            continue
        if not image_path.exists():
            errors.append(f"Referenced image does not exist: {ref}")
        elif not image_path.is_file():
            errors.append(f"Referenced image is not a file: {ref}")
    return errors


def print_html_to_pdf(html_path: Path, pdf_root: Path) -> Path | None:
    if os.getenv("LECTURE_RECONSTRUCTOR_SKIP_PDF") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        return None
    edge = _find_edge()
    if edge is None:
        return None
    html_path = Path(html_path).resolve()
    pdf_root = Path(pdf_root).expanduser().resolve()
    pdf_root.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_root / f"{html_path.stem}.pdf"
    command = [
        str(edge),
        "--headless",
        "--disable-gpu",
        f"--print-to-pdf={pdf_path}",
        "--print-to-pdf-no-header",
        html_path.as_uri(),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0 or not pdf_path.exists():
        raise RuntimeError(
            "Microsoft Edge PDF printing failed. "
            f"Return code: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return pdf_path


def _find_edge() -> Path | None:
    executable = shutil.which("msedge")
    if executable:
        return Path(executable)
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
