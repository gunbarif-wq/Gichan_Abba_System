"""
Evolution Coach
장 마감 후 복기 + 패턴 분석 + 개선안 생성

할 수 있는 것:
- trade_history 분석
- 실패 차트 저장
- feedback 저장
- 후보 모델 생성 제안
- proposal 생성

할 수 없는 것:
- live_config 수정
- risk 코드 수정
- active 모델 자동 교체
- 실계좌 설정 변경
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class EvolutionCoach:
    """
    자가학습 코치 (Evolution Coach)
    장 마감 후 실행하여 매매 결과를 복기하고 개선안을 생성한다.
    """

    def __init__(
        self,
        feedback_dir: str = "datasets/feedback",
        proposal_dir: str = "config/proposals",
        labels_csv: str = "datasets/labels.csv",
    ):
        self.feedback_dir = Path(feedback_dir)
        self.proposal_dir = Path(proposal_dir)
        self.labels_csv = Path(labels_csv)
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[EvolutionCoach] 초기화 완료")

    # ── 1. 매매 결과 분석 ──────────────────────────────────────

    def analyze_trade_results(self, trade_results: List[dict]) -> dict:
        """
        매매 결과를 분석하여 성공/실패 패턴 추출

        Args:
            trade_results: [{"symbol", "label_at_entry", "pnl_ratio", ...}]

        Returns:
            분석 리포트
        """
        if not trade_results:
            return {"ok": False, "reason": "매매 결과 없음"}

        df = pd.DataFrame(trade_results)
        report = {
            "total_trades": len(df),
            "win_count": int((df["pnl_ratio"] > 0).sum()),
            "loss_count": int((df["pnl_ratio"] < 0).sum()),
            "avg_pnl_ratio": round(float(df["pnl_ratio"].mean()), 4),
            "pattern_analysis": {},
        }

        # 패턴별 성과
        if "label_at_entry" in df.columns:
            for label in df["label_at_entry"].unique():
                group = df[df["label_at_entry"] == label]
                report["pattern_analysis"][label] = {
                    "count": len(group),
                    "win_rate": round(float((group["pnl_ratio"] > 0).mean()), 4),
                    "avg_pnl": round(float(group["pnl_ratio"].mean()), 4),
                }

        logger.info(f"[EvolutionCoach] 분석 완료: {report['total_trades']}건")
        return report

    # ── 2. 오답 노트 (실패 케이스 저장) ──────────────────────

    def record_failure(
        self,
        symbol: str,
        entry_time: str,
        agent_scores: dict,
        pnl_ratio: float,
        reason: str = "",
    ) -> None:
        """
        실패 케이스를 feedback에 기록

        비전 에이전트 점수가 높았지만 결과가 나빴던 경우를 저장한다.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        record = {
            "recorded_at": ts,
            "symbol": symbol,
            "entry_time": entry_time,
            "agent_scores": agent_scores,
            "pnl_ratio": pnl_ratio,
            "reason": reason,
        }

        feedback_file = self.feedback_dir / f"failure_{symbol}_{ts}.json"
        with open(str(feedback_file), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        logger.info(f"[EvolutionCoach] 실패 기록: {symbol} pnl={pnl_ratio:.2%}")

    # ── 3. 패턴 분석 (성공/실패 차트 차이점 추출) ────────────

    def analyze_success_vs_fail_patterns(self) -> Optional[dict]:
        """
        labels.csv에서 Success와 Fail 패턴의 특징 차이를 분석한다.
        이 텍스트 리포트가 proposal_config의 근거가 된다.
        """
        if not self.labels_csv.exists():
            logger.warning("[EvolutionCoach] labels.csv 없음")
            return None

        try:
            df = pd.read_csv(str(self.labels_csv))
        except Exception as e:
            logger.error(f"labels.csv 읽기 실패: {e}")
            return None

        if "label" not in df.columns:
            return None

        analysis = {
            "total_windows": len(df),
            "label_distribution": {},
            "pattern_distribution": {},
            "key_findings": [],
        }

        # 라벨 분포
        for label, cnt in df["label"].value_counts().items():
            analysis["label_distribution"][label] = {
                "count": int(cnt),
                "ratio": round(cnt / len(df), 4),
            }

        # 패턴 태그별 성공률
        if "pattern_tags" in df.columns:
            all_tags = set()
            for tags_str in df["pattern_tags"].dropna():
                for t in tags_str.split(","):
                    if t.strip():
                        all_tags.add(t.strip())

            for tag in all_tags:
                mask = df["pattern_tags"].str.contains(tag, na=False)
                group = df[mask]
                if len(group) >= 3:
                    success_rate = float((group["label"] == "Success").mean())
                    fail_rate = float((group["label"] == "Fail").mean())
                    analysis["pattern_distribution"][tag] = {
                        "count": int(len(group)),
                        "success_rate": round(success_rate, 4),
                        "fail_rate": round(fail_rate, 4),
                    }

        # Key Findings 도출
        for tag, stats in analysis["pattern_distribution"].items():
            if stats["success_rate"] >= 0.50 and stats["count"] >= 5:
                analysis["key_findings"].append(
                    f"'{tag}' 패턴: 성공률 {stats['success_rate']:.1%} ({stats['count']}건) - 긍정 신호"
                )
            if stats["fail_rate"] >= 0.50 and stats["count"] >= 5:
                analysis["key_findings"].append(
                    f"'{tag}' 패턴: 실패율 {stats['fail_rate']:.1%} ({stats['count']}건) - 주의 필요"
                )

        logger.info(f"[EvolutionCoach] 패턴 분석 완료: {len(analysis['key_findings'])}개 발견")
        return analysis

    # ── 4. Proposal 생성 ──────────────────────────────────────

    def generate_proposal(
        self,
        analysis: dict,
        trade_report: dict = None,
    ) -> str:
        """
        분석 결과를 바탕으로 agent_weights 조정 제안서 생성
        proposal_config.yaml에 저장 (live_config 수정 불가)

        Returns:
            저장된 proposal 파일 경로
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        proposal = {
            "generated_at": ts,
            "generated_by": "EvolutionCoach",
            "status": "PENDING_APPROVAL",
            "analysis_summary": {},
            "proposed_changes": {},
            "notes": [
                "이 제안서는 사용자 승인 없이 live_config에 자동 반영되지 않습니다.",
                "승인 후 수동으로 config/agent_weights.yaml에 반영해주세요.",
            ],
        }

        # 분석 요약
        if analysis:
            proposal["analysis_summary"] = {
                "total_windows": analysis.get("total_windows", 0),
                "key_findings": analysis.get("key_findings", []),
            }

        # 가중치 조정 제안
        pattern_dist = analysis.get("pattern_distribution", {}) if analysis else {}
        proposed_weights = {}

        if "Breakout" in pattern_dist:
            br = pattern_dist["Breakout"]
            if br["success_rate"] >= 0.50:
                proposed_weights["vision_breakout_bonus"] = round(br["success_rate"] * 20, 1)
            elif br["fail_rate"] >= 0.50:
                proposed_weights["vision_breakout_penalty"] = round(br["fail_rate"] * 20, 1)

        if "Dip" in pattern_dist:
            dp = pattern_dist["Dip"]
            if dp["success_rate"] >= 0.45:
                proposed_weights["dip_bonus"] = round(dp["success_rate"] * 15, 1)

        if proposed_weights:
            proposal["proposed_changes"]["agent_score_adjustments"] = proposed_weights

        # 거래 성과 기반 제안
        if trade_report:
            win_rate = trade_report.get("win_count", 0) / max(trade_report.get("total_trades", 1), 1)
            if win_rate < 0.40:
                proposal["proposed_changes"]["threshold_suggestion"] = (
                    f"현재 승률 {win_rate:.1%}로 낮음 - 진입 점수 임계값 상향 검토"
                )

        # YAML 형태로 저장
        import yaml

        proposal_filename = f"proposal_{ts}.yaml"
        proposal_path = self.proposal_dir / proposal_filename
        with open(str(proposal_path), "w", encoding="utf-8") as f:
            yaml.dump(proposal, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"[EvolutionCoach] Proposal 저장: {proposal_path}")
        return str(proposal_path)

    # ── 5. 전체 복기 실행 ─────────────────────────────────────

    def run_daily_review(self, trade_results: List[dict] = None) -> str:
        """
        장 마감 후 전체 복기 실행
        1. 매매 결과 분석
        2. 패턴 분석 (labels.csv 기반)
        3. Proposal 생성
        """
        logger.info("[EvolutionCoach] 일일 복기 시작")

        trade_report = {}
        if trade_results:
            trade_report = self.analyze_trade_results(trade_results)

        pattern_analysis = self.analyze_success_vs_fail_patterns()

        if pattern_analysis or trade_report:
            proposal_path = self.generate_proposal(pattern_analysis, trade_report)
            logger.info(f"[EvolutionCoach] 복기 완료 -> {proposal_path}")
            return proposal_path
        else:
            logger.warning("[EvolutionCoach] 분석 데이터 부족")
            return ""


# 싱글톤
_evolution_coach: Optional[EvolutionCoach] = None


def get_evolution_coach() -> EvolutionCoach:
    global _evolution_coach
    if _evolution_coach is None:
        _evolution_coach = EvolutionCoach()
    return _evolution_coach
