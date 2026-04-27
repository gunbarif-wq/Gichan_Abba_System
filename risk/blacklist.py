"""
Blacklist
거래 금지 종목 목록 관리
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)

BLACKLIST_FILE = Path("storage/blacklist.json")


class Blacklist:
    """거래 금지 종목 목록"""

    def __init__(self, blacklist_file: str = str(BLACKLIST_FILE)):
        self._file = Path(blacklist_file)
        self._symbols: Set[str] = set()
        self._reasons: dict = {}
        self._load()
        logger.info(f"[Blacklist] 초기화: {len(self._symbols)}개 종목")

    def _load(self) -> None:
        if self._file.exists():
            try:
                with open(str(self._file), encoding="utf-8") as f:
                    data = json.load(f)
                self._symbols = set(data.get("symbols", []))
                self._reasons = data.get("reasons", {})
            except Exception as e:
                logger.error(f"[Blacklist] 로드 실패: {e}")

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(str(self._file), "w", encoding="utf-8") as f:
                json.dump({"symbols": list(self._symbols), "reasons": self._reasons}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Blacklist] 저장 실패: {e}")

    def add(self, symbol: str, reason: str = "") -> None:
        self._symbols.add(symbol)
        self._reasons[symbol] = {"reason": reason, "added_at": datetime.now().isoformat()}
        self._save()
        logger.warning(f"[Blacklist] 추가: {symbol} ({reason})")

    def remove(self, symbol: str) -> None:
        self._symbols.discard(symbol)
        self._reasons.pop(symbol, None)
        self._save()
        logger.info(f"[Blacklist] 제거: {symbol}")

    def is_blacklisted(self, symbol: str) -> bool:
        return symbol in self._symbols

    def get_reason(self, symbol: str) -> Optional[str]:
        info = self._reasons.get(symbol)
        return info["reason"] if info else None

    def get_all(self) -> Set[str]:
        return set(self._symbols)


_blacklist: Optional[Blacklist] = None


def get_blacklist() -> Blacklist:
    global _blacklist
    if _blacklist is None:
        _blacklist = Blacklist()
    return _blacklist
