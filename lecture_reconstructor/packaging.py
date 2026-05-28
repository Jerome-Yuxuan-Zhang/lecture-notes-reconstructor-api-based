from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package_output(output_dir: Path) -> Path:
    output_dir = Path(output_dir).resolve()
    zip_path = output_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(output_dir.parent))
    return zip_path
