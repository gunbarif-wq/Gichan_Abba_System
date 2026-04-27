"""
Retry Policy
재시도 정책 관리
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryAction(Enum):
    RETRY = "RETRY"
    ABORT = "ABORT"
    ESCALATE = "ESCALATE"


@dataclass
class RetryResult:
    success: bool
    attempts: int
    result: Optional[object] = None
    last_error: Optional[str] = None


class RetryPolicy:
    """
    재시도 정책

    - 토큰 만료: 재발급 후 1회 재시도
    - 네트워크 오류: 최대 3회, 5초 간격
    - 잔고 부족: 재시도 금지
    - 주문 거부: 재시도 금지
    """

    MAX_NETWORK_RETRIES = 3
    RETRY_DELAY = 5  # seconds

    def execute_with_retry(
        self,
        func: Callable[[], T],
        context: str = "",
        no_retry_exceptions: tuple = (),
    ) -> RetryResult:
        """
        재시도 로직으로 함수 실행

        Args:
            func: 실행할 함수
            context: 컨텍스트 설명
            no_retry_exceptions: 재시도하지 않을 예외 타입들
        """
        from shared.errors import (
            InsufficientCash, RiskException, TokenExpired, NetworkError
        )

        last_error = None
        for attempt in range(1, self.MAX_NETWORK_RETRIES + 1):
            try:
                result = func()
                logger.debug(f"[RetryPolicy] 성공: {context} (시도 {attempt})")
                return RetryResult(success=True, attempts=attempt, result=result)

            except TokenExpired as e:
                logger.warning(f"[RetryPolicy] 토큰 만료: {context}")
                # TODO: 토큰 재발급 로직
                last_error = str(e)
                if attempt >= 2:
                    break

            except NetworkError as e:
                logger.warning(f"[RetryPolicy] 네트워크 오류 (시도 {attempt}/{self.MAX_NETWORK_RETRIES}): {e}")
                last_error = str(e)
                if attempt < self.MAX_NETWORK_RETRIES:
                    time.sleep(self.RETRY_DELAY)

            except no_retry_exceptions as e:
                logger.warning(f"[RetryPolicy] 재시도 불가: {type(e).__name__}: {e}")
                return RetryResult(success=False, attempts=attempt, last_error=str(e))

            except Exception as e:
                logger.error(f"[RetryPolicy] 예외: {type(e).__name__}: {e}")
                last_error = str(e)
                break

        logger.error(f"[RetryPolicy] 최종 실패: {context} -> {last_error}")
        return RetryResult(
            success=False,
            attempts=self.MAX_NETWORK_RETRIES,
            last_error=last_error,
        )


_retry_policy: Optional[RetryPolicy] = None


def get_retry_policy() -> RetryPolicy:
    global _retry_policy
    if _retry_policy is None:
        _retry_policy = RetryPolicy()
    return _retry_policy
