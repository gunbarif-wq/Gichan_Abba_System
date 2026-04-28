"""
야간 자동 재학습 스케줄러 — 매일 21:00 KST 실행
Step 1: KIS API에서 Top 200 종목 OHLCV 수집
Step 2: 2-stage 모델 파인튜닝 (stage1 + stage2)
Step 3: 이전 세션 대비 성능 비교
Step 4: 완료 후 텔레그램 리포트 (실패 시에도 발송)
"""

import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from torch.utils.data import DataLoader, WeightedRandomSampler
from torchvision import models, transforms
from sklearn.model_selection import train_test_split
from sklearn.metrics import precision_score, recall_score
from sklearn.preprocessing import StandardScaler

# 프로젝트 루트 기준
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from notify.telegram import get_telegram_notifier

logger = logging.getLogger(__name__)

# ── 경로 ──────────────────────────────────────────────────────────────────────
DATA_DIR    = BASE_DIR / "storage" / "chart_images" / "after_analysis"
CSV_PATH    = BASE_DIR / "storage" / "chart_images" / "labels_after_analysis.csv"
WEIGHT_PATH = BASE_DIR / "models" / "weights" / "resnet18_pretrained.pt"
SAVE_S1     = BASE_DIR / "models" / "active" / "stage1_surge_detector.pt"
SAVE_S2     = BASE_DIR / "models" / "active" / "stage2_authenticity_classifier.pt"
METRICS_PATH = BASE_DIR / "storage" / "logs" / "nightly_metrics.json"

# ── 하이퍼파라미터 ─────────────────────────────────────────────────────────────
BATCH_SIZE   = 32
FINETUNE_EPOCHS = 10   # 야간 파인튜닝은 10에폭
LR           = 0.0001  # 파인튜닝은 낮은 lr
FAIL_MAX     = 5000
IMG_SIZE     = 224
VAL_RATIO    = 0.2
SEED         = 42

FEATURE_COLS = [
    "volume_ratio", "volume_surge", "bullish_candle_ratio",
    "volatility", "trend_short", "trend_long", "price_position", "body_ratio",
]

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ── 모델 정의 (train_2stage.py 와 동일) ──────────────────────────────────────
class StageModel(nn.Module):
    def __init__(self, n_classes=2):
        super().__init__()
        self.cnn = models.resnet18(weights=None)
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


from PIL import Image

class SurgeDataset(torch.utils.data.Dataset):
    def __init__(self, samples, df_feat, scaler, transform, fit_scaler=False):
        self.samples   = samples
        self.transform = transform
        feats = []
        for path, _ in samples:
            name  = path.name
            parts = name.replace(".png", "").split("_")
            row   = pd.DataFrame()
            if len(parts) >= 2:
                ticker = parts[0]
                ts     = parts[1] + "_" + parts[2] if len(parts) > 2 else parts[1]
                row    = df_feat[(df_feat["ticker"] == ticker) & (df_feat["timestamp"] == ts)]
            f = row.iloc[0][FEATURE_COLS].fillna(0).tolist() if len(row) else [0.0] * 8
            feats.append(f)
        feats = np.array(feats, dtype=np.float32)
        if fit_scaler:
            scaler.fit(feats)
        self.features = scaler.transform(feats)

    def __len__(self): return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        img  = Image.open(path).convert("RGB")
        feat = torch.tensor(self.features[idx], dtype=torch.float32)
        return self.transform(img), feat, label


def _make_val_transform():
    return transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])

def _make_train_transform():
    return transforms.Compose([
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


# ── Step 1: OHLCV 수집 ────────────────────────────────────────────────────────
def fetch_top200_ohlcv() -> dict:
    """
    KIS API로 Top 200 종목 OHLCV 수집.
    Mock 모드이거나 API 실패 시 기존 데이터 사용.
    """
    result = {"symbols": [], "fetched": 0, "skipped": 0, "source": "api"}
    try:
        from trade.kis_mock_client import get_kis_mock_client
        kis = get_kis_mock_client()

        # 코스피+코스닥 각 100개
        kospi  = kis.get_volume_rank(market="J", top_n=100)
        kosdaq = kis.get_volume_rank(market="Q", top_n=100)
        items  = kospi + kosdaq

        symbols = []
        for item in items:
            sym = item.get("mksc_shrn_iscd") or item.get("stck_shrn_iscd", "")
            if sym and sym not in symbols:
                symbols.append(sym)

        result["symbols"] = symbols[:200]
        result["fetched"] = len(result["symbols"])
        logger.info(f"[NightlyTrainer] Top200 수집 완료: {result['fetched']}개")

    except Exception as e:
        logger.warning(f"[NightlyTrainer] OHLCV 수집 실패 (기존 데이터 사용): {e}")
        result["source"]  = "cache"
        result["skipped"] = 200

    return result


# ── Step 2: 파인튜닝 ───────────────────────────────────────────────────────────
def finetune_stage(model_path: Path, samples, class_weights_list,
                   n_classes=2, target_metric="recall", target_class=0) -> dict:
    """기존 모델을 로드해 파인튜닝. 성능 지표 반환."""
    if not model_path.exists():
        return {"ok": False, "error": f"{model_path.name} 없음"}

    rng = np.random.default_rng(SEED)
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

    scaler = StandardScaler()
    tr_ds  = SurgeDataset(tr_samples, df_feat, scaler, _make_train_transform(), fit_scaler=True)
    va_ds  = SurgeDataset(va_samples, df_feat, scaler, _make_val_transform())

    tr_dl = DataLoader(tr_ds, batch_size=BATCH_SIZE, sampler=sampler, num_workers=0)
    va_dl = DataLoader(va_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    # 기존 모델 로드
    ckpt  = torch.load(model_path, map_location=DEVICE, weights_only=False)
    model = StageModel(n_classes=n_classes).to(DEVICE)
    model.load_state_dict(ckpt["model_state_dict"])

    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    criterion = nn.CrossEntropyLoss(weight=cls_w)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)

    best_metric = 0.0
    best_state  = None

    for epoch in range(1, FINETUNE_EPOCHS + 1):
        model.train()
        for imgs, feats, lbls in tr_dl:
            imgs, feats, lbls = imgs.to(DEVICE), feats.to(DEVICE), lbls.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(imgs, feats), lbls)
            loss.backward()
            optimizer.step()
        scheduler.step()

        model.eval()
        va_pred, va_true = [], []
        with torch.no_grad():
            for imgs, feats, lbls in va_dl:
                out = model(imgs.to(DEVICE), feats.to(DEVICE))
                va_pred.extend(out.argmax(1).cpu().tolist())
                va_true.extend(lbls.tolist())

        rec_arr  = recall_score(va_true, va_pred, average=None,
                                labels=list(range(n_classes)), zero_division=0)
        prec_arr = precision_score(va_true, va_pred, average=None,
                                   labels=list(range(n_classes)), zero_division=0)
        key_metric = rec_arr[target_class] if target_metric == "recall" else prec_arr[target_class]

        if key_metric > best_metric:
            best_metric = key_metric
            best_state  = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        va_acc = sum(p == t for p, t in zip(va_pred, va_true)) / len(va_true) * 100
        logger.info(
            f"  [{model_path.stem}] Epoch {epoch:2d}/{FINETUNE_EPOCHS}: "
            f"Acc={va_acc:.1f}% | cls0 Recall={rec_arr[0]*100:.1f}% Prec={prec_arr[0]*100:.1f}%"
        )

    # 최종 평가
    model.load_state_dict({k: v.to(DEVICE) for k, v in best_state.items()})
    model.eval()
    va_pred, va_true = [], []
    with torch.no_grad():
        for imgs, feats, lbls in va_dl:
            out = model(imgs.to(DEVICE), feats.to(DEVICE))
            va_pred.extend(out.argmax(1).cpu().tolist())
            va_true.extend(lbls.tolist())

    acc   = sum(p == t for p, t in zip(va_pred, va_true)) / len(va_true) * 100
    prec  = precision_score(va_true, va_pred, average=None,
                            labels=list(range(n_classes)), zero_division=0)
    rec   = recall_score(va_true, va_pred, average=None,
                         labels=list(range(n_classes)), zero_division=0)

    # 저장
    torch.save({
        "model_state_dict": best_state,
        "n_classes":        n_classes,
        "best_val_acc":     acc,
        "scaler_mean":      scaler.mean_.tolist(),
        "scaler_scale":     scaler.scale_.tolist(),
        "trained_at":       datetime.now().isoformat(),
    }, model_path)

    return {
        "ok":        True,
        "accuracy":  round(acc, 2),
        "precision": [round(float(p) * 100, 1) for p in prec],
        "recall":    [round(float(r) * 100, 1) for r in rec],
    }


# ── Step 3: 메트릭 저장/비교 ─────────────────────────────────────────────────
def load_prev_metrics() -> dict:
    if METRICS_PATH.exists():
        try:
            return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_metrics(metrics: dict):
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")


def delta_str(cur: float, prev: float) -> str:
    d = cur - prev
    return f"▲{d:+.1f}%" if d >= 0 else f"▼{d:.1f}%"


# ── Step 4: 텔레그램 리포트 ──────────────────────────────────────────────────
def send_report(ohlcv_result: dict, s1_result: dict, s2_result: dict,
                prev: dict, duration_sec: float, success: bool, error: str = ""):
    tg = get_telegram_notifier()

    if not success:
        tg.send(f"⚠️ <b>야간 재학습 실패</b>\n{error}\n{datetime.now():%Y-%m-%d %H:%M:%S}")
        return

    # 델타 계산
    prev_s1_prec = prev.get("s1_precision_cls0", 0.0)
    prev_s2_prec = prev.get("s2_precision_cls0", 0.0)
    cur_s1_prec  = s1_result.get("precision", [0])[0]
    cur_s2_prec  = s2_result.get("precision", [0])[0]

    d_s1 = delta_str(cur_s1_prec, prev_s1_prec) if prev_s1_prec else "N/A(첫실행)"
    d_s2 = delta_str(cur_s2_prec, prev_s2_prec) if prev_s2_prec else "N/A(첫실행)"

    mins = int(duration_sec // 60)
    secs = int(duration_sec % 60)

    msg = (
        f"🌙 <b>야간 재학습 완료</b>\n"
        f"─────────────────────\n"
        f"📅 {datetime.now():%Y-%m-%d %H:%M}\n"
        f"⏱ 소요시간: {mins}분 {secs}초\n"
        f"📊 처리 종목: {ohlcv_result.get('fetched', 0)}개 "
        f"(소스: {ohlcv_result.get('source', '?')})\n"
        f"\n"
        f"<b>Stage1 급등감지</b>\n"
        f"  Acc: {s1_result.get('accuracy', 0):.1f}%\n"
        f"  Precision(surge): {cur_s1_prec:.1f}%  {d_s1}\n"
        f"  Recall(surge):    {s1_result.get('recall', [0])[0]:.1f}%\n"
        f"\n"
        f"<b>Stage2 진위판별</b>\n"
        f"  Acc: {s2_result.get('accuracy', 0):.1f}%\n"
        f"  Precision(success): {cur_s2_prec:.1f}%  {d_s2}\n"
        f"  Recall(success):    {s2_result.get('recall', [0])[0]:.1f}%\n"
        f"\n"
        f"✅ 모델 업데이트 완료 — 내일 매매 준비됨"
    )
    tg.send(msg)


# ── 데이터 로딩 ───────────────────────────────────────────────────────────────
def load_raw():
    rng = np.random.default_rng(SEED)
    success, fail, normal = [], [], []
    for folder in ("success", "fail", "normal"):
        fdir = DATA_DIR / folder
        if not fdir.exists():
            logger.warning(f"[NightlyTrainer] {fdir} 없음")
            continue
        files = list(fdir.glob("*.png"))
        if folder == "fail" and len(files) > FAIL_MAX:
            files = rng.choice(files, FAIL_MAX, replace=False).tolist()
        if folder == "success": success = files
        elif folder == "fail":  fail    = files
        else:                   normal  = files
        logger.info(f"  {folder}: {len(files):,}개")
    return success, fail, normal


# ── 메인 사이클 ───────────────────────────────────────────────────────────────
def run_nightly_cycle():
    logger.info("[NightlyTrainer] 야간 재학습 사이클 시작")
    started = time.time()

    ohlcv_result = {}
    s1_result    = {}
    s2_result    = {}
    error_msg    = ""

    try:
        # Step 1: 데이터 수집
        logger.info("[NightlyTrainer] Step1: Top200 OHLCV 수집")
        ohlcv_result = fetch_top200_ohlcv()

        # Step 2: 파인튜닝
        logger.info("[NightlyTrainer] Step2: 모델 파인튜닝")
        success_files, fail_files, normal_files = load_raw()

        s1_samples = (
            [(f, 0) for f in success_files] +
            [(f, 0) for f in fail_files] +
            [(f, 1) for f in normal_files]
        )
        s1_result = finetune_stage(
            SAVE_S1, s1_samples,
            class_weights_list=[5.0, 1.0],
            n_classes=2, target_metric="recall", target_class=0,
        )
        if not s1_result.get("ok"):
            raise RuntimeError(f"Stage1 실패: {s1_result.get('error')}")

        s2_samples = (
            [(f, 0) for f in success_files] +
            [(f, 1) for f in fail_files]
        )
        s2_result = finetune_stage(
            SAVE_S2, s2_samples,
            class_weights_list=[3.0, 1.0],
            n_classes=2, target_metric="precision", target_class=0,
        )
        if not s2_result.get("ok"):
            raise RuntimeError(f"Stage2 실패: {s2_result.get('error')}")

        # Step 3: 비교 및 저장
        prev = load_prev_metrics()
        new_metrics = {
            "date":              datetime.now().strftime("%Y-%m-%d"),
            "s1_accuracy":       s1_result["accuracy"],
            "s1_precision_cls0": s1_result["precision"][0],
            "s1_recall_cls0":    s1_result["recall"][0],
            "s2_accuracy":       s2_result["accuracy"],
            "s2_precision_cls0": s2_result["precision"][0],
            "s2_recall_cls0":    s2_result["recall"][0],
        }
        save_metrics(new_metrics)

        duration = time.time() - started
        send_report(ohlcv_result, s1_result, s2_result, prev, duration, success=True)
        logger.info(f"[NightlyTrainer] 완료 ({duration/60:.1f}분)")

    except Exception as e:
        logger.error(f"[NightlyTrainer] 실패: {e}", exc_info=True)
        error_msg = str(e)
        duration  = time.time() - started
        send_report(ohlcv_result, s1_result, s2_result, {}, duration,
                    success=False, error=error_msg)


# ── 스케줄러 ──────────────────────────────────────────────────────────────────
def wait_until_2100():
    """21:00 KST까지 대기. 이미 지났으면 내일 21:00."""
    now    = datetime.now()
    target = now.replace(hour=21, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    wait = (target - datetime.now()).total_seconds()
    logger.info(f"[NightlyTrainer] 21:00까지 대기 ({wait/3600:.1f}시간)")
    time.sleep(wait)


def run_scheduler():
    """매일 21:00 KST 자동 실행 루프."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                BASE_DIR / "storage" / "logs" / "nightly_trainer.log",
                encoding="utf-8"
            ),
        ]
    )
    logger.info("[NightlyTrainer] 스케줄러 시작 — 매일 21:00 KST 실행")
    while True:
        wait_until_2100()
        run_nightly_cycle()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="즉시 1회 실행 (테스트용)")
    args = parser.parse_args()

    if args.now:
        logging.basicConfig(level=logging.INFO,
                            format="[%(asctime)s] %(levelname)s %(message)s")
        run_nightly_cycle()
    else:
        run_scheduler()
