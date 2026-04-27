import logging
import warnings
from pathlib import Path
from typing import Optional, List, Dict

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

# ── 경로 ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
CSV_DIR    = BASE_DIR / "data" / "csv"
SAVE_ROOT  = BASE_DIR / "storage" / "chart_images"
AFTER_DIR  = SAVE_ROOT / "after_analysis"
BEFORE_DIR = SAVE_ROOT / "before_prediction"

# ── 봉 단위 ───────────────────────────────────────────────────────────────────
CHART_BARS  = 60   # 이미지 1장
FUTURE_9M   = 3    # 9분  = 3분봉 3개
FUTURE_10M  = 4    # 10분 ≈ 3분봉 4개
FUTURE_20M  = 7    # 20분 ≈ 3분봉 7개
FUTURE_30M  = 10   # 30분 = 3분봉 10개
FUTURE_60M  = 20   # 60분 = 3분봉 20개
VOL_LOOK    = 10   # 거래량 평균 기준 직전 봉 수

# ── 라벨링 임계값 ─────────────────────────────────────────────────────────────
OUTLIER_RATIO  = 50.0  # 이상치 거래량 배수

SURGE_VOL      = 2.0;  SURGE_30   = 0.03;  SURGE_60   = 0.01
STRONG_VOL     = 3.0;  STRONG_30  = 0.05;  STRONG_60  = 0.03
FAKE_VOL       = 1.5;  FAKE_RISE  = 0.02;  FAKE_FALL  = 0.02
PUMP_RISE      = 0.05; PUMP_FALL  = 0.05
TRAP_VOL       = 3.0;  TRAP_FALL  = 0.01
NORMAL_UP_RET  = 0.02; DECLINE_RET = -0.02

NORMAL_MAX_AFTER  = 100   # 파일당 normal 계열 최대
NORMAL_MAX_BEFORE = 50    # 파일당 normal_before 최대

# ── 라벨 → 폴더 ───────────────────────────────────────────────────────────────
AFTER_FOLDER = {
    "strong_surge": "success", "surge":     "success",
    "fake_surge":   "fail",    "pump_dump": "fail",
    "volume_trap":  "fail",    "decline":   "fail",
    "normal_up":    "normal",  "sideways":  "normal",
}
BEFORE_FOLDER = {
    "surge_before":        "surge_before",
    "pump_dump_before":    "pump_dump_before",
    "accumulation_before": "accumulation_before",
    "normal_before":       "normal_before",
}

# ── 이미지 설정 ───────────────────────────────────────────────────────────────
IMG_W = 12; IMG_H = 7; DPI = 100; BAR_W = 0.7; SIDE_PAD = 1.0


# ─────────────────────────────────────────────────────────────────────────────
class CandleBuilder:

    def build_3m_from_1m(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.resample("3min").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "volume": "sum"}
        ).dropna()

    def build_from_csv(self, path: str) -> Optional[pd.DataFrame]:
        try:
            df = _load_csv(path)
            return self.build_3m_from_1m(df) if df is not None else None
        except Exception as e:
            logger.error(e); return None

    def run_all(self) -> None:
        _makedirs()
        files = sorted(CSV_DIR.glob("*_1m.csv"))
        print(f"\n{'='*62}")
        print(f"  전체 {len(files)}개 파일 처리 시작")
        print(f"{'='*62}\n")

        after_recs  : List[dict] = []
        before_recs : List[dict] = []
        totals_a    : Dict[str, int] = {}
        totals_b    : Dict[str, int] = {}

        prev_stats = _load_prev_stats()   # 수정 전 통계

        for idx, f in enumerate(files, 1):
            ticker = f.stem.replace("_1m", "")
            print(f"[{idx:3d}/{len(files)}] {ticker}", end="  ", flush=True)

            df_1m = _load_csv(str(f))
            if df_1m is None:
                print("로드 실패"); continue

            df3 = self.build_3m_from_1m(df_1m)
            if len(df3) < CHART_BARS + FUTURE_60M + 2:
                print(f"봉 부족({len(df3)}), 스킵"); continue

            # ── Part 1: after_analysis ────────────────────────────────────
            df3 = _label_after(df3)
            a_recs = _save_after(df3, ticker)
            after_recs.extend(a_recs)
            for r in a_recs:
                totals_a[r["label"]] = totals_a.get(r["label"], 0) + 1

            a_cnt = {k: v for k, v in
                     pd.Series([r["label"] for r in a_recs]).value_counts().items()}
            print(f"after={sum(a_cnt.values())}  ", end="")

            # ── Part 2: before_prediction ─────────────────────────────────
            b_recs = _save_before(df3, ticker)
            before_recs.extend(b_recs)
            for r in b_recs:
                totals_b[r["label"]] = totals_b.get(r["label"], 0) + 1

            b_cnt = {k: v for k, v in
                     pd.Series([r["label"] for r in b_recs]).value_counts().items()}
            print(f"before={sum(b_cnt.values())}")

        # ── CSV 저장 ──────────────────────────────────────────────────────
        if after_recs:
            pd.DataFrame(after_recs).to_csv(
                SAVE_ROOT / "labels_after_analysis.csv",
                index=False, encoding="utf-8-sig")
        if before_recs:
            pd.DataFrame(before_recs).to_csv(
                SAVE_ROOT / "labels_before_prediction.csv",
                index=False, encoding="utf-8-sig")

        _print_report(totals_a, totals_b,
                      pd.DataFrame(after_recs)  if after_recs  else pd.DataFrame(),
                      pd.DataFrame(before_recs) if before_recs else pd.DataFrame(),
                      prev_stats)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _makedirs():
    for sub in ("success", "fail", "normal", "outliers_after"):
        (AFTER_DIR / sub).mkdir(parents=True, exist_ok=True)
    for sub in ("surge_before", "pump_dump_before",
                "accumulation_before", "normal_before", "outliers_before"):
        (BEFORE_DIR / sub).mkdir(parents=True, exist_ok=True)


def _load_csv(path: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        df.columns = [c.lower() for c in df.columns]
        df.set_index("date", inplace=True)
        return df.sort_index()
    except Exception as e:
        logger.error(f"CSV 로드 실패: {e}"); return None


def _load_prev_stats() -> dict:
    """수정 전 통계 로드 (첫 실행이면 빈 dict)"""
    p = SAVE_ROOT / "labels_after_analysis.csv"
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p)
        return df["label"].value_counts().to_dict()
    except Exception:
        return {}


# ── Part 1 라벨링 ─────────────────────────────────────────────────────────────

def _label_after(df3: pd.DataFrame) -> pd.DataFrame:
    """
    우선순위: strong_surge > surge > pump_dump > fake_surge
              > volume_trap > normal_up > decline > sideways
    """
    n        = len(df3)
    labels   = ["sideways"] * n
    vol_avg  = df3["volume"].rolling(VOL_LOOK).mean()

    for i in range(VOL_LOOK, n - FUTURE_60M):
        c0      = df3["close"].iloc[i]
        c_9m    = df3["close"].iloc[i + FUTURE_9M]
        c_30m   = df3["close"].iloc[i + FUTURE_30M]
        c_60m   = df3["close"].iloc[i + FUTURE_60M]
        avg_vol = vol_avg.iloc[i]
        if pd.isna(avg_vol) or avg_vol <= 0:
            continue

        vol_r   = df3["volume"].iloc[i] / avg_vol
        ret_30  = (c_30m - c0) / c0
        ret_60  = (c_60m - c0) / c0
        bar_ret = (df3["close"].iloc[i] - df3["open"].iloc[i]) / df3["open"].iloc[i]

        # pump_dump: 10분 내 5% 급등 → 20분 내 5% 급락
        max_rise = max(df3["close"].iloc[i:i + FUTURE_10M + 1].max() / c0 - 1, 0)
        min_fall = df3["close"].iloc[i:i + FUTURE_20M + 1].min() / c0 - 1

        if vol_r >= STRONG_VOL and ret_30 >= STRONG_30 and ret_60 >= STRONG_60:
            labels[i] = "strong_surge"
        elif vol_r >= SURGE_VOL and ret_30 >= SURGE_30 and ret_60 >= SURGE_60:
            labels[i] = "surge"
        elif max_rise >= PUMP_RISE and min_fall <= -PUMP_FALL:
            labels[i] = "pump_dump"
        elif vol_r >= FAKE_VOL and bar_ret >= FAKE_RISE and (c_9m / c0 - 1) <= -FAKE_FALL:
            labels[i] = "fake_surge"
        elif vol_r >= TRAP_VOL and ret_30 <= -TRAP_FALL:
            labels[i] = "volume_trap"
        elif ret_30 >= NORMAL_UP_RET:
            labels[i] = "normal_up"
        elif ret_30 <= DECLINE_RET:
            labels[i] = "decline"
        else:
            labels[i] = "sideways"

    df3 = df3.copy()
    df3["label_after"] = labels
    df3["vol_ratio"]   = df3["volume"] / vol_avg
    return df3


# ── Part 2 라벨링 ─────────────────────────────────────────────────────────────

def _get_before_label(df3: pd.DataFrame, event_idx: int, after_label: str) -> str:
    """
    event_idx 이전 60봉 윈도우를 분석해 before 라벨 결정.
    surge/strong_surge → surge_before
    pump_dump/fake_surge/volume_trap → pump_dump_before
    quiet accumulation → accumulation_before
    else → normal_before
    """
    if after_label in ("surge", "strong_surge"):
        return "surge_before"
    if after_label in ("pump_dump", "fake_surge", "volume_trap"):
        return "pump_dump_before"

    # 매집 패턴: 60봉 윈도우 내 변동성 낮고 거래량 꾸준 1.0~1.5배
    start = max(0, event_idx - CHART_BARS)
    win   = df3.iloc[start:event_idx]
    if len(win) < 20:
        return "normal_before"

    returns    = win["close"].pct_change().dropna()
    volatility = returns.std()
    avg_vr     = win["vol_ratio"].mean() if "vol_ratio" in win.columns else 1.0
    price_trend = np.polyfit(range(len(win)), win["close"].values, 1)[0]

    if volatility < 0.003 and 1.0 <= avg_vr <= 1.5 and price_trend >= 0:
        return "accumulation_before"

    return "normal_before"


# ── 특징 추출 ─────────────────────────────────────────────────────────────────

def _extract_features(bars: pd.DataFrame, ticker: str,
                      ts: str, label: str, part: str) -> dict:
    closes  = bars["close"].values
    highs   = bars["high"].values
    lows    = bars["low"].values
    opens   = bars["open"].values
    volumes = bars["volume"].values

    recent_vol = volumes[-5:].mean()
    prev_vol   = volumes[-20:-5].mean() if len(volumes) >= 20 else volumes.mean()
    vol_ratio  = recent_vol / (prev_vol + 1e-9)

    # 거래량 추세 (기울기)
    vol_trend = float(np.polyfit(range(len(volumes)), volumes, 1)[0])

    bull_ratio = float(np.mean(closes[-10:] >= opens[-10:]))
    volatility = float(np.mean((highs - lows) / np.where(closes > 0, closes, 1)))

    s    = pd.Series(closes)
    ma5  = float(s.rolling(5).mean().iloc[-1])
    ma20 = float(s.rolling(20).mean().iloc[-1]) if len(s) >= 20 else float(s.mean())
    ma60 = float(s.rolling(60).mean().iloc[-1]) if len(s) >= 60 else float(s.mean())

    price_pos  = (closes[-1] - lows.min()) / (highs.max() - lows.min() + 1e-9)
    body       = np.abs(closes - opens)
    body_ratio = float(np.mean(body / (highs - lows + 1e-9)))

    # 연속 양봉 개수
    consec = 0
    for c, o in zip(reversed(closes), reversed(opens)):
        if c >= o:
            consec += 1
        else:
            break

    hour = int(ts[9:11]) if len(ts) >= 11 else 9
    session = "opening" if hour < 10 else ("closing" if hour >= 14 else "middle")

    return {
        "part":                    part,
        "ticker":                  ticker,
        "timestamp":               ts,
        "label":                   label,
        "volume_ratio":            round(vol_ratio, 3),
        "volume_trend":            round(vol_trend, 2),
        "volume_surge":            int(vol_ratio >= 1.5),
        "bullish_candle_ratio":    round(bull_ratio, 3),
        "volatility":              round(volatility, 5),
        "trend_short":             int(ma5 > ma20),
        "trend_long":              int(ma20 > ma60),
        "price_position":          round(float(price_pos), 3),
        "body_ratio":              round(body_ratio, 3),
        "time_session":            session,
        "consecutive_up_candles":  consec,
    }


# ── 이미지 생성 ───────────────────────────────────────────────────────────────

def _draw_chart(bars: pd.DataFrame, save_path: Path):
    """검은 배경, 빨강 양봉 / 파랑 음봉, 굵고 일정한 캔들, 고해상도"""
    fig  = plt.figure(figsize=(IMG_W, IMG_H), facecolor="black")
    gs   = GridSpec(4, 1, figure=fig, hspace=0)
    ax_c = fig.add_subplot(gs[:3, 0])
    ax_v = fig.add_subplot(gs[3:,  0], sharex=ax_c)

    for ax in (ax_c, ax_v):
        ax.set_facecolor("black")
        ax.axis("off")

    for xi, (_, row) in enumerate(bars.iterrows()):
        bull  = row["close"] >= row["open"]
        color = "#FF3333" if bull else "#3399FF"

        ax_c.plot([xi, xi], [row["low"], row["high"]],
                  color=color, linewidth=1.0, solid_capstyle="butt", zorder=1)

        body_lo = min(row["open"], row["close"])
        body_hi = max(row["open"], row["close"])
        min_h   = (row["high"] - row["low"]) * 0.05 or row["close"] * 0.001
        ax_c.bar(xi, max(body_hi - body_lo, min_h),
                 bottom=body_lo, width=BAR_W,
                 color=color, linewidth=0, zorder=2)

    vol_max = bars["volume"].max() or 1
    for xi, (_, row) in enumerate(bars.iterrows()):
        bull  = row["close"] >= row["open"]
        color = "#FF3333" if bull else "#3399FF"
        ax_v.bar(xi, row["volume"] / vol_max,
                 width=BAR_W, color=color, linewidth=0, alpha=0.85)

    xlim = (-SIDE_PAD, len(bars) - 1 + SIDE_PAD)
    ax_c.set_xlim(*xlim)
    ax_v.set_xlim(*xlim)
    ax_v.set_ylim(0, 1.15)

    plt.tight_layout(pad=0)
    fig.savefig(save_path, dpi=DPI, bbox_inches="tight",
                facecolor="black", pad_inches=0.03)
    plt.close(fig)


# ── Part 1 이미지 저장 ────────────────────────────────────────────────────────

def _save_after(df3: pd.DataFrame, ticker: str) -> List[dict]:
    n           = len(df3)
    records     = []
    normal_cnt  = 0
    outlier_cnt = 0

    for i in range(CHART_BARS, n - FUTURE_60M):
        label   = df3["label_after"].iloc[i]
        vol_r   = df3["vol_ratio"].iloc[i]
        folder  = AFTER_FOLDER.get(label, "normal")

        # 이상치 격리
        if not pd.isna(vol_r) and vol_r > OUTLIER_RATIO:
            bars  = df3.iloc[i - CHART_BARS:i]
            ts    = df3.index[i].strftime("%Y%m%d_%H%M")
            fname = f"{ticker}_{ts}_after_{label}_outlier.png"
            _draw_chart(bars, AFTER_DIR / "outliers_after" / fname)
            outlier_cnt += 1
            continue

        # normal 계열 샘플 제한
        if folder == "normal":
            if normal_cnt >= NORMAL_MAX_AFTER:
                continue
            normal_cnt += 1

        bars = df3.iloc[i - CHART_BARS:i]
        ts   = df3.index[i].strftime("%Y%m%d_%H%M")
        tend = df3.index[i - 1].strftime("%H%M")
        fname = f"{ticker}_{ts}_to_{tend}_after_{label}.png"

        _draw_chart(bars, AFTER_DIR / folder / fname)
        rec = _extract_features(bars, ticker, ts, label, "after")
        rec["vol_ratio_at_event"] = round(float(vol_r) if not pd.isna(vol_r) else 0, 2)
        records.append(rec)

    return records


# ── Part 2 이미지 저장 ────────────────────────────────────────────────────────

def _save_before(df3: pd.DataFrame, ticker: str) -> List[dict]:
    n           = len(df3)
    records     = []
    normal_cnt  = 0
    event_labels = {"surge", "strong_surge", "pump_dump",
                    "fake_surge", "volume_trap"}

    for i in range(CHART_BARS + FUTURE_60M, n - FUTURE_60M):
        after_label = df3["label_after"].iloc[i]
        vol_r       = df3["vol_ratio"].iloc[i]

        # before 이미지: 현재 봉 i 의 60봉 전까지 (급등 전조 패턴 구간)
        before_start = i - CHART_BARS
        before_end   = i   # 급등 시점 바로 전

        # 이벤트 또는 주기적 샘플링만 저장
        is_event = after_label in event_labels
        is_sample = (not is_event) and (i % 3 == 0)  # 3봉마다 normal 샘플

        if not is_event and not is_sample:
            continue

        if not is_event:
            if normal_cnt >= NORMAL_MAX_BEFORE:
                continue
            normal_cnt += 1

        before_label = _get_before_label(df3, i, after_label)
        folder       = BEFORE_FOLDER.get(before_label, "normal_before")

        # 이상치
        if not pd.isna(vol_r) and vol_r > OUTLIER_RATIO:
            bars  = df3.iloc[before_start:before_end]
            ts    = df3.index[before_start].strftime("%Y%m%d_%H%M")
            fname = f"{ticker}_{ts}_before_{before_label}_outlier.png"
            _draw_chart(bars, BEFORE_DIR / "outliers_before" / fname)
            continue

        bars = df3.iloc[before_start:before_end]
        if len(bars) < CHART_BARS:
            continue

        ts    = df3.index[before_start].strftime("%Y%m%d_%H%M")
        tend  = df3.index[before_end - 1].strftime("%H%M")
        fname = f"{ticker}_{ts}_to_{tend}_before_{before_label}.png"

        _draw_chart(bars, BEFORE_DIR / folder / fname)
        rec = _extract_features(bars, ticker, ts, before_label, "before")
        rec["event_after"]         = after_label
        rec["vol_ratio_at_event"]  = round(float(vol_r) if not pd.isna(vol_r) else 0, 2)
        records.append(rec)

    return records


# ── 리포트 ────────────────────────────────────────────────────────────────────

def _print_report(ta: dict, tb: dict,
                  df_a: pd.DataFrame, df_b: pd.DataFrame,
                  prev: dict):
    sep = "=" * 62
    print(f"\n{sep}")
    print("  통합 통계 리포트")
    print(sep)

    # ── After Analysis ──
    print("\n[ Part 1: After Analysis ]")
    total_a = sum(ta.values())
    for lbl in ("strong_surge", "surge", "fake_surge", "pump_dump",
                "volume_trap", "normal_up", "sideways", "decline"):
        cnt = ta.get(lbl, 0)
        pct = cnt / total_a * 100 if total_a else 0
        print(f"  {lbl:20s} {cnt:5d}개 ({pct:5.1f}%)")
    print(f"  {'합계':20s} {total_a:5d}개")

    fail_sum = sum(ta.get(l, 0) for l in ("fake_surge","pump_dump","volume_trap"))
    print(f"\n  ※ 가짜 급등 합계(fake+pump+trap): {fail_sum}개  ", end="")
    if fail_sum >= 500:
        print("✔ 500개 이상 충족")
    else:
        print(f"✘ 목표 500개 미달 ({500 - fail_sum}개 부족)")

    # surge vs fake 거래량 비교
    if not df_a.empty and "vol_ratio_at_event" in df_a.columns:
        s_vr = df_a[df_a["label"].isin(["surge","strong_surge"])]["vol_ratio_at_event"]
        f_vr = df_a[df_a["label"] == "fake_surge"]["vol_ratio_at_event"]
        print(f"\n  surge       평균 거래량 비율: {s_vr.mean():.2f}배  (n={len(s_vr)})")
        print(f"  fake_surge  평균 거래량 비율: {f_vr.mean():.2f}배  (n={len(f_vr)})")

    # 급등 시간대
    if not df_a.empty and "time_session" in df_a.columns:
        sess = df_a[df_a["label"].isin(["surge","strong_surge"])]["time_session"].value_counts()
        print(f"\n  급등 다발 시간대: {sess.to_dict()}")

    # 이상치
    out_after = len(list((AFTER_DIR / "outliers_after").glob("*.png")))
    print(f"  이상치(거래량 50배↑): {out_after}개 → outliers_after/")

    # ── Before Prediction ──
    print(f"\n[ Part 2: Before Prediction ]")
    total_b = sum(tb.values())
    for lbl in ("surge_before", "pump_dump_before",
                "accumulation_before", "normal_before"):
        cnt = tb.get(lbl, 0)
        pct = cnt / total_b * 100 if total_b else 0
        print(f"  {lbl:25s} {cnt:5d}개 ({pct:5.1f}%)")
    print(f"  {'합계':25s} {total_b:5d}개")

    if not df_b.empty and "vol_ratio_at_event" in df_b.columns:
        sb = df_b[df_b["label"] == "surge_before"]["vol_ratio_at_event"]
        pb = df_b[df_b["label"] == "pump_dump_before"]["vol_ratio_at_event"]
        print(f"\n  surge_before     거래량 비율: {sb.mean():.2f}배")
        print(f"  pump_dump_before 거래량 비율: {pb.mean():.2f}배")

    out_before = len(list((BEFORE_DIR / "outliers_before").glob("*.png")))
    print(f"  이상치: {out_before}개 → outliers_before/")

    # ── 수정 전 vs 수정 후 ──
    if prev:
        print(f"\n[ 수정 전 vs 수정 후 비교 ]")
        print(f"  {'라벨':<20s} {'수정 전':>8s}  {'수정 후':>8s}  {'변화':>8s}")
        print(f"  {'-'*50}")
        all_lbls = sorted(set(list(prev.keys()) + list(ta.keys())))
        for lbl in all_lbls:
            before_n = prev.get(lbl, 0)
            after_n  = ta.get(lbl, 0)
            delta    = after_n - before_n
            sign     = "+" if delta >= 0 else ""
            print(f"  {lbl:<20s} {before_n:>8d}  {after_n:>8d}  {sign}{delta:>7d}")

    # ── 급등 Top 10 ──
    if not df_a.empty and "vol_ratio_at_event" in df_a.columns:
        top10 = df_a[df_a["label"].isin(["strong_surge","surge"])]\
                    .nlargest(10, "vol_ratio_at_event")
        if len(top10):
            print(f"\n[ 급등 패턴 Top 10 (거래량 비율) ]")
            for _, r in top10.iterrows():
                print(f"  {r['ticker']}  {r['timestamp']}  "
                      f"{r['label']}  vol:{r['vol_ratio_at_event']:.1f}x  "
                      f"session:{r['time_session']}")

    # ── 권장 사항 ──
    print(f"\n[ 모델 활용 권장 ]")
    print("  Before 모델: 급등 60분 전 패턴으로 진입 신호 포착")
    print("  After  모델: 급등 발생 중 진짜/가짜 여부 즉시 판별")
    print("  조합 전략 : Before → 진입 / After → 검증 · 청산")
    print(f"\n  저장 경로: {SAVE_ROOT}")
    print(sep)


def get_candle_builder() -> "CandleBuilder":
    return CandleBuilder()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    CandleBuilder().run_all()
