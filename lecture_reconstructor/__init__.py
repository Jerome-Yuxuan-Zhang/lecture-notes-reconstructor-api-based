"""Lecture reconstruction application core."""

from .generator import generate_lecture
from .material import extract_materials, scan_materials
from .packaging import package_output

__all__ = [
    "extract_materials",
    "generate_lecture",
    "package_output",
    "scan_materials",
]
