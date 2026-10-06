"""Measure how the app's confidence floor handles out-of-scope messages.

In the app, a message is treated as "not understood" when the model predicts `oos`
OR its top confidence is below INTENT_CONFIDENCE_FLOOR. This script reports, per floor:
- oos caught: share of CLINC150 out-of-scope test messages that are rejected,
- in-scope kept: share of in-scope test messages that pass the floor,
- accuracy on kept: accuracy among the in-scope messages that pass.

Usage (from ml/):  uv run python intent/evaluate_threshold.py <export_dir>
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import torch
import truststore
from datasets import load_dataset
from safetensors.torch import load_file
from transformers import AutoConfig, AutoModel, AutoTokenizer

truststore.inject_into_ssl()
sys.path.insert(0, str(Path(__file__).parent))
from verify_export import IntentClassifier, clean_text  # noqa: E402

FLOORS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]


def main(export_dir: Path) -> None:
    meta = json.loads((export_dir / "model_meta.json").read_text())
    mapping = json.loads((export_dir / "unified_label_mapping.json").read_text())
    label2id, overlap = mapping["label2id"], mapping["overlap_mapping"]
    env = json.loads((export_dir / "environment.json").read_text())["datasets"]

    model = IntentClassifier(AutoModel.from_config(AutoConfig.from_pretrained(export_dir)),
                             meta["num_labels"], meta["dropout_rate"])
    model.load_state_dict(load_file(export_dir / "model.safetensors"), strict=False)
    model.eval()
    tok = AutoTokenizer.from_pretrained(export_dir)
    torch.set_num_threads(4)

    def run(texts):
        confs, preds = [], []
        with torch.inference_mode():
            for i in range(0, len(texts), 256):
                enc = tok([clean_text(t) for t in texts[i:i + 256]], padding=True, truncation=True,
                          max_length=meta["max_length"], return_tensors="pt")
                p = torch.softmax(model(enc["input_ids"], enc["attention_mask"]), -1)
                c, k = p.max(-1)
                confs.append(c.numpy()); preds.append(k.numpy())
        return np.concatenate(confs), np.concatenate(preds)

    clinc_id, clinc_cfg, clinc_rev = env["clinc150"]
    clinc = load_dataset(clinc_id, clinc_cfg, revision=clinc_rev)["test"]
    names = clinc.features["intent"].names
    y = np.array([label2id[overlap.get(names[i], names[i])] for i in clinc["intent"]])
    conf, pred = run(list(clinc["text"]))
    oos = label2id["oos"]
    is_oos = y == oos

    b77_id, b77_rev = env["banking77"]
    b77 = load_dataset(b77_id, revision=b77_rev)["test"]
    by = np.array(b77["label"])
    bconf, bpred = run(list(b77["text"]))

    in_acc = float((pred[~is_oos] == y[~is_oos]).mean())
    print(f"CLINC150 test: n={len(y)}, oos={is_oos.sum()} | in-scope accuracy (no floor) {in_acc:.4f} "
          f"| oos recall (predicted 'oos') {(pred[is_oos] == oos).mean():.4f}")
    print(f"Banking77 test accuracy (no floor) {(bpred == by).mean():.4f}\n")
    print(f"{'floor':>5} | {'oos caught':>10} | {'CLINC in-scope kept':>19} | {'acc on kept':>11} "
          f"| {'B77 kept':>8} | {'B77 acc on kept':>15}")
    rows = []
    for f in FLOORS:
        rejected = (pred == oos) | (conf < f)
        kept_in = ~rejected & ~is_oos
        brej = (bpred == oos) | (bconf < f)
        row = {
            "floor": f,
            "oos_caught": float(rejected[is_oos].mean()),
            "clinc_in_scope_kept": float(kept_in.sum() / (~is_oos).sum()),
            "clinc_acc_on_kept": float((pred[kept_in] == y[kept_in]).mean()),
            "b77_kept": float((~brej).mean()),
            "b77_acc_on_kept": float((bpred[~brej] == by[~brej]).mean()),
        }
        rows.append(row)
        print(f"{f:>5.2f} | {row['oos_caught']:>10.3f} | {row['clinc_in_scope_kept']:>19.3f} | "
              f"{row['clinc_acc_on_kept']:>11.3f} | {row['b77_kept']:>8.3f} | {row['b77_acc_on_kept']:>15.3f}")
    out = export_dir / "threshold_analysis.json"
    out.write_text(json.dumps({"clinc_in_scope_accuracy": in_acc, "rows": rows}, indent=2))
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
