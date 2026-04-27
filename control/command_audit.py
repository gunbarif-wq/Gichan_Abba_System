"""
Command Audit
모든 명령 감사 로그
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CommandAudit:
    """모든 명령을 기록하는 감사 로거"""

    def __init__(self, log_dir: str = "storage/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        today = datetime.now().strftime("%Y%m%d")
        self._logfile = self.log_dir / f"command_audit_{today}.jsonl"
        logger.info(f"[CommandAudit] 초기화: {self._logfile}")

    def log(self, user_id: str, command: str, status: str, detail: str = "") -> None:
        record = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "command": command,
            "status": status,
            "detail": detail,
        }
        try:
            with self._lock:
                with open(str(self._logfile), "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[CommandAudit] 기록 실패: {e}")


_command_audit: Optional[CommandAudit] = None


def get_command_audit() -> CommandAudit:
    global _command_audit
    if _command_audit is None:
        _command_audit = CommandAudit()
    return _command_audit
