"""
Command Agent — Telegram 봇 폴링 루프
/status /positions /buy /sell /stop /resume /help
주의: 주문 직접 실행 금지 — run.py의 SharedState 큐를 통해서만
"""
import logging
import os
import time
from typing import Optional

import requests

from shared.schemas import CommandRequest, CommandResult
from control.command_auth import CommandAuth
from control.command_router import CommandRouter
from control.command_audit import CommandAudit

logger = logging.getLogger(__name__)

TELEGRAM_API  = "https://api.telegram.org/bot{token}"
POLL_INTERVAL = 2    # 초
POLL_TIMEOUT  = 30   # long polling 타임아웃


class CommandAgent:
    """
    Telegram Bot API 폴링 루프
    - getUpdates long polling
    - CommandAuth → CommandRouter → Telegram sendMessage
    """

    def __init__(self):
        self.token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID",   "")
        self.auth    = CommandAuth()
        self.router  = CommandRouter()
        self.audit   = CommandAudit()
        self._ok     = bool(self.token)
        self._offset = 0
        logger.info(f"[CommandAgent] 초기화 (bot={'OK' if self._ok else 'NO TOKEN'})")

    # ── 기본 API 호출 ─────────────────────────────────────────────────────────

    def _api(self, method: str, **params) -> Optional[dict]:
        url = f"{TELEGRAM_API.format(token=self.token)}/{method}"
        try:
            resp = requests.post(url, json=params, timeout=POLL_TIMEOUT + 5)
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            logger.warning(f"[CommandAgent] API 오류: {data.get('description')}")
        except requests.RequestException as e:
            logger.warning(f"[CommandAgent] 연결 오류: {e}")
        return None

    def send_message(self, chat_id: str, text: str) -> bool:
        result = self._api("sendMessage",
                           chat_id=chat_id, text=text, parse_mode="HTML")
        return result is not None

    # ── 메시지 처리 ───────────────────────────────────────────────────────────

    def handle_message(self, user_id: str, text: str) -> str:
        logger.info(f"[CommandAgent] user={user_id} text={text}")

        if not self.auth.is_authorized(user_id):
            self.audit.log(user_id, text, "UNAUTHORIZED")
            return "권한이 없습니다."

        request = self._parse_request(user_id, text)
        if request is None:
            return "명령을 인식할 수 없습니다. /help 로 목록 확인"

        result = self.router.route_command(request)
        self.audit.log(user_id, text, "SUCCESS" if result.success else "FAIL",
                       result.error or "")
        return result.message

    def _parse_request(self, user_id: str, text: str) -> Optional[CommandRequest]:
        parts = text.strip().split()
        if not parts:
            return None
        cmd = parts[0].lower()
        if not cmd.startswith("/"):
            return None
        return CommandRequest(
            user_id=user_id,
            command=cmd,
            args=parts[1:],
        )

    # ── 폴링 루프 ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Telegram long polling 루프 (무한 실행)"""
        if not self._ok:
            logger.error("[CommandAgent] TELEGRAM_BOT_TOKEN 없음 — 봇 비활성")
            return

        logger.info("[CommandAgent] Telegram 봇 폴링 시작")

        while True:
            try:
                updates = self._api(
                    "getUpdates",
                    offset=self._offset,
                    timeout=POLL_TIMEOUT,
                    allowed_updates=["message"],
                )
                if not updates:
                    continue

                for upd in updates:
                    self._offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    if not msg:
                        continue

                    text    = msg.get("text", "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    user_id = str(msg.get("from", {}).get("id", ""))

                    if not text or not text.startswith("/"):
                        continue

                    response = self.handle_message(user_id, text)
                    if response:
                        self.send_message(chat_id, response)

            except Exception as e:
                logger.error(f"[CommandAgent] 폴링 오류: {e}")
                time.sleep(POLL_INTERVAL)


_command_agent: Optional[CommandAgent] = None


def get_command_agent() -> CommandAgent:
    global _command_agent
    if _command_agent is None:
        _command_agent = CommandAgent()
    return _command_agent
