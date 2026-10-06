# %% [markdown]
# # UnifyComm: intent model retraining (Plan B)
#
# The original intent weights were lost, so this notebook retrains the model from the
# documented recipe of the team's two Colab notebooks and the saved label mapping.
#
# **How to run (about 10–15 minutes):**
# 1. `Runtime → Change runtime type → T4 GPU`, then `Save`.
# 2. `Runtime → Run all`.
# 3. When it finishes, the browser downloads `unifycomm_intent_repro-v1.zip`. Allow the download if asked.
# 4. The last cell also copies the zip to your Google Drive (`MyDrive/UnifyComm/models/intent/`). Approve the Drive prompt.
# 5. Put the zip in `C:\UnifyComm\models\intent\` and tell Claude.
#
# **What it reproduces:** `all-MiniLM-L6-v2` encoder, mean pooling, dropout 0.1, linear head,
# max length 64, the same `clean_text`, the same 213 unified labels and label order.
# Stage 1 trains on Banking77 (77 labels); Stage 2 trains jointly on Banking77 + CLINC150 "plus"
# (213 labels) with encoder LR 1e-5 and head LR 1e-4.
#
# **What it fixes:** the original Stage 1 picked its best epoch on the *test* set. Here, model
# selection uses validation data (10% of Banking77 train, plus CLINC150 validation) and each
# test set is used once, at the end. The weights are saved as `model.safetensors` and copied to Drive.

# %%
# Setup: detect Colab and install pinned libraries (Colab already has CUDA PyTorch).
import os
import subprocess
import sys

IN_COLAB = "COLAB_RELEASE_TAG" in os.environ or os.path.exists("/content/sample_data")
DRY_RUN = os.environ.get("UC_DRY_RUN") == "1"  # local CPU smoke test with a tiny sample

if IN_COLAB:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "transformers==5.18.0", "datasets>=3.0", "safetensors", "scikit-learn"],
        check=True,
    )
print(f"Colab: {IN_COLAB} | dry run: {DRY_RUN}")

# %%
import copy
import hashlib
import json
import random
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import transformers
from datasets import load_dataset
from safetensors.torch import save_file
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader, TensorDataset
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

SEED = 42


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


seed_all(SEED)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
if DEVICE.type != "cuda" and not DRY_RUN:
    raise RuntimeError(
        "No GPU found. In Colab: Runtime → Change runtime type → T4 GPU → Save, then Runtime → Run all."
    )
print(f"torch {torch.__version__} | transformers {transformers.__version__} | device {DEVICE}")
if DEVICE.type == "cuda":
    print("GPU:", torch.cuda.get_device_name(0))

# %%
# Configuration. Every external input is pinned to an exact revision.
BASE_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BASE_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
B77_ID, B77_REVISION = "legacy-datasets/banking77", "f54121560de48f2852f90be299010d1d6dc612ec"
CLINC_ID, CLINC_CONFIG = "clinc/clinc_oos", "plus"
CLINC_REVISION = "155b9c710419136e17307b80d0a13e68cd46b4ec"

MAX_LENGTH = 64
DROPOUT = 0.1
BATCH_SIZE = 32
EVAL_BATCH_SIZE = 256
B77_VAL_FRACTION = 0.10
STAGE1 = {"epochs": 5, "lr": 2e-5, "warmup_steps": 100, "weight_decay": 0.01, "patience": 2}
STAGE2 = {"epochs": 5, "encoder_lr": 1e-5, "head_lr": 1e-4, "warmup_steps": 100,
          "weight_decay": 0.01, "patience": 2}
MODEL_VERSION_NAME = "repro-v1"

if DRY_RUN:  # tiny, fast settings for a local CPU check of the whole pipeline
    BATCH_SIZE, EVAL_BATCH_SIZE = 16, 64
    STAGE1 = {**STAGE1, "epochs": 1, "warmup_steps": 2}
    STAGE2 = {**STAGE2, "epochs": 1, "warmup_steps": 2}

OUT_DIR = Path(os.environ.get("UC_OUT_DIR", "/content/repro-v1" if IN_COLAB else "repro-v1"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
print("Output folder:", OUT_DIR.resolve())

# %%
# The team's unified label mapping (213 labels, exact order). Embedded so the notebook is self-contained.
MAPPING_JSON = None  # @EMBED_MAPPING@
if MAPPING_JSON is None:
    MAPPING_JSON = Path(os.environ["UC_MAPPING_PATH"]).read_text(encoding="utf-8")
MAPPING = json.loads(MAPPING_JSON)

ID2LABEL = {int(k): v for k, v in MAPPING["id2label"].items()}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}
BANKING_LABELS = MAPPING["banking77_labels"]
OVERLAP = MAPPING["overlap_mapping"]
NUM_LABELS = len(ID2LABEL)
assert NUM_LABELS == 213 and [ID2LABEL[i] for i in range(77)] == BANKING_LABELS
print(f"{NUM_LABELS} unified labels, {len(OVERLAP)} CLINC→Banking77 merges")

# %%
# Text cleaning: identical to the team's notebook. The app must apply the same function at inference.
def clean_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s\.\,\!\?\'\-]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


assert clean_text("my card  was   stolen #help @bank") == "my card was stolen help bank"

# %%
# Load data and map everything to unified label IDs.
b77 = load_dataset(B77_ID, revision=B77_REVISION)
clinc = load_dataset(CLINC_ID, CLINC_CONFIG, revision=CLINC_REVISION)

b77_names = b77["train"].features["label"].names
assert b77_names == BANKING_LABELS, "Banking77 label order differs from the unified mapping"
clinc_names = clinc["train"].features["intent"].names
clinc_to_unified = [LABEL2ID[OVERLAP.get(name, name)] for name in clinc_names]


def rows(split, text_col, label_col, mapper=None):
    texts = list(split[text_col])
    labels = list(split[label_col])
    if mapper is not None:
        labels = [mapper[x] for x in labels]
    return texts, labels


b77_train_texts, b77_train_labels = rows(b77["train"], "text", "label")
b77_test = rows(b77["test"], "text", "label")
clinc_train = rows(clinc["train"], "text", "intent", clinc_to_unified)
clinc_val = rows(clinc["validation"], "text", "intent", clinc_to_unified)
clinc_test = rows(clinc["test"], "text", "intent", clinc_to_unified)

idx_tr, idx_val = train_test_split(
    list(range(len(b77_train_texts))), test_size=B77_VAL_FRACTION,
    stratify=b77_train_labels, random_state=SEED,
)
b77_train = ([b77_train_texts[i] for i in idx_tr], [b77_train_labels[i] for i in idx_tr])
b77_val = ([b77_train_texts[i] for i in idx_val], [b77_train_labels[i] for i in idx_val])

if DRY_RUN:
    def head(pair, n):
        return pair[0][:n], pair[1][:n]
    b77_train, b77_val, b77_test = head(b77_train, 256), head(b77_val, 64), head(b77_test, 64)
    clinc_train, clinc_val, clinc_test = head(clinc_train, 256), head(clinc_val, 64), head(clinc_test, 64)

for name, pair in [("banking77 train", b77_train), ("banking77 val", b77_val),
                   ("banking77 test", b77_test), ("clinc150 train", clinc_train),
                   ("clinc150 val", clinc_val), ("clinc150 test", clinc_test)]:
    print(f"{name:16s} {len(pair[0]):>6,}")

# %%
# Tokenize once into tensors.
tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REVISION)


def to_dataset(pair) -> TensorDataset:
    enc = tokenizer([clean_text(t) for t in pair[0]], padding="max_length", truncation=True,
                    max_length=MAX_LENGTH, return_tensors="pt")
    return TensorDataset(enc["input_ids"], enc["attention_mask"], torch.tensor(pair[1]))


def concat(a, b):
    return a[0] + b[0], a[1] + b[1]


ds = {
    "s1_train": to_dataset(b77_train),
    "s1_val": to_dataset(b77_val),
    "s2_train": to_dataset(concat(b77_train, clinc_train)),
    "s2_val": to_dataset(concat(b77_val, clinc_val)),
    "b77_test": to_dataset(b77_test),
    "clinc_test": to_dataset(clinc_test),
}
print({k: len(v) for k, v in ds.items()})

# %%
# Model: same architecture as the team's IntentClassifier (state-dict keys encoder.* and classifier.*).
class IntentClassifier(nn.Module):
    def __init__(self, encoder: nn.Module, num_labels: int, dropout_rate: float = DROPOUT):
        super().__init__()
        self.encoder = encoder
        self.hidden_size = encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout_rate)
        self.classifier = nn.Linear(self.hidden_size, num_labels)

    @staticmethod
    def mean_pooling(last_hidden_state, attention_mask):
        mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        return torch.sum(last_hidden_state * mask, 1) / torch.clamp(mask.sum(1), min=1e-9)

    def forward(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        pooled = self.mean_pooling(out.last_hidden_state, attention_mask)
        return self.classifier(self.dropout(pooled))


def param_groups(model: IntentClassifier, encoder_lr: float, head_lr: float, weight_decay: float):
    no_decay = ("bias", "LayerNorm.weight", "LayerNorm.bias")
    groups = []
    for module, lr in ((model.encoder, encoder_lr), (model.classifier, head_lr)):
        named = list(module.named_parameters())
        groups.append({"params": [p for n, p in named if not n.endswith(no_decay)],
                       "lr": lr, "weight_decay": weight_decay})
        groups.append({"params": [p for n, p in named if n.endswith(no_decay)],
                       "lr": lr, "weight_decay": 0.0})
    return groups

# %%
# Training and evaluation helpers (plain PyTorch loop, fp16 autocast on GPU, gradient clipping 1.0).
USE_AMP = DEVICE.type == "cuda"


@torch.no_grad()
def predict(model, dataset):
    model.eval()
    all_logits = []
    for ids, mask, _ in DataLoader(dataset, batch_size=EVAL_BATCH_SIZE):
        with torch.autocast(device_type=DEVICE.type, dtype=torch.float16, enabled=USE_AMP):
            logits = model(ids.to(DEVICE), mask.to(DEVICE))
        all_logits.append(logits.float().cpu())
    logits = torch.cat(all_logits)
    return logits.argmax(-1).numpy(), dataset.tensors[2].numpy()


def scores(y_pred, y_true) -> dict:
    present = sorted(set(y_true.tolist()))
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_f1_true_labels": float(f1_score(y_true, y_pred, labels=present, average="macro",
                                               zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "n": int(len(y_true)),
    }


def train_stage(model, train_ds, val_ds, groups, epochs, warmup_steps, patience, name):
    loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,
                        generator=torch.Generator().manual_seed(SEED))
    optimizer = torch.optim.AdamW(groups)
    scheduler = get_linear_schedule_with_warmup(optimizer, warmup_steps, len(loader) * epochs)
    scaler = torch.amp.GradScaler("cuda", enabled=USE_AMP)
    loss_fn = nn.CrossEntropyLoss()
    best_acc, best_state, bad_epochs, history = -1.0, None, 0, []
    for epoch in range(1, epochs + 1):
        model.train()
        started, losses = time.time(), []
        for ids, mask, labels in loader:
            ids, mask, labels = ids.to(DEVICE), mask.to(DEVICE), labels.to(DEVICE)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=DEVICE.type, dtype=torch.float16, enabled=USE_AMP):
                logits = model(ids, mask)
            loss = loss_fn(logits.float(), labels)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            losses.append(loss.item())
        val = scores(*predict(model, val_ds))
        row = {"epoch": epoch, "train_loss": float(np.mean(losses)), "seconds": round(time.time() - started, 1),
               **{f"val_{k}": v for k, v in val.items() if k != "n"}}
        history.append(row)
        print(f"[{name}] epoch {epoch}: loss {row['train_loss']:.4f} | val acc {val['accuracy']:.4f} "
              f"| val macro-F1 {val['macro_f1']:.4f} | {row['seconds']}s")
        if val["accuracy"] > best_acc:
            best_acc, bad_epochs = val["accuracy"], 0
            best_state = copy.deepcopy({k: v.detach().cpu() for k, v in model.state_dict().items()})
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                print(f"[{name}] early stop")
                break
    model.load_state_dict(best_state)
    best_epoch = max(history, key=lambda r: r["val_accuracy"])["epoch"]
    print(f"[{name}] best epoch {best_epoch}, val acc {best_acc:.4f}")
    return history, best_epoch

# %%
# Stage 1: Banking77 only (77 labels).
seed_all(SEED)
encoder = AutoModel.from_pretrained(BASE_MODEL, revision=BASE_REVISION)
stage1 = IntentClassifier(encoder, num_labels=77).to(DEVICE)
t0 = time.time()
s1_history, s1_best = train_stage(
    stage1, ds["s1_train"], ds["s1_val"],
    param_groups(stage1, STAGE1["lr"], STAGE1["lr"], STAGE1["weight_decay"]),
    STAGE1["epochs"], STAGE1["warmup_steps"], STAGE1["patience"], "stage1",
)
s1_test = scores(*predict(stage1, ds["b77_test"]))
print(f"Stage 1 Banking77 test: {s1_test}  ({time.time() - t0:.0f}s)")

# %%
# Stage 2: joint Banking77 + CLINC150 (213 labels). Head rows 0..76 start from the Stage 1 head.
seed_all(SEED)
stage2 = IntentClassifier(stage1.encoder, num_labels=NUM_LABELS).to(DEVICE)
with torch.no_grad():
    stage2.classifier.weight[:77].copy_(stage1.classifier.weight)
    stage2.classifier.bias[:77].copy_(stage1.classifier.bias)
del stage1
t0 = time.time()
s2_history, s2_best = train_stage(
    stage2, ds["s2_train"], ds["s2_val"],
    param_groups(stage2, STAGE2["encoder_lr"], STAGE2["head_lr"], STAGE2["weight_decay"]),
    STAGE2["epochs"], STAGE2["warmup_steps"], STAGE2["patience"], "stage2",
)
print(f"Stage 2 training time: {time.time() - t0:.0f}s")

# %%
# Final test evaluation: each test set is used exactly once, here.
b77_pred, b77_true = predict(stage2, ds["b77_test"])
clinc_pred, clinc_true = predict(stage2, ds["clinc_test"])
b77_scores, clinc_scores = scores(b77_pred, b77_true), scores(clinc_pred, clinc_true)
oos_id = LABEL2ID["oos"]
oos_mask = clinc_true == oos_id
oos_recall = float((clinc_pred[oos_mask] == oos_id).mean()) if oos_mask.any() else None
print("Banking77 test :", b77_scores)
print("CLINC150 test  :", clinc_scores)
print("CLINC150 out-of-scope recall:", oos_recall)


def report(y_true, y_pred):
    present = sorted(set(y_true.tolist()) | set(y_pred.tolist()))
    return classification_report(y_true, y_pred, labels=present,
                                 target_names=[ID2LABEL[i] for i in present],
                                 output_dict=True, zero_division=0)

# %%
# Golden check: the six example predictions shown in the team's slides.
GOLDEN = [
    ("I can't access my account anymore", "account_blocked", 0.5358),
    ("What's the exchange rate for USD to EUR?", "exchange_rate", 0.9976),
    ("My card was stolen yesterday", "lost_or_stolen_card", 0.9700),
    ("Can you help me book a flight to London?", "book_flight", 0.9646),
    ("I was charged twice for the same transaction", "transaction_charged_twice", 0.9999),
    ("What's the weather like today?", "weather", 0.9910),
]


@torch.no_grad()
def top_k(model, text, k=3):
    model.eval()
    enc = tokenizer([clean_text(text)], padding="max_length", truncation=True,
                    max_length=MAX_LENGTH, return_tensors="pt").to(DEVICE)
    probs = torch.softmax(model(enc["input_ids"], enc["attention_mask"]).float(), -1)[0].cpu()
    values, indices = probs.topk(k)
    return [(ID2LABEL[int(i)], round(float(v), 4)) for v, i in zip(values, indices)]


golden_results = []
for text, expected, original_conf in GOLDEN:
    preds = top_k(stage2, text)
    ok = preds[0][0] == expected
    golden_results.append({"text": text, "expected": expected, "original_confidence": original_conf,
                           "top3": preds, "match": ok})
    print(f"{'OK ' if ok else 'DIFF'} {text!r}\n     -> {preds}   (original: {expected} {original_conf})")
print(f"Golden matches: {sum(r['match'] for r in golden_results)}/{len(GOLDEN)}")

# %%
# Export: safetensors weights + config + tokenizer + labels + metrics, then zip.
state = {k: v.detach().cpu().contiguous() for k, v in stage2.state_dict().items()}
save_file(state, str(OUT_DIR / "model.safetensors"),
          metadata={"format": "pt", "architecture": "IntentClassifier"})
stage2.encoder.config.save_pretrained(OUT_DIR)
tokenizer.save_pretrained(OUT_DIR)
weights_sha256 = hashlib.sha256((OUT_DIR / "model.safetensors").read_bytes()).hexdigest()


def write_json(name, obj):
    (OUT_DIR / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")


write_json("id2label.json", {str(i): ID2LABEL[i] for i in range(NUM_LABELS)})
write_json("label2id.json", LABEL2ID)
write_json("unified_label_mapping.json", MAPPING)
write_json("model_meta.json", {
    "model_name": BASE_MODEL, "base_revision": BASE_REVISION, "architecture": "IntentClassifier",
    "pooling": "mean", "num_labels": NUM_LABELS, "hidden_size": stage2.hidden_size,
    "dropout_rate": DROPOUT, "max_length": MAX_LENGTH, "text_cleaning": "clean_text_v1",
    "state_dict_prefixes": ["encoder.", "classifier."], "version_name": MODEL_VERSION_NAME,
    "weights_sha256": weights_sha256,
})
write_json("final_metrics.json", {
    "version_name": MODEL_VERSION_NAME, "dry_run": DRY_RUN,
    "banking77_test": b77_scores, "clinc150_test": clinc_scores,
    "clinc150_oos_recall": oos_recall,
    "banking77_test_stage1_77way": s1_test,
    "regression_delta_banking77": b77_scores["accuracy"] - s1_test["accuracy"],
    "stage1_best_epoch": s1_best, "stage2_best_epoch": s2_best,
    "golden_matches": f"{sum(r['match'] for r in golden_results)}/{len(GOLDEN)}",
})
write_json("training_history.json", {"stage1": s1_history, "stage2": s2_history,
                                     "config": {"stage1": STAGE1, "stage2": STAGE2,
                                                "batch_size": BATCH_SIZE, "seed": SEED,
                                                "b77_val_fraction": B77_VAL_FRACTION}})
write_json("classification_report_banking77.json", report(b77_true, b77_pred))
write_json("classification_report_clinc150.json", report(clinc_true, clinc_pred))
write_json("golden_results.json", golden_results)
write_json("environment.json", {
    "torch": torch.__version__, "transformers": transformers.__version__,
    "device": torch.cuda.get_device_name(0) if DEVICE.type == "cuda" else "cpu",
    "datasets": {"banking77": [B77_ID, B77_REVISION],
                 "clinc150": [CLINC_ID, CLINC_CONFIG, CLINC_REVISION]},
})

ZIP_PATH = OUT_DIR.parent / f"unifycomm_intent_{MODEL_VERSION_NAME}.zip"
with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
    for f in sorted(OUT_DIR.iterdir()):
        zf.write(f, arcname=f"{MODEL_VERSION_NAME}/{f.name}")
print(f"Saved {ZIP_PATH} ({ZIP_PATH.stat().st_size / 1e6:.1f} MB), weights sha256 {weights_sha256[:12]}")

# %%
# Download the zip to your computer.
if IN_COLAB:
    from google.colab import files
    files.download(str(ZIP_PATH))

# %%
# Backup copy in Google Drive so the weights cannot be lost again.
SAVE_TO_DRIVE = True
if IN_COLAB and SAVE_TO_DRIVE:
    import shutil

    from google.colab import drive
    drive.mount("/content/drive")
    target = Path("/content/drive/MyDrive/UnifyComm/models/intent")
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ZIP_PATH, target / ZIP_PATH.name)
    print("Copied to", target / ZIP_PATH.name)
