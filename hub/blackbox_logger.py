"""
BlackBox Logger
모든 주문, 체결, 실패, 명령, 리스크 거부 사유를 기록한다.
어떤 상황에서도 기록을 멈추지 않는다.
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_LOG_DIR = Path("storage/logs")


class BlackboxLogger:
    """
    블랙박스 로거
    - 모든 주문/체결/실패/명령/리스크거부를 JSON Lines 형식으로 기록
    - thread-safe
    """

    def __init__(self, log_dir: str = "storage/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        today = datetime.now().strftime("%Y%m%d")
        self._logfile = self.log_dir / f"blackbox_{today}.jsonl"
        logger.info(f"[BlackboxLogger] 초기화: {self._logfile}")

    def _write(self, record: Dict[str, Any]) -> None:
        """JSON Lines 형식으로 파일에 기록"""
        try:
            with self._lock:
                with open(str(self._logfile), "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error(f"[BlackboxLogger] 기록 실패: {e}")

    def log_order(self, order_id: str, symbol: str, side: str, quantity: int,
                  price: float, state: str, reason: str = "", **kwargs) -> None:
        """주문 기록"""
        self._write({
            "type": "ORDER",
            "timestamp": datetime.now().isoformat(),
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "state": state,
            "reason": reason,
            **kwargs,
        })

    def log_fill(self, order_id: str, symbol: str, side: str, quantity: int,
                 price: float, commission: float, **kwargs) -> None:
        """체결 기록"""
        self._write({
            "type": "FILL",
            "timestamp": datetime.now().isoformat(),
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "commission": commission,
            **kwargs,
        })

    def log_risk_rejection(self, order_id: str, symbol: str, side: str,
                           failed_checks: list, reason: str = "", **kwargs) -> None:
        """리스크 거부 기록"""
        self._write({
            "type": "RISK_REJECTION",
            "timestamp": datetime.now().isoformat(),
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "failed_checks": failed_checks,
            "reason": reason,
            **kwargs,
        })

    def log_error(self, context: str, error: str, symbol: str = "", **kwargs) -> None:
        """에러 기록"""
        self._write({
            "type": "ERROR",
            "timestamp": datetime.now().isoformat(),
            "context": context,
            "error": error,
            "symbol": symbol,
            **kwargs,
        })

    def log_command(self, user_id: str, command: str, result: str, **kwargs) -> None:
        """명령 기록"""
        self._write({
            "type": "COMMAND",
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "command": command,
            "result": result,
            **kwargs,
        })

    def log_signal(self, symbol: str, side: str, confidence: float, reason: str, **kwargs) -> None:
        """신호 기록"""
        self._write({
            "type": "SIGNAL",
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "side": side,
            "confidence": confidence,
            "reason": reason,
            **kwargs,
        })

    def log_system(self, event: str, message: str, **kwargs) -> None:
        """시스템 이벤트 기록"""
        self._write({
            "type": "SYSTEM",
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "message": message,
            **kwargs,
        })


# 싱글톤
_blackbox: Optional[BlackboxLogger] = None


def get_blackbox() -> BlackboxLogger:
    global _blackbox
    if _blackbox is None:
        _blackbox = BlackboxLogger()
    return _blackbox


def init_blackbox(log_dir: str = "storage/logs") -> BlackboxLogger:
    global _blackbox
    _blackbox = BlackboxLogger(log_dir)
    return _blackbox
