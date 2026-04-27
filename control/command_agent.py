"""
Command Agent (Skeleton)
텔레그램 명령 수신 및 처리

주의:
- 주문 직접 실행 금지
- Risk Guard 우회 금지
- 반드시 order_manager 경로 사용

TODO: 실제 Telegram API 연동
"""

import logging
from typing import Optional

from shared.schemas import CommandRequest, CommandResult
from control.command_auth import CommandAuth
from control.command_router import CommandRouter
from control.command_audit import CommandAudit

logger = logging.getLogger(__name__)


class CommandAgent:
    """
    명령 에이전트 (Skeleton)

    흐름:
    Telegram 메시지 → command_auth → command_router → 실행 → 회신

    TODO: 실제 Telegram Bot API 연동
    """

    def __init__(self):
        self.auth = CommandAuth()
        self.router = CommandRouter()
        self.audit = CommandAudit()
        logger.info("[CommandAgent] 초기화")

    def handle_message(self, user_id: str, text: str) -> str:
        """
        메시지 처리 (테스트 가능한 인터페이스)

        Args:
            user_id: Telegram user_id
            text: 메시지 텍스트

        Returns:
            응답 메시지
        """
        logger.info(f"[CommandAgent] 메시지: user={user_id} text={text}")

        # 권한 확인
        if not self.auth.is_authorized(user_id):
            self.audit.log(user_id, text, "UNAUTHORIZED")
            return "권한이 없습니다."

        # 명령 파싱
        request = self._parse_request(user_id, text)
        if request is None:
            return "명령을 인식할 수 없습니다."

        # 명령 실행
        result = self.router.route_command(request)

        # 감사 로그
        self.audit.log(user_id, text, "SUCCESS" if result.success else "FAIL")

        return result.message

    def _parse_request(self, user_id: str, text: str) -> Optional[CommandRequest]:
        """명령 파싱"""
        parts = text.strip().split()
        if not parts:
            return None
        return CommandRequest(
            user_id=user_id,
            command=parts[0].lower(),
            args=parts[1:],
        )

    def run(self) -> None:
        """Telegram 봇 실행 (TODO)"""
        logger.info("[CommandAgent] Telegram 봇 시작 (TODO)")
        # TODO: python-telegram-bot Application 생성 및 실행


_command_agent: Optional[CommandAgent] = None


def get_command_agent() -> CommandAgent:
    global _command_agent
    if _command_agent is None:
        _command_agent = CommandAgent()
    return _command_agent
