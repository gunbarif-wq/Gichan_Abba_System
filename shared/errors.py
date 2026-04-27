"""
커스텀 예외 클래스
"""


class GichanAbbaException(Exception):
    """기본 예외"""
    pass


# ==================== 주문 관련 예외 ====================

class OrderException(GichanAbbaException):
    """주문 관련 예외"""
    pass


class OrderStateException(OrderException):
    """주문 상태 관련 예외"""
    pass


class DuplicateOrderException(OrderException):
    """중복 주문 예외"""
    pass


class OrderTimeoutException(OrderException):
    """주문 타임아웃"""
    pass


class OrderNotFound(OrderException):
    """주문을 찾을 수 없음"""
    pass


class InvalidOrderState(OrderStateException):
    """유효하지 않은 주문 상태"""
    pass


# ==================== 리스크 관련 예외 ====================

class RiskException(GichanAbbaException):
    """리스크 검사 실패"""
    pass


class InsufficientCash(RiskException):
    """잔고 부족"""
    pass


class PositionRatioExceeded(RiskException):
    """종목당 비중 초과"""
    pass


class CashRatioExceeded(RiskException):
    """최소 현금 비율 초과"""
    pass


class MaxPositionsExceeded(RiskException):
    """최대 보유 종목 수 초과"""
    pass


class UnknownOrderState(RiskException):
    """UNKNOWN 상태의 주문 존재"""
    pass


class EmergencyStop(RiskException):
    """긴급 중단"""
    pass


class LiveTradingDisabled(RiskException):
    """실계좌 거래 비활성화"""
    pass


# ==================== 거래 관련 예외 ====================

class TradeException(GichanAbbaException):
    """거래 관련 예외"""
    pass


class ExecutionException(TradeException):
    """주문 실행 실패"""
    pass


class PartialFillException(TradeException):
    """부분 체결"""
    pass


class FillCheckException(TradeException):
    """체결 확인 실패"""
    pass


# ==================== 계좌 관련 예외 ====================

class AccountException(GichanAbbaException):
    """계좌 관련 예외"""
    pass


class PositionNotFound(AccountException):
    """포지션을 찾을 수 없음"""
    pass


class ZeroHoldings(AccountException):
    """보유 수량이 0"""
    pass


# ==================== 시장 관련 예외 ====================

class MarketException(GichanAbbaException):
    """시장 관련 예외"""
    pass


class MarketClosed(MarketException):
    """거래시간이 아님"""
    pass


class BuyRestrictedTime(MarketException):
    """신규 매수 제한 시간"""
    pass


# ==================== API/브로커 관련 예외 ====================

class BrokerException(GichanAbbaException):
    """브로커 관련 예외"""
    pass


class TokenExpired(BrokerException):
    """토큰 만료"""
    pass


class TokenRefreshFailed(BrokerException):
    """토큰 재발급 실패"""
    pass


class APIError(BrokerException):
    """API 오류"""
    pass


class NetworkError(BrokerException):
    """네트워크 오류"""
    pass


class ResponseError(BrokerException):
    """응답 파싱 오류"""
    pass


# ==================== 설정 관련 예외 ====================

class ConfigException(GichanAbbaException):
    """설정 관련 예외"""
    pass


class ConfigNotFound(ConfigException):
    """설정 파일을 찾을 수 없음"""
    pass


class InvalidConfig(ConfigException):
    """유효하지 않은 설정"""
    pass


# ==================== 명령 관련 예외 ====================

class CommandException(GichanAbbaException):
    """명령 관련 예외"""
    pass


class UnauthorizedCommand(CommandException):
    """권한 없는 명령"""
    pass


class InvalidCommand(CommandException):
    """유효하지 않은 명령"""
    pass


class CommandParseError(CommandException):
    """명령 파싱 오류"""
    pass


# ==================== 데이터 관련 예외 ====================

class DataException(GichanAbbaException):
    """데이터 관련 예외"""
    pass


class DataNotFound(DataException):
    """데이터를 찾을 수 없음"""
    pass


class InvalidData(DataException):
    """유효하지 않은 데이터"""
    pass


# ==================== 학습 관련 예외 ====================

class TrainingException(GichanAbbaException):
    """학습 관련 예외"""
    pass


class ModelNotFound(TrainingException):
    """모델을 찾을 수 없음"""
    pass


class InvalidModelState(TrainingException):
    """유효하지 않은 모델 상태"""
    pass
