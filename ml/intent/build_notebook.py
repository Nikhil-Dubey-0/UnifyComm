"""Build the Colab notebook from retrain_intent.py.

Cells are separated by "# %%" lines; "# %% [markdown]" cells become markdown.
The unified label mapping is embedded so the notebook needs no extra uploads.

Usage (from ml/):  uv run python intent/build_notebook.py
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "retrain_intent.py"
MAPPING = HERE.parents[1] / "models" / "intent" / "final_model" / "unified_label_mapping.json"
TARGET = HERE / "unifycomm_intent_retrain.ipynb"
PLACEHOLDER = "MAPPING_JSON = None  # @EMBED_MAPPING@"


def split_cells(text: str) -> list[tuple[str, str]]:
    cells, kind, buf = [], None, []
    for line in text.splitlines():
        if line.startswith("# %%"):
            if kind is not None:
                cells.append((kind, "\n".join(buf).strip("\n")))
            kind, buf = ("markdown" if "[markdown]" in line else "code"), []
        else:
            buf.append(line)
    if kind is not None:
        cells.append((kind, "\n".join(buf).strip("\n")))
    return cells


def to_cell(kind: str, src: str) -> dict:
    if kind == "markdown":
        src = "\n".join(line[2:] if line.startswith("# ") else line.lstrip("#") for line in src.splitlines())
        return {"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)}
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": src.splitlines(keepends=True)}


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    mapping = json.dumps(json.loads(MAPPING.read_text(encoding="utf-8")), separators=(",", ":"))
    assert PLACEHOLDER in text and "'''" not in mapping
    text = text.replace(PLACEHOLDER, f"MAPPING_JSON = r'''{mapping}'''")
    nb = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4", "name": TARGET.name},
            "kernelspec": {"name": "python3", "display_name": "Python 3"},
            "language_info": {"name": "python"},
        },
        "cells": [to_cell(k, s) for k, s in split_cells(text)],
    }
    TARGET.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {TARGET} with {len(nb['cells'])} cells")


if __name__ == "__main__":
    main()
