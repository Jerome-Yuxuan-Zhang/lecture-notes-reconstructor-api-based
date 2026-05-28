from __future__ import annotations

from collections import Counter
from pathlib import Path

from .models import MaterialDocument


def create_material_mix_chart(documents: list[MaterialDocument], assets_dir: Path) -> Path | None:
    if not documents:
        return None
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        return None

    counts = Counter(doc.material_type for doc in documents)
    assets_dir.mkdir(parents=True, exist_ok=True)
    output = assets_dir / "fig_0_1_material_mix.png"

    plt.rcParams["font.family"] = "serif"
    plt.rcParams["font.serif"] = ["Times New Roman", "Palatino Linotype", "Palatino"]
    plt.rcParams["mathtext.fontset"] = "stix"
    sns.set_style("white")

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    keys = list(counts.keys())
    values = [counts[k] for k in keys]
    sns.barplot(x=keys, y=values, ax=ax, color="#2c5aa0")
    ax.set_title("Material Type Coverage")
    ax.set_xlabel("File type")
    ax.set_ylabel("Count")
    ax.grid(True, axis="y", alpha=0.15, linewidth=0.5, color="#cccccc")
    fig.tight_layout(pad=2.0)
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return output
