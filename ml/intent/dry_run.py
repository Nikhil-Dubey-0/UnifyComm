"""Local CPU smoke test of retrain_intent.py with a tiny data sample.

This machine's network re-signs TLS, so Python must trust the Windows certificate store
(truststore). Colab does not need this.

Usage (from ml/):  uv run python intent/dry_run.py <output_dir>
"""

import os
import runpy
import sys
from pathlib import Path

import truststore

truststore.inject_into_ssl()

here = Path(__file__).parent
os.environ["UC_DRY_RUN"] = "1"
os.environ["UC_MAPPING_PATH"] = str(
    here.parents[1] / "models" / "intent" / "final_model" / "unified_label_mapping.json"
)
os.environ["UC_OUT_DIR"] = sys.argv[1]
runpy.run_path(str(here / "retrain_intent.py"), run_name="__main__")
