"""ARCHITECTURE D3: the api process never imports torch or transformers."""

import json
import subprocess
import sys

import pytest

HEAVY = ("torch", "transformers")


def _heavy_modules_after(code: str, backend_dir) -> list[str]:
    probe = (
        f"{code}\nimport json, sys\nprint(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_probe_detects_torch(backend_dir):
    """Positive control: the probe really sees a torch import."""
    assert "torch" in _heavy_modules_after("import torch", backend_dir)


def test_api_never_imports_torch(backend_dir):
    assert _heavy_modules_after("import app.main", backend_dir) == []


@pytest.mark.parametrize(
    "module",
    [
        "app.worker.loop",
        "app.worker.handlers",
        "app.worker.classifiers",
        "app.ai.fake",
        "app.ai.contracts",
        "app.ai.text_prep",
    ],
)
def test_worker_and_ai_modules_import_torch_lazily(module, backend_dir):
    assert _heavy_modules_after(f"import {module}", backend_dir) == []
