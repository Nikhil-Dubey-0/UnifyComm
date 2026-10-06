"""Load an exported intent model exactly as the app will, and run the golden sentences.

Usage (from ml/):  uv run python intent/verify_export.py <export_dir>
No network access: the encoder is built from the exported config.json.
"""

import json
import re
import sys
from pathlib import Path

import torch
import torch.nn as nn
from safetensors.torch import load_file
from transformers import AutoConfig, AutoModel, AutoTokenizer

GOLDEN = [
    ("I can't access my account anymore", "account_blocked"),
    ("What's the exchange rate for USD to EUR?", "exchange_rate"),
    ("My card was stolen yesterday", "lost_or_stolen_card"),
    ("Can you help me book a flight to London?", "book_flight"),
    ("I was charged twice for the same transaction", "transaction_charged_twice"),
    ("What's the weather like today?", "weather"),
]


def clean_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s\.\,\!\?\'\-]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class IntentClassifier(nn.Module):
    def __init__(self, encoder: nn.Module, num_labels: int, dropout_rate: float):
        super().__init__()
        self.encoder = encoder
        self.dropout = nn.Dropout(dropout_rate)
        self.classifier = nn.Linear(encoder.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        mask = attention_mask.unsqueeze(-1).float()
        pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        return self.classifier(self.dropout(pooled))


def main(export_dir: Path) -> int:
    meta = json.loads((export_dir / "model_meta.json").read_text(encoding="utf-8"))
    id2label = {int(k): v for k, v in json.loads((export_dir / "id2label.json").read_text()).items()}
    config = AutoConfig.from_pretrained(export_dir)
    model = IntentClassifier(AutoModel.from_config(config), meta["num_labels"], meta["dropout_rate"])
    missing, unexpected = model.load_state_dict(load_file(export_dir / "model.safetensors"), strict=False)
    missing = [k for k in missing if not k.endswith("position_ids")]
    if missing or unexpected:
        print("STATE DICT MISMATCH", missing, unexpected)
        return 1
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(export_dir)
    matches = 0
    with torch.inference_mode():
        for text, expected in GOLDEN:
            enc = tokenizer([clean_text(text)], padding="max_length", truncation=True,
                            max_length=meta["max_length"], return_tensors="pt")
            probs = torch.softmax(model(enc["input_ids"], enc["attention_mask"]), -1)[0]
            values, idx = probs.topk(3)
            top = [(id2label[int(i)], round(float(v), 4)) for v, i in zip(values, idx)]
            matches += top[0][0] == expected
            print(f"{'OK ' if top[0][0] == expected else 'DIFF'} {text!r} -> {top}")
    print(f"golden matches {matches}/{len(GOLDEN)}; weights sha256 {meta.get('weights_sha256', '?')[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
