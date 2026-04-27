"""
프로젝트 전역 상수
"""

# ==================== 모드 ====================
DEFAULT_MODE = "paper"
ALLOWED_MODES = ["paper", "mock", "live"]

# ==================== 거래 관련 ====================
DEFAULT_COMMISSION_RATE = 0.00015  # 0.015%
DEFAULT_TAX_RATE = 0.0018  # 0.18%
DEFAULT_INITIAL_CASH = 10_000_000  # 1천만원
DEFAULT_MIN_CASH_RATIO = 0.20  # 최소 현금 비율 20%
DEFAULT_MAX_POSITION_RATIO = 0.20  # 종목당 최대 비중 20%
DEFAULT_MAX_POSITIONS = 5  # 최대 보유 종목 5개
DEFAULT_MAX_DAILY_LOSS_RATIO = 0.03  # 최대 일일 손실률 3%

# ==================== 주문 ====================
ORDER_TIMEOUT_SECONDS = 300  # 5분
MAX_RETRY_COUNT = 3
RETRY_DELAY_SECONDS = 5

# ==================== 시장 시간 (HHmm 형식) ====================
# KIS 모의투자 / KRX 정규장
KIS_MARKET_OPEN = "0900"
KIS_MARKET_CLOSE = "1530"

# NXT 포함 시
NXT_PREMARKET_START = "0800"
NXT_PREMARKET_END = "0850"
NXT_MAIN_START = "0930"  # 09:30
NXT_MAIN_END = "1520"    # 15:20
NXT_AFTERMARKET_START = "1540"  # 15:40
NXT_AFTERMARKET_END = "2000"

# 신규 주문 제한 구간
BAN_BUY_START = "0850"
BAN_BUY_END = "0930"
BAN_BUY_AFTERNOON_START = "1520"
BAN_BUY_AFTERNOON_END = "1540"

# ==================== 에이전트 ====================
AGENT_NAMES = [
    "vision_agent",
    "supply_agent",
    "news_agent",
    "critic_agent",
    "council",
    "evolution_coach",
    "ops_agent",
    "command_agent"
]

# ==================== 로그 ====================
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "INFO"
LOG_FILE = "storage/logs/gichan_abba.log"

# ==================== 데이터베이스 ====================
TRADE_HISTORY_DB = "storage/trade_history.db"

# ==================== 파일 경로 ====================
CONFIG_DIR = "config"
STORAGE_DIR = "storage"
MODELS_DIR = "models"
DATASETS_DIR = "datasets"

# ==================== 시스템 ====================
SYSTEM_CHECK_INTERVAL = 60  # 1분
TOKEN_CHECK_INTERVAL = 3600  # 1시간
MARKET_CLOCK_UPDATE_INTERVAL = 30  # 30초

# ==================== 거래 신호 ====================
MIN_CONFIDENCE = 0.5
MIN_VOLUME = 1000  # 최소 거래량
MIN_PRICE = 1000  # 최소 주가

# ==================== Vision 학습 ====================
MIN_CANDLES_FOR_IMAGE = 60  # 최소 3분봉 60개
CHART_IMAGE_SIZE = (256, 256)
CHART_IMAGE_FORMAT = "RGB"

# ==================== 에러 메시지 ====================
ERROR_UNKNOWN_ORDER_STATE = "UNKNOWN 상태의 주문이 존재하여 신규 주문 불가"
ERROR_DUPLICATE_BUY = "이미 보유 중이거나 미체결 매수 주문이 존재합니다"
ERROR_DUPLICATE_SELL = "미체결 매도 주문이 이미 존재합니다"
ERROR_INSUFFICIENT_CASH = "주문가능금액이 부족합니다"
ERROR_ZERO_HOLDINGS = "보유 수량이 0입니다"
ERROR_POSITION_RATIO_EXCEEDED = "종목당 최대 비중을 초과합니다"
ERROR_CASH_RATIO_EXCEEDED = "최소 현금 비율을 초과합니다"
ERROR_MAX_POSITIONS_EXCEEDED = "최대 보유 종목 수를 초과합니다"
ERROR_LIVE_TRADING_DISABLED = "실계좌 거래가 비활성화 되어있습니다"
ERROR_MARKET_CLOSED = "거래 시간이 아닙니다"

# ==================== 성공 메시지 ====================
SUCCESS_ORDER_CREATED = "주문이 생성되었습니다"
SUCCESS_ORDER_FILLED = "주문이 체결되었습니다"
SUCCESS_ORDER_CANCELLED = "주문이 취소되었습니다"

# ==================== 텔레그램 명령어 ====================
TELEGRAM_COMMANDS = {
    "/help": "도움말",
    "/status": "시스템 상태",
    "/account": "계좌 조회",
    "/positions": "포지션 조회",
    "/orders": "주문 현황",
    "/pause_buy": "매수 일시 중단",
    "/resume_buy": "매수 재개",
    "/pause_all": "전체 거래 일시 중단",
    "/resume_all": "전체 거래 재개",
    "/restart": "시스템 재시작",
    "/buy": "매수 주문",
    "/sell": "매도 주문",
    "/sell_all": "전량 매도",
    "/cancel": "주문 취소",
    "/emergency": "긴급 중단",
}
