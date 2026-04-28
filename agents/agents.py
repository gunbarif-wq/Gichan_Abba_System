"""
Agent implementations
VisionAgent (ResNet18+MLP), SupplyAgent, NewsAgent, CriticAgent, CouncilAgent
"""

import logging
import tempfile
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from shared.schemas import AgentScore, Candidate

logger = logging.getLogger(__name__)

BASE_DIR   = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "active" / "surge_detector.pt"

FEATURE_COLS = [
    "volume_ratio", "volume_surge", "bullish_candle_ratio",
    "volatility", "trend_short", "trend_long",
    "price_position", "body_ratio",
]
CLASS_MAP = {0: "success", 1: "fail", 2: "normal"}


# ── SurgeDetector 아키텍처 (학습 코드와 동일해야 함) ──────────────────────────

def _build_model():
    import torch.nn as nn
    from torchvision import models

    class SurgeDetector(nn.Module):
        def __init__(self, n_features=8, n_classes=3):
            super().__init__()
            self.cnn = models.resnet18(weights=None)
            self.cnn.fc = nn.Identity()
            self.mlp = nn.Sequential(
                nn.Linear(n_features, 64), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(64, 32),         nn.ReLU(),
            )
            self.fusion = nn.Sequential(
                nn.Linear(512 + 32, 256), nn.ReLU(), nn.Dropout(0.4),
                nn.Linear(256, 128),      nn.ReLU(),
                nn.Linear(128, n_classes),
            )

        def forward(self, img, feat):
            return self.fusion(
                __import__("torch").cat([self.cnn(img), self.mlp(feat)], dim=1)
            )

    return SurgeDetector


# ── 차트 이미지 생성 (학습 시 사용한 _draw_chart 동일 스타일) ─────────────────

def _draw_chart_to_file(bars: pd.DataFrame) -> Optional[str]:
    """60개 3분봉 → 임시 PNG 파일 경로 반환. 실패 시 None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        IMG_W, IMG_H, DPI = 12, 7, 100
        BAR_W, SIDE_PAD   = 0.7, 1.0

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
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        fig.savefig(tmp.name, dpi=DPI, bbox_inches="tight",
                    facecolor="black", pad_inches=0.03)
        plt.close(fig)
        return tmp.name
    except Exception as e:
        logger.error(f"[VisionAgent] 차트 생성 실패: {e}")
        return None


# ── 수치 특징 추출 ─────────────────────────────────────────────────────────────

def _extract_features(df: pd.DataFrame) -> List[float]:
    """FEATURE_COLS 순서대로 8개 특징 추출"""
    closes  = df["close"].values.astype(float)
    highs   = df["high"].values.astype(float)
    lows    = df["low"].values.astype(float)
    opens   = df["open"].values.astype(float)
    volumes = df["volume"].values.astype(float)

    n = len(closes)

    recent_vol = volumes[-5:].mean()
    prev_vol   = volumes[-20:-5].mean() if n >= 20 else (volumes.mean() or 1)
    volume_ratio = recent_vol / (prev_vol + 1e-9)

    volume_surge = float(volume_ratio >= 1.5)

    k = min(10, n)
    bullish_candle_ratio = float(np.mean(closes[-k:] >= opens[-k:]))

    volatility = float(np.mean((highs - lows) / np.where(closes > 0, closes, 1)))

    s    = pd.Series(closes)
    ma5  = float(s.rolling(5).mean().iloc[-1])
    ma20 = float(s.rolling(20).mean().iloc[-1]) if n >= 20 else float(s.mean())
    ma60 = float(s.rolling(60).mean().iloc[-1]) if n >= 60 else float(s.mean())
    trend_short = float(ma5 > ma20)
    trend_long  = float(ma20 > ma60)

    price_position = (closes[-1] - lows.min()) / (highs.max() - lows.min() + 1e-9)

    body       = np.abs(closes - opens)
    body_ratio = float(np.mean(body / (highs - lows + 1e-9)))

    return [volume_ratio, volume_surge, bullish_candle_ratio,
            volatility, trend_short, trend_long,
            float(price_position), body_ratio]


# ── VisionAgent ───────────────────────────────────────────────────────────────

class VisionAgent:
    """
    ResNet18+MLP 멀티모달 모델로 3분봉 차트 + 수치 특징 분석
    success(0) / fail(1) / normal(2) 3-class 분류
    """

    def __init__(self):
        self._model        = None
        self._scaler_mean  = None
        self._scaler_scale = None
        self._device       = None
        self._transform    = None
        self._loaded       = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch
            from torchvision import transforms

            if not MODEL_PATH.exists():
                logger.warning("[VisionAgent] surge_detector.pt 없음 — 학습 완료 후 자동 로드")
                return

            ckpt = torch.load(str(MODEL_PATH), map_location="cpu")

            SurgeDetector = _build_model()
            model = SurgeDetector(n_features=len(FEATURE_COLS))
            model.load_state_dict(ckpt["model_state_dict"])

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model.to(device).eval()

            self._model        = model
            self._device       = device
            self._scaler_mean  = np.array(ckpt["scaler_mean"], dtype=np.float32)
            self._scaler_scale = np.array(ckpt["scaler_scale"], dtype=np.float32)
            self._transform    = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406],
                                     [0.229, 0.224, 0.225]),
            ])
            self._loaded = True
            best_acc = ckpt.get("best_val_acc", 0.0)
            logger.info(f"[VisionAgent] 모델 로드 완료 (val_acc={best_acc:.1f}%)")

        except Exception as e:
            logger.error(f"[VisionAgent] 모델 로드 실패: {e}")

    def _reload_if_needed(self) -> None:
        if not self._loaded and MODEL_PATH.exists():
            self._load_model()

    def analyze(self, symbol: str, df_3m: pd.DataFrame = None, **kwargs) -> AgentScore:
        """차트 + 수치 특징 분석 → AgentScore"""
        self._reload_if_needed()

        if df_3m is None or len(df_3m) < 20:
            return AgentScore(
                agent_name="vision_agent", symbol=symbol,
                score=30.0, reason="데이터 부족",  # 중립 아닌 경계값
            )
        if not self._loaded:
            return AgentScore(
                agent_name="vision_agent", symbol=symbol,
                score=35.0, reason="모델 미로드",
            )

        bars = df_3m.tail(60)

        # ① 수치 특징 추출 + 스케일링
        raw_feat = _extract_features(bars)
        feat_arr = (np.array(raw_feat, dtype=np.float32) - self._scaler_mean) / (self._scaler_scale + 1e-9)

        # ② 차트 이미지 생성
        img_path = _draw_chart_to_file(bars)

        try:
            import torch
            from PIL import Image

            feat_t = torch.tensor(feat_arr).unsqueeze(0).to(self._device)

            if img_path:
                img = Image.open(img_path).convert("RGB")
                img_t = self._transform(img).unsqueeze(0).to(self._device)
                try:
                    import os
                    os.unlink(img_path)
                except Exception:
                    pass
            else:
                # fallback: 빈 이미지
                img_t = torch.zeros(1, 3, 224, 224).to(self._device)

            with torch.no_grad():
                logits = self._model(img_t, feat_t)
                probs  = torch.softmax(logits, dim=1).squeeze().cpu().numpy()

            success_prob = float(probs[0])
            fail_prob    = float(probs[1])
            normal_prob  = float(probs[2])
            pred_class   = int(np.argmax(probs))
            pred_label   = CLASS_MAP[pred_class]

            # success 확률이 높을수록 점수 높음 (fail이면 낮음)
            score  = success_prob * 100 - fail_prob * 30
            score  = max(0.0, min(100.0, score))
            reason = (f"예측={pred_label} "
                      f"(success={success_prob:.1%} fail={fail_prob:.1%})")

            return AgentScore(
                agent_name="vision_agent", symbol=symbol,
                score=score, reason=reason,
                metadata={"probs": probs.tolist(), "pred": pred_label},
            )

        except Exception as e:
            logger.error(f"[VisionAgent] 추론 실패 {symbol}: {e}")
            return AgentScore(
                agent_name="vision_agent", symbol=symbol,
                score=30.0, reason=f"추론 오류: {e}",
            )


# ── SupplyAgent ───────────────────────────────────────────────────────────────

class SupplyAgent:
    """
    수급 분석
    거래량 비율, 매수/매도 체결 비율, 전일 대비 거래량 변화로 판단
    """

    def __init__(self):
        logger.info("[SupplyAgent] 초기화")

    def analyze(self, symbol: str, df_3m: pd.DataFrame = None,
                buy_ratio: float = 0.5, volume_ratio: float = 1.0,
                **kwargs) -> AgentScore:
        """
        수급 분석
        buy_ratio:    매수 체결 비율 (0~1, 0.5=중립)
        volume_ratio: 현재 거래량 / 직전 20봉 평균 거래량
        """
        score  = 50.0
        reason_parts = []

        # 거래량 수급 점수
        if volume_ratio >= 3.0:
            score += 20; reason_parts.append(f"거래량{volume_ratio:.1f}배급증")
        elif volume_ratio >= 2.0:
            score += 12; reason_parts.append(f"거래량{volume_ratio:.1f}배증가")
        elif volume_ratio >= 1.5:
            score += 6;  reason_parts.append(f"거래량{volume_ratio:.1f}배")
        elif volume_ratio < 0.7:
            score -= 10; reason_parts.append("거래량부족")

        # 매수/매도 비율 점수
        if buy_ratio >= 0.65:
            score += 20; reason_parts.append(f"매수우위{buy_ratio:.0%}")
        elif buy_ratio >= 0.55:
            score += 10; reason_parts.append(f"매수우세{buy_ratio:.0%}")
        elif buy_ratio <= 0.40:
            score -= 15; reason_parts.append(f"매도우위{buy_ratio:.0%}")
        elif buy_ratio <= 0.45:
            score -= 8;  reason_parts.append(f"매도우세{buy_ratio:.0%}")

        # df_3m 기반 추가 분석
        if df_3m is not None and len(df_3m) >= 5:
            vols   = df_3m["volume"].values[-20:]
            recent = vols[-3:].mean()
            prev   = vols[:-3].mean() if len(vols) > 3 else recent
            vol_trend = recent / (prev + 1e-9)
            if vol_trend >= 1.5:
                score += 5; reason_parts.append("거래량증가추세")

        score = max(0.0, min(100.0, score))
        return AgentScore(
            agent_name="supply_agent", symbol=symbol,
            score=score,
            reason=", ".join(reason_parts) if reason_parts else "수급 중립",
            metadata={"buy_ratio": buy_ratio, "volume_ratio": volume_ratio},
        )


# ── NewsAgent ─────────────────────────────────────────────────────────────────

class NewsAgent:
    """
    뉴스/공시 분석
    PreMarketScanner의 뉴스 점수 및 테마 점수를 활용
    """

    def __init__(self):
        logger.info("[NewsAgent] 초기화")

    def analyze(self, symbol: str,
                news_score: float = 0.0,
                theme_rank: int = 0,
                premarket_score: float = 0.0,
                premarket_reasons: List[str] = None,
                **kwargs) -> AgentScore:
        """
        뉴스/테마 분석
        news_score:       PreMarketScanner의 뉴스 점수 (0~15)
        theme_rank:       테마 순위 (0=해당없음)
        premarket_score:  PreMarketScanner 종합 점수
        """
        score  = 50.0
        reason_parts = []

        if news_score > 0:
            bonus = min(news_score * 2, 20)
            score += bonus
            reason_parts.append("뉴스/공시")

        if theme_rank > 0:
            bonus = max(0, 10 - theme_rank) * 2
            score += bonus
            reason_parts.append(f"테마{theme_rank}위")

        if premarket_score > 20:
            bonus = min(premarket_score * 0.5, 15)
            score += bonus
            if premarket_reasons:
                reason_parts.extend(premarket_reasons[:2])

        score = max(0.0, min(100.0, score))
        return AgentScore(
            agent_name="news_agent", symbol=symbol,
            score=score,
            reason=", ".join(reason_parts) if reason_parts else "뉴스/테마 없음",
            metadata={"news_score": news_score, "theme_rank": theme_rank},
        )


# ── CriticAgent ───────────────────────────────────────────────────────────────

class CriticAgent:
    """
    다른 에이전트 점수 검토 및 위험 감점
    - Vision: fail 예측이면 강한 감점
    - 수급: 매도 우위면 감점
    - 종합: 스코어 불일치 시 신뢰도 하락
    """

    def __init__(self):
        logger.info("[CriticAgent] 초기화")

    def critique(self, scores: List[AgentScore],
                 df_3m: pd.DataFrame = None) -> float:
        """패널티 반환 (양수 = 감점)"""
        penalty = 0.0

        vision_score = next((s.score for s in scores if s.agent_name == "vision_agent"), None)
        supply_score = next((s.score for s in scores if s.agent_name == "supply_agent"), None)

        if vision_score is not None:
            if vision_score < 30:
                penalty += 25   # fail 예측 강한 감점
            elif vision_score < 45:
                penalty += 10

        if supply_score is not None and supply_score < 40:
            penalty += 10

        # 에이전트 간 의견 불일치 감점
        valid_scores = [s.score for s in scores if s.agent_name != "critic_agent"]
        if len(valid_scores) >= 2:
            std = float(np.std(valid_scores))
            if std > 25:
                penalty += 5  # 의견 분산

        # df_3m 기반 위험 신호
        if df_3m is not None and len(df_3m) >= 5:
            closes = df_3m["close"].values[-5:]
            # 연속 하락 중이면 감점
            if all(closes[i] < closes[i-1] for i in range(1, len(closes))):
                penalty += 8

        return min(penalty, 40.0)  # 최대 40점 감점


# ── CouncilAgent ──────────────────────────────────────────────────────────────

class CouncilAgent:
    """
    모든 에이전트 점수 종합 → 최종 매수 후보 결정
    가중 평균 후 Critic 감점 적용
    """

    WEIGHTS = {
        "vision_agent": 0.40,
        "supply_agent": 0.30,
        "news_agent":   0.30,
    }
    BUY_THRESHOLD = 65.0

    def __init__(self, weights: dict = None):
        if weights:
            self.WEIGHTS = weights
        self._critic = CriticAgent()
        logger.info("[CouncilAgent] 초기화")

    def make_decision(self, scores: List[AgentScore],
                      symbol: str, name: str,
                      df_3m: pd.DataFrame = None) -> Candidate:
        """가중 평균 → Critic 감점 → 최종 결정"""
        weighted_sum  = 0.0
        weight_total  = 0.0

        for s in scores:
            w = self.WEIGHTS.get(s.agent_name, 0.0)
            weighted_sum  += s.score * w
            weight_total  += w

        base_score = weighted_sum / weight_total if weight_total > 0 else 50.0

        penalty    = self._critic.critique(scores, df_3m)
        avg_score  = max(0.0, base_score - penalty)

        recommendation = "BUY" if avg_score >= self.BUY_THRESHOLD else "HOLD"

        logger.debug(
            f"[CouncilAgent] {symbol} {name}: base={base_score:.1f} "
            f"penalty={penalty:.1f} final={avg_score:.1f} → {recommendation}"
        )

        return Candidate(
            symbol=symbol, name=name,
            scores=scores,
            avg_score=round(avg_score, 1),
            recommendation=recommendation,
            metadata={"base_score": base_score, "penalty": penalty},
        )


# ── EvolutionCoach ────────────────────────────────────────────────────────────

class EvolutionCoach:
    """매매 결과 복기 및 개선 제안 (로그 기반)"""

    def __init__(self):
        logger.info("[EvolutionCoach] 초기화")

    def review(self, symbol: str = "", pnl: float = 0.0,
               reason: str = "", **kwargs) -> str:
        """매매 완료 후 간단 복기"""
        verdict = "성공" if pnl >= 0 else "실패"
        return f"[복기] {symbol} {verdict} pnl={pnl:+.0f}원 사유={reason}"
