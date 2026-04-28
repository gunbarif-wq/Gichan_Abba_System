"""
2단계 모델 학습
Stage 1: 급등 감지 (surge vs normal)   — Recall 최대화
Stage 2: 진위 판별 (success vs fail)   — Precision 최대화
"""
import sys, os, warnings
warnings.filterwarnings("ignore")

# 인터넷 차단 환경 대비: torch 자동 다운로드 비활성화
os.environ.setdefault("TORCH_HOME", str(__import__("pathlib").Path(__file__).resolve().parent.parent / "models" / "torch_cache"))
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"]  = "1"

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
SAVE_S1     = BASE_DIR / "models" / "active" / "stage1_surge_detector.pt"
SAVE_S2     = BASE_DIR / "models" / "active" / "stage2_authenticity_classifier.pt"
SAVED_S1    = BASE_DIR / "models" / "saved"  / "stage1_surge_detector.pt"
SAVED_S2    = BASE_DIR / "models" / "saved"  / "stage2_authenticity_classifier.pt"

# ── 하이퍼파라미터 ─────────────────────────────────────────────────────────────
BATCH_SIZE = 32
EPOCHS     = 20
LR         = 0.001
FAIL_MAX   = 5000
IMG_SIZE   = 224
VAL_RATIO  = 0.2
SEED       = 42

FEATURE_COLS = [
    "volume_ratio","volume_surge","bullish_candle_ratio",
    "volatility","trend_short","trend_long","price_position","body_ratio",
]
DEVICE    = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CACHE_DIR = BASE_DIR / "storage" / "img_cache"


# ── 이미지 캐시 빌드 (PNG → 224×224 uint8 numpy, 최초 1회) ──────────────────
def build_cache(all_paths: list):
    """모든 PNG를 224×224 uint8 numpy로 변환해 .npy 캐시 저장."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    missing = [p for p in all_paths if not (CACHE_DIR / (p.stem + ".npy")).exists()]
    if not missing:
        print(f"캐시 이미 완성 ({len(all_paths):,}개)", flush=True)
        return
    print(f"캐시 빌드 시작: {len(missing):,}개 / 전체 {len(all_paths):,}개", flush=True)
    resize = transforms.Resize((IMG_SIZE, IMG_SIZE))
    for i, p in enumerate(missing, 1):
        out = CACHE_DIR / (p.stem + ".npy")
        img = resize(Image.open(p).convert("RGB"))
        np.save(out, np.array(img, dtype=np.uint8))
        if i % 500 == 0:
            print(f"  캐시 {i:,}/{len(missing):,}", flush=True)
    print(f"캐시 빌드 완료", flush=True)


# ── 모델 ──────────────────────────────────────────────────────────────────────
class StageModel(nn.Module):
    def __init__(self, n_classes=2):
        super().__init__()
        self.cnn = models.resnet18(weights=None)  # 인터넷 다운로드 없음
        if WEIGHT_PATH.exists():
            self.cnn.load_state_dict(
                torch.load(WEIGHT_PATH, map_location="cpu", weights_only=True)
            )
        self.cnn.fc = nn.Identity()
        self.mlp = nn.Sequential(
            nn.Linear(8, 64), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(64, 32), nn.ReLU(),
        )
        self.fusion = nn.Sequential(
            nn.Linear(544, 256), nn.ReLU(), nn.Dropout(0.4),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, n_classes),
        )
    def forward(self, img, feat):
        return self.fusion(torch.cat([self.cnn(img), self.mlp(feat)], dim=1))


# ── Dataset ───────────────────────────────────────────────────────────────────
class SurgeDataset(Dataset):
    def __init__(self, samples, df_feat, scaler, transform, fit_scaler=False):
        self.samples   = samples
        self.transform = transform
        feats = []
        for path, _ in samples:
            name  = path.name
            parts = name.replace(".png","").split("_")
            row   = pd.DataFrame()
            if len(parts) >= 2:
                ticker = parts[0]
                ts     = parts[1]+"_"+parts[2] if len(parts) > 2 else parts[1]
                row    = df_feat[(df_feat["ticker"]==ticker)&(df_feat["timestamp"]==ts)]
            f = row.iloc[0][FEATURE_COLS].fillna(0).tolist() if len(row) else [0.0]*8
            feats.append(f)
        feats = np.array(feats, dtype=np.float32)
        if fit_scaler:
            scaler.fit(feats)
        self.features = scaler.transform(feats)

    def __len__(self): return len(self.samples)
    def __getitem__(self, idx):
        path, label = self.samples[idx]
        cache = CACHE_DIR / (path.stem + ".npy")
        if cache.exists():
            img = Image.fromarray(np.load(cache))
        else:
            img = Image.open(path).convert("RGB")
        feat = torch.tensor(self.features[idx], dtype=torch.float32)
        return self.transform(img), feat, label


def make_transforms():
    tr = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225]),
    ])
    va = transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225]),
    ])
    return tr, va


CHECKPOINT_INTERVAL = 5  # N 에폭마다 체크포인트 저장


# ── 공통 학습 루프 ─────────────────────────────────────────────────────────────
def train_stage(samples, class_weights_list, stage_name, save_path,
                n_classes=2, target_metric="recall", target_class=0):
    print(f"\n{'='*62}", flush=True)
    print(f"  {stage_name}", flush=True)
    print(f"{'='*62}", flush=True)

    ckpt_path = save_path.parent / (save_path.stem + "_checkpoint.pth")

    label_counts = {}
    for _, lbl in samples:
        label_counts[lbl] = label_counts.get(lbl, 0) + 1
    for lbl, cnt in sorted(label_counts.items()):
        cname = {0:"class0",1:"class1"}.get(lbl,str(lbl))
        print(f"  class {lbl} ({cname}): {cnt:,}개", flush=True)
    print(f"  총: {len(samples):,}개\n", flush=True)

    df_feat = pd.read_csv(CSV_PATH)
    labels  = [s[1] for s in samples]
    tr_idx, va_idx = train_test_split(
        range(len(samples)), test_size=VAL_RATIO,
        stratify=labels, random_state=SEED,
    )
    tr_samples = [samples[i] for i in tr_idx]
    va_samples = [samples[i] for i in va_idx]

    cls_w   = torch.tensor(class_weights_list, dtype=torch.float32).to(DEVICE)
    samp_w  = [class_weights_list[s[1]] for s in tr_samples]
    sampler = WeightedRandomSampler(samp_w, len(tr_samples), replacement=True)

    tr_tf, va_tf = make_transforms()
    scaler = StandardScaler()

    tr_ds = SurgeDataset(tr_samples, df_feat, scaler, tr_tf, fit_scaler=True)
    va_ds = SurgeDataset(va_samples, df_feat, scaler, va_tf)

    # CPU 부하 완화: prefetch_factor 제거, pin_memory=False
    tr_dl = DataLoader(tr_ds, batch_size=BATCH_SIZE, sampler=sampler,
                       num_workers=0, pin_memory=False)
    va_dl = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False,
                       num_workers=0, pin_memory=False)

    model     = StageModel(n_classes=n_classes).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss(weight=cls_w)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=7, gamma=0.5)

    best_metric  = 0.0
    best_state   = None
    best_va_acc  = 0.0
    start_epoch  = 1

    # ── 체크포인트 복원 ────────────────────────────────────────────────────────
    if ckpt_path.exists():
        print(f"체크포인트 발견 → 이어서 학습: {ckpt_path.name}", flush=True)
        ckpt = torch.load(ckpt_path, map_location=DEVICE, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"])
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        start_epoch  = ckpt["epoch"] + 1
        best_metric  = ckpt.get("best_metric", 0.0)
        best_va_acc  = ckpt.get("best_va_acc", 0.0)
        best_state   = ckpt.get("best_model_state_dict")
        # scaler 복원
        scaler.mean_  = np.array(ckpt["scaler_mean"])
        scaler.scale_ = np.array(ckpt["scaler_scale"])
        scaler.var_   = scaler.scale_ ** 2
        scaler.n_features_in_ = len(scaler.mean_)
        print(f"  Epoch {start_epoch}부터 재개 (best_metric={best_metric*100:.1f}%)", flush=True)

    print("학습:", flush=True)
    for epoch in range(start_epoch, EPOCHS+1):
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
            tr_correct += (out.argmax(1)==lbls).sum().item()
            tr_total   += len(lbls)
        scheduler.step()

        model.eval()
        va_pred, va_true = [], []
        with torch.no_grad():
            for imgs, feats, lbls in va_dl:
                out = model(imgs.to(DEVICE), feats.to(DEVICE))
                va_pred.extend(out.argmax(1).cpu().tolist())
                va_true.extend(lbls.tolist())

        va_acc  = sum(p==t for p,t in zip(va_pred,va_true)) / len(va_true) * 100
        rec_arr = recall_score(va_true, va_pred, average=None,
                               labels=list(range(n_classes)), zero_division=0)
        prec_arr= precision_score(va_true, va_pred, average=None,
                                  labels=list(range(n_classes)), zero_division=0)
        key_metric = rec_arr[target_class] if target_metric=="recall" else prec_arr[target_class]

        is_best = key_metric > best_metric
        if is_best:
            best_metric  = key_metric
            best_va_acc  = va_acc
            best_state   = {k:v.cpu().clone() for k,v in model.state_dict().items()}

        tr_avg = tr_loss / tr_total
        flag   = " ← best" if is_best else ""
        r0     = rec_arr[0]*100
        p0     = prec_arr[0]*100
        print(f"Epoch {epoch:2d}/{EPOCHS}: Loss={tr_avg:.3f} Acc={va_acc:.1f}%"
              f" | cls0 Recall={r0:.1f}% Prec={p0:.1f}%{flag}", flush=True)

        # N 에폭마다 체크포인트 저장
        if epoch % CHECKPOINT_INTERVAL == 0 or epoch == EPOCHS:
            ckpt_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "epoch":                  epoch,
                "model_state_dict":       {k:v.cpu() for k,v in model.state_dict().items()},
                "optimizer_state_dict":   optimizer.state_dict(),
                "scheduler_state_dict":   scheduler.state_dict(),
                "best_metric":            best_metric,
                "best_va_acc":            best_va_acc,
                "best_model_state_dict":  best_state,
                "scaler_mean":            scaler.mean_.tolist(),
                "scaler_scale":           scaler.scale_.tolist(),
            }, ckpt_path)
            print(f"  체크포인트 저장: epoch={epoch}", flush=True)

    # 저장
    save_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": best_state,
        "n_classes":        n_classes,
        "best_val_acc":     best_va_acc,
        "best_metric":      best_metric,
        "target_metric":    target_metric,
        "target_class":     target_class,
        "scaler_mean":      scaler.mean_.tolist(),
        "scaler_scale":     scaler.scale_.tolist(),
        "epochs":           EPOCHS,
    }, save_path)
    print(f"\n저장: {save_path.name}")
    print(f"Best {target_metric} (class {target_class}): {best_metric*100:.1f}%  Acc: {best_va_acc:.1f}%")

    return best_state, scaler, va_samples, df_feat, va_tf


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────
def load_raw():
    rng = np.random.default_rng(SEED)
    success, fail, normal = [], [], []
    for folder in ("success","fail","normal"):
        fdir = DATA_DIR / folder
        if not fdir.exists():
            print(f"  경고: {fdir} 없음", flush=True); continue
        files = list(fdir.glob("*.png"))
        if folder=="fail" and len(files)>FAIL_MAX:
            files = rng.choice(files, FAIL_MAX, replace=False).tolist()
        if folder=="success": success = files
        elif folder=="fail":  fail    = files
        else:                 normal  = files
        print(f"  {folder}: {len(files):,}개", flush=True)
    return success, fail, normal


# ── 통합 평가 ─────────────────────────────────────────────────────────────────
def evaluate_pipeline(s1_state, s1_scaler, s2_state, s2_scaler,
                      va_all_samples, df_feat, va_tf):
    """Stage1 → Stage2 파이프라인 검증셋 평가"""
    print(f"\n{'='*62}")
    print("  통합 파이프라인 평가")
    print(f"{'='*62}")

    # 원본 라벨: success=0, fail=1, normal=2
    ORIG_MAP = {"success":0,"fail":1,"normal":2}

    # Stage1 모델 로드
    m1 = StageModel(n_classes=2).to(DEVICE)
    m1.load_state_dict({k:v.to(DEVICE) for k,v in s1_state.items()})
    m1.eval()

    # Stage2 모델 로드
    m2 = StageModel(n_classes=2).to(DEVICE)
    m2.load_state_dict({k:v.to(DEVICE) for k,v in s2_state.items()})
    m2.eval()

    # va_all_samples: (path, orig_label) — 0=success,1=fail,2=normal
    va_ds = SurgeDataset(va_all_samples, df_feat, s1_scaler, va_tf)
    va_dl = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    # Stage2 scaler transform
    va_ds2 = SurgeDataset(va_all_samples, df_feat, s2_scaler, va_tf)
    va_dl2 = DataLoader(va_ds2, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    # Stage1 예측
    s1_preds = []
    with torch.no_grad():
        for imgs, feats, _ in va_dl:
            out = m1(imgs.to(DEVICE), feats.to(DEVICE))
            s1_preds.extend(out.argmax(1).cpu().tolist())
    # Stage1: 0=surge, 1=normal

    # Stage2 예측 (surge 샘플에 대해서만)
    s2_preds_all = []
    with torch.no_grad():
        for imgs, feats, _ in va_dl2:
            out = m2(imgs.to(DEVICE), feats.to(DEVICE))
            s2_preds_all.extend(out.argmax(1).cpu().tolist())
    # Stage2: 0=success, 1=fail

    # 파이프라인 최종 예측
    final_pred = []
    final_true = []
    for i, (_, orig_lbl) in enumerate(va_all_samples):
        true_lbl = orig_lbl  # 0=success,1=fail,2=normal

        if s1_preds[i] == 1:         # Stage1: normal
            pred = 2
        else:                        # Stage1: surge → Stage2
            pred = s2_preds_all[i]   # 0=success, 1=fail

        final_pred.append(pred)
        final_true.append(true_lbl)

    # 성능 계산
    overall = sum(p==t for p,t in zip(final_pred,final_true))/len(final_true)*100
    cm      = confusion_matrix(final_true, final_pred, labels=[0,1,2])
    prec    = precision_score(final_true, final_pred, average=None, labels=[0,1,2], zero_division=0)
    rec     = recall_score(final_true, final_pred, average=None, labels=[0,1,2], zero_division=0)

    print(f"\n전체 정확도: {overall:.1f}%")
    print(f"\nConfusion Matrix (행=실제, 열=예측):")
    print(f"{'':12s} {'success':>8s} {'fail':>8s} {'normal':>8s}")
    for i, rn in enumerate(["success","fail","normal"]):
        print(f"{rn:12s} {cm[i,0]:>8d} {cm[i,1]:>8d} {cm[i,2]:>8d}")

    print(f"\n최종 성능:")
    names = ["success (진짜 급등)","fail (가짜 급등)","normal (일반)"]
    for i,n in enumerate(names):
        f1 = 2*prec[i]*rec[i]/(prec[i]+rec[i]+1e-9)
        print(f"  {n}: Precision={prec[i]*100:.1f}%  Recall={rec[i]*100:.1f}%  F1={f1*100:.1f}%")

    fake_to_real = cm[1,0]
    real_to_fake = cm[0,1]
    total_fail   = sum(cm[1])
    total_success= sum(cm[0])
    print(f"\n투자 위험 지표:")
    print(f"  가짜→진짜 오류 (매수 손실 위험): {fake_to_real}개  "
          f"({fake_to_real/max(total_fail,1)*100:.1f}%)")
    print(f"  진짜→가짜 오류 (기회 손실):       {real_to_fake}개  "
          f"({real_to_fake/max(total_success,1)*100:.1f}%)")

    s1_recall_surge = rec[0] + rec[1]   # stage1이 둘 다 잡아야 함
    print(f"\n목표 달성 여부:")
    print(f"  Stage1 급등 Recall(success+fail 합산 감지): "
          f"{'PASS' if rec[0]+rec[1]>=0.90 else 'FAIL'}")
    print(f"  success Precision: {prec[0]*100:.1f}%  "
          f"{'PASS ≥80%' if prec[0]>=0.80 else f'FAIL (<80%)'}")
    print(f"  success Recall:    {rec[0]*100:.1f}%  "
          f"{'PASS ≥50%' if rec[0]>=0.50 else f'FAIL (<50%)'}")


# ── 메인 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Device: {DEVICE}", flush=True)
    print("\n데이터 로딩:", flush=True)
    success_files, fail_files, normal_files = load_raw()

    # 캐시 빌드 (최초 1회만, 이후 스킵)
    all_paths = success_files + fail_files + normal_files
    build_cache(all_paths)

    # ── Stage 1: 급등 감지 ────────────────────────────────────────────────────
    # Class 0 = surge (success+fail), Class 1 = normal
    s1_samples = (
        [(f, 0) for f in success_files] +
        [(f, 0) for f in fail_files] +
        [(f, 1) for f in normal_files]
    )
    s1_state, s1_scaler, _, _, _ = train_stage(
        s1_samples,
        class_weights_list=[5.0, 1.0],
        stage_name="Stage 1: 급등 감지 (surge=0 vs normal=1)",
        save_path=SAVE_S1,
        n_classes=2,
        target_metric="recall",
        target_class=0,     # surge Recall 최대화
    )

    # ── Stage 2: 진위 판별 ────────────────────────────────────────────────────
    # Class 0 = success, Class 1 = fail
    s2_samples = (
        [(f, 0) for f in success_files] +
        [(f, 1) for f in fail_files]
    )
    s2_state, s2_scaler, _, _, _ = train_stage(
        s2_samples,
        class_weights_list=[3.0, 1.0],
        stage_name="Stage 2: 진위 판별 (success=0 vs fail=1)",
        save_path=SAVE_S2,
        n_classes=2,
        target_metric="precision",
        target_class=0,     # success Precision 최대화
    )

    # ── 통합 평가 ─────────────────────────────────────────────────────────────
    # 전체 3-class 검증셋으로 파이프라인 테스트
    all_samples = (
        [(f, 0) for f in success_files] +
        [(f, 1) for f in fail_files] +
        [(f, 2) for f in normal_files]
    )
    df_feat = pd.read_csv(CSV_PATH)
    labels  = [s[1] for s in all_samples]
    _, va_idx = train_test_split(
        range(len(all_samples)), test_size=VAL_RATIO,
        stratify=labels, random_state=SEED,
    )
    va_all = [all_samples[i] for i in va_idx]

    _, va_tf = make_transforms()
    evaluate_pipeline(s1_state, s1_scaler, s2_state, s2_scaler,
                      va_all, df_feat, va_tf)

    # models/saved/ 에도 복사 저장
    import shutil
    SAVED_S1.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAVE_S1, SAVED_S1)
    shutil.copy2(SAVE_S2, SAVED_S2)
    print(f"백업 저장: {SAVED_S1.parent}")

    print(f"\n완료.")
