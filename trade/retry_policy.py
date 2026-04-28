"""
Retry Policy — 재시도 정책
TokenExpired: 토큰 재발급 후 1회 재시도 (핵심)
NetworkError: 최대 3회, 5초 간격
InsufficientCash / RiskException: 재시도 금지
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryAction(Enum):
    RETRY     = "RETRY"
    ABORT     = "ABORT"
    ESCALATE  = "ESCALATE"


@dataclass
class RetryResult:
    success:    bool
    attempts:   int
    result:     Optional[object] = None
    last_error: Optional[str]   = None


class RetryPolicy:
    """
    재시도 정책

    - TokenExpired  : 토큰 재발급(kis_client.get_access_token()) 후 1회 재시도
    - NetworkError  : 최대 MAX_NETWORK_RETRIES회, RETRY_DELAY 초 간격
    - InsufficientCash / RiskException : 재시도 금지 즉시 반환
    - 그 외 Exception : 재시도 금지 즉시 반환
    """

    MAX_NETWORK_RETRIES = 3
    RETRY_DELAY         = 5   # seconds

    def __init__(self, kis_client=None):
        self._kis = kis_client

    def _get_kis(self):
        if self._kis:
            return self._kis
        try:
            from trade.kis_mock_client import get_kis_mock_client
            return get_kis_mock_client()
        except Exception:
            return None

    def _refresh_token(self) -> bool:
        """토큰 강제 재발급"""
        kis = self._get_kis()
        if kis is None:
            return False
        try:
            kis._access_token    = None
            kis._token_expire_at = None
            kis.get_access_token()
            logger.info("[RetryPolicy] 토큰 재발급 완료")
            return True
        except Exception as e:
            logger.error(f"[RetryPolicy] 토큰 재발급 실패: {e}")
            return False

    def execute_with_retry(
        self,
        func:                 Callable[[], T],
        context:              str   = "",
        no_retry_exceptions:  tuple = (),
    ) -> RetryResult:
        from shared.errors import (
            InsufficientCash, RiskException, TokenExpired, NetworkError,
        )
        try:
            import requests
            request_errors = (requests.RequestException,)
        except Exception:
            request_errors = (ConnectionError, TimeoutError)

        # no_retry 기본 포함
        _no_retry = no_retry_exceptions + (InsufficientCash, RiskException)

        token_refreshed = False
        last_error      = None

        for attempt in range(1, self.MAX_NETWORK_RETRIES + 2):  # +1 for token retry
            try:
                result = func()
                if attempt > 1:
                    logger.info(f"[RetryPolicy] 재시도 성공: {context} (시도 {attempt})")
                return RetryResult(success=True, attempts=attempt, result=result)

            except TokenExpired as e:
                logger.warning(f"[RetryPolicy] 토큰 만료: {context}")
                last_error = str(e)

                if token_refreshed:
                    # 재발급 후에도 토큰 오류면 포기
                    logger.error("[RetryPolicy] 토큰 재발급 후에도 실패 — 중단")
                    break

                ok = self._refresh_token()
                if not ok:
                    break
                token_refreshed = True
                # 재시도 (attempt 카운트 유지, loop 계속)

            except NetworkError as e:
                logger.warning(
                    f"[RetryPolicy] 네트워크 오류 "
                    f"(시도 {attempt}/{self.MAX_NETWORK_RETRIES}): {e}"
                )
                last_error = str(e)
                if attempt <= self.MAX_NETWORK_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                else:
                    break

            except request_errors as e:
                logger.warning(
                    f"[RetryPolicy] 요청 오류 "
                    f"(시도 {attempt}/{self.MAX_NETWORK_RETRIES}): {e}"
                )
                last_error = str(e)
                if attempt <= self.MAX_NETWORK_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                else:
                    break

            except _no_retry as e:
                logger.warning(f"[RetryPolicy] 재시도 불가 {type(e).__name__}: {e}")
                return RetryResult(success=False, attempts=attempt, last_error=str(e))

            except Exception as e:
                logger.error(f"[RetryPolicy] 예외 {type(e).__name__}: {e}")
                last_error = str(e)
                break

        logger.error(f"[RetryPolicy] 최종 실패: {context} → {last_error}")
        return RetryResult(
            success    = False,
            attempts   = min(attempt, self.MAX_NETWORK_RETRIES),
            last_error = last_error,
        )


_retry_policy: Optional[RetryPolicy] = None


def get_retry_policy(kis_client=None) -> RetryPolicy:
    global _retry_policy
    if _retry_policy is None:
        _retry_policy = RetryPolicy(kis_client)
    return _retry_policy
