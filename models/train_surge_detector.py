"""
급등 패턴 멀티모달 AI 학습 (오프라인 구동 가능)
ResNet18 + MLP Fusion → 3-class (success/fail/normal)
"""
import sys
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import numpy as np
import pandas as pd

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from torchvision import models, transforms
from PIL import Image
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

# ── 경로 ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent.parent
DATA_DIR    = BASE_DIR / "storage" / "chart_images" / "after_analysis"
CSV_PATH    = BASE_DIR / "storage" / "chart_images" / "labels_after_analysis.csv"
WEIGHT_PATH = BASE_DIR / "models" / "weights" / "resnet18_pretrained.pt"
SAVE_PATH   = BASE_DIR / "models" / "active" / "surge_detector.pt"

PYTHON_EXE  = sys.executable  # 현재 Python 경로 (오프라인 재실행용)

# ── 하이퍼파라미터 ─────────────────────────────────────────────────────────────
BATCH_SIZE  = 32
EPOCHS      = 20
LR          = 0.001
FAIL_MAX    = 5000   # fail 클래스 최대 샘플 수
IMG_SIZE    = 224
VAL_RATIO   = 0.2
SEED        = 42

FEATURE_COLS = [
    "volume_ratio", "volume_surge", "bullish_candle_ratio",
    "volatility", "trend_short", "trend_long",
    "price_position", "body_ratio",
]

CLASS_MAP   = {0: "success", 1: "fail", 2: "normal"}
FOLDER_MAP  = {"success": 0, "fail": 1, "normal": 2}
DEVICE      = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ── Dataset ───────────────────────────────────────────────────────────────────
class SurgeDataset(Dataset):
    def __init__(self, samples, df_feat, scaler, transform, fit_scaler=False):
        self.samples   = samples    # [(path, label), ...]
        self.df_feat   = df_feat
        self.scaler    = scaler
        self.transform = transform

        # 수치 특징 행렬 구성
        feats = []
        for path, _ in samples:
            row = self._get_features(path)
            feats.append(row)
        feats = np.array(feats, dtype=np.float32)

        if fit_scaler:
            self.scaler.fit(feats)
        self.features = self.scaler.transform(feats)

    def _get_features(self, path: Path) -> list:
        name = path.name
        # ticker + timestamp 로 매칭
        # 파일명: {ticker}_{ts}_to_{tend}_after_{label}.png
        parts = name.replace(".png", "").split("_")
        if len(parts) >= 2:
            ticker = parts[0]
            ts     = parts[1] + "_" + parts[2] if len(parts) > 2 else parts[1]
            rows   = self.df_feat[
                (self.df_feat["ticker"] == ticker) &
                (self.df_feat["timestamp"] == ts)
            ]
            if len(rows):
                return rows.iloc[0][FEATURE_COLS].fillna(0).tolist()
        return [0.0] * len(FEATURE_COLS)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        img = Image.open(path).convert("RGB")
        img = self.transform(img)
        feat = torch.tensor(self.features[idx], dtype=torch.float32)
        return img, feat, label


# ── 모델 ──────────────────────────────────────────────────────────────────────
class SurgeDetector(nn.Module):
    def __init__(self, n_features=8, n_classes=3):
        super().__init__()

        # CNN (ResNet18)
        self.cnn = models.resnet18(weights=None)
        if WEIGHT_PATH.exists():
            self.cnn.load_state_dict(torch.load(WEIGHT_PATH, map_location="cpu"))
        self.cnn.fc = nn.Identity()  # 512-dim 출력

        # MLP (수치 특징)
        self.mlp = nn.Sequential(
            nn.Linear(n_features, 64), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(64, 32),         nn.ReLU(),
        )

        # Fusion
        self.fusion = nn.Sequential(
            nn.Linear(512 + 32, 256), nn.ReLU(), nn.Dropout(0.4),
            nn.Linear(256, 128),      nn.ReLU(),
            nn.Linear(128, n_classes),
        )

    def forward(self, img, feat):
        cnn_out = self.cnn(img)
        mlp_out = self.mlp(feat)
        x = torch.cat([cnn_out, mlp_out], dim=1)
        return self.fusion(x)


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────
def load_samples():
    samples = []
    counts  = {}
    rng = np.random.default_rng(SEED)
    for folder, label in FOLDER_MAP.items():
        fdir = DATA_DIR / folder
        if not fdir.exists():
            continue
        files = list(fdir.glob("*.png"))
        if folder == "fail" and len(files) > FAIL_MAX:
            files = rng.choice(files, FAIL_MAX, replace=False).tolist()
        for f in files:
            samples.append((f, label))
        counts[folder] = len(files)
    return samples, counts


def make_transforms():
    train_tf = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406],
                             [0.229, 0.224, 0.225]),
    ])
    val_tf = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406],
                             [0.229, 0.224, 0.225]),
    ])
    return train_tf, val_tf


# ── 학습 ──────────────────────────────────────────────────────────────────────
def train():
    print(f"Device: {DEVICE}")

    # 데이터 로딩
    samples, counts = load_samples()
    print("\n데이터 로딩:")
    for folder, cnt in counts.items():
        print(f"  {folder}/: {cnt}개 (Class {FOLDER_MAP[folder]})")
    print(f"  총: {len(samples)}개\n")

    df_feat = pd.read_csv(CSV_PATH)

    # Train/Val 분리 (stratified)
    labels  = [s[1] for s in samples]
    tr_idx, va_idx = train_test_split(
        range(len(samples)), test_size=VAL_RATIO,
        stratify=labels, random_state=SEED
    )
    tr_samples = [samples[i] for i in tr_idx]
    va_samples = [samples[i] for i in va_idx]

    # 클래스 가중치 (불균형 해결)
    cnt_arr  = np.array([counts.get(f, 1) for f in ("success", "fail", "normal")])
    weights  = cnt_arr.max() / cnt_arr
    cls_w    = torch.tensor(weights, dtype=torch.float32).to(DEVICE)
    print(f"클래스 가중치: success={weights[0]:.1f}, fail={weights[1]:.1f}, normal={weights[2]:.1f}\n")

    # WeightedRandomSampler
    sample_w = [weights[s[1]] for s in tr_samples]
    sampler  = WeightedRandomSampler(sample_w, len(tr_samples), replacement=True)

    train_tf, val_tf = make_transforms()
    scaler = StandardScaler()

    tr_ds = SurgeDataset(tr_samples, df_feat, scaler, train_tf, fit_scaler=True)
    va_ds = SurgeDataset(va_samples, df_feat, scaler, val_tf,   fit_scaler=False)

    tr_dl = DataLoader(tr_ds, batch_size=BATCH_SIZE, sampler=sampler,  num_workers=0)
    va_dl = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False,    num_workers=0)

    # 모델
    model     = SurgeDetector(n_features=len(FEATURE_COLS)).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss(weight=cls_w)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.5)

    best_acc  = 0.0
    best_state = None

    print("학습:")
    for epoch in range(1, EPOCHS + 1):
        # Train
        model.train()
        tr_loss, tr_correct, tr_total = 0, 0, 0
        for imgs, feats, lbls in tr_dl:
            imgs, feats, lbls = imgs.to(DEVICE), feats.to(DEVICE), lbls.to(DEVICE)
            optimizer.zero_grad()
            out  = model(imgs, feats)
            loss = criterion(out, lbls)
            loss.backward()
            optimizer.step()
            tr_loss    += loss.item() * len(lbls)
            tr_correct += (out.argmax(1) == lbls).sum().item()
            tr_total   += len(lbls)
        scheduler.step()

        # Validation
        model.eval()
        va_correct, va_total = 0, 0
        with torch.no_grad():
            for imgs, feats, lbls in va_dl:
                imgs, feats, lbls = imgs.to(DEVICE), feats.to(DEVICE), lbls.to(DEVICE)
                out = model(imgs, feats)
                va_correct += (out.argmax(1) == lbls).sum().item()
                va_total   += len(lbls)

        tr_acc = tr_correct / tr_total * 100
        va_acc = va_correct / va_total * 100
        tr_avg = tr_loss / tr_total

        if va_acc > best_acc:
            best_acc   = va_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        print(f"Epoch {epoch:2d}/{EPOCHS}: Loss={tr_avg:.3f}, "
              f"Train={tr_acc:.1f}%, Val={va_acc:.1f}%"
              + (" ← best" if va_acc == best_acc else ""))

    # 저장
    SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": best_state,
        "class_mapping":    CLASS_MAP,
        "feature_columns":  FEATURE_COLS,
        "best_val_acc":     best_acc,
        "epochs":           EPOCHS,
        "scaler_mean":      scaler.mean_.tolist(),
        "scaler_scale":     scaler.scale_.tolist(),
    }, SAVE_PATH)
    print(f"\n모델 저장: {SAVE_PATH}")
    print(f"Best Val Acc: {best_acc:.1f}%")

    # 최종 평가
    _evaluate(model, va_dl, best_state)


def _evaluate(model, va_dl, best_state):
    model.load_state_dict({k: v.to(DEVICE) for k, v in best_state.items()})
    model.eval()

    all_pred, all_true = [], []
    with torch.no_grad():
        for imgs, feats, lbls in va_dl:
            imgs, feats = imgs.to(DEVICE), feats.to(DEVICE)
            out = model(imgs, feats)
            all_pred.extend(out.argmax(1).cpu().tolist())
            all_true.extend(lbls.tolist())

    cm        = confusion_matrix(all_true, all_pred, labels=[0, 1, 2])
    precision = precision_score(all_true, all_pred, average=None, labels=[0,1,2], zero_division=0)
    recall    = recall_score(all_true, all_pred, average=None, labels=[0,1,2], zero_division=0)
    overall   = sum(p == t for p, t in zip(all_pred, all_true)) / len(all_true) * 100

    print("\nConfusion Matrix:")
    print(f"{'':10s} {'진짜':>6s} {'가짜':>6s} {'일반':>6s}")
    for i, row_name in enumerate(["진짜", "가짜", "일반"]):
        print(f"{row_name:10s} {cm[i,0]:>6d} {cm[i,1]:>6d} {cm[i,2]:>6d}")

    print("\nClass별 성능:")
    names = ["진짜 급등 (success)", "가짜 급등 (fail)", "일반 (normal)"]
    for i, name in enumerate(names):
        print(f"  {name}: Precision={precision[i]*100:.1f}%, Recall={recall[i]*100:.1f}%")

    print(f"\n전체 정확도: {overall:.1f}%")

    # 투자 위험 오류
    fake_to_real = cm[1, 0]  # 가짜→진짜
    real_to_fake = cm[0, 1]  # 진짜→가짜
    print(f"\n중요:")
    print(f"  가짜→진짜 오류 (투자 위험): {fake_to_real}개")
    print(f"  진짜→가짜 오류 (기회 손실): {real_to_fake}개")


if __name__ == "__main__":
    train()
