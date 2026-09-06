"""
Author: Zsigmond Kovacs-Nagy
Description: ...
"""

from datetime import datetime, timezone
import logging
import os
from types import SimpleNamespace
from typing import Any

import MetaTrader5 as mt5

# MT5 constants
LOGIN_TIMEOUT = 10000
MAXIMUM_MT5_CANDLE_COUNT_PER_REQUEST = 50000

# Runtime constants
STRATEGY_CHECK_FREQUENCY = 10

# Order constants
LOT_SIZE_CALCULATION_VALUE = 1.0
ORDER_FULFILL_TIME = mt5.ORDER_TIME_GTC  # Remains active until canceled

# Backtesting constants
MT5_TIMEFRAME_TO_NAUTILUS_BAR = {
    "M1": "1-MINUTE",
    "M5": "5-MINUTE",
    "M15": "15-MINUTE",
    "M30": "30-MINUTE",
    "H1": "1-HOUR",
    "H4": "4-HOUR",
    "D1": "1-DAY",
}

MOCK_ACCOUNT_INFO = SimpleNamespace(
    balance=500000.0,
    currency="USD",
)

# EMA strategy constants
EMA_CROSS_STRATEGY = "ema_cross_strategy"
EMA_WARMUP_MULTIPLIER = 1.5

# Logging constants
LOGGING_INDENT = " " * 17


def parse_bool(value: str) -> bool:
    value = value.strip().lower()

    if value in ("true", "yes"):
        return True
    if value in ("false", "no"):
        return False

    raise ValueError(f"Invalid boolean configuration value: {value}")


def getenv_required(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise RuntimeError(f"Required environment variable '{name}' is missing.")
    return value


def load_mt5_configs() -> dict[str, Any]:
    return {
        "username": getenv_required("MT5_USERNAME"),
        "password": getenv_required("MT5_PASSWORD"),
        "server": getenv_required("MT5_SERVER"),
        "trading_mode": getenv_required("TRADING_MODE")
    }


def load_symbol_configs() -> dict[str, Any]:
    return {
        "symbols": getenv_required("MT5_SYMBOLS").split(","),
        "timeframe": getenv_required("MT5_TIMEFRAME"),
        "number_of_candles": int(getenv_required("NUMBER_OF_CANDLES")),
        "historical_timeframe": parse_bool(getenv_required("HISTORICAL_TIMEFRAME")),
        "historical_start_time": datetime.strptime(
            getenv_required("HISTORICAL_START_TIME"), "%Y-%m-%d"
        ).replace(tzinfo=timezone.utc),
        "historical_end_time": datetime.strptime(
            getenv_required("HISTORICAL_END_TIME"), "%Y-%m-%d"
        ).replace(tzinfo=timezone.utc)
    }


def load_order_configs() -> dict[str, Any]:
    return {
        "risk_reward_ratio": float(getenv_required("RISK_REWARD_RATIO")),
        "risk_percentage_per_trade": float(
            getenv_required("RISK_PERCENTAGE_PER_TRADE")
        ),
        "max_margin_utilisation": float(
            getenv_required("MAX_MARGIN_UTILISATION")
        ),
        "fx_commission_usd_per_lot": float(
            getenv_required("FX_COMMISSION_USD_PER_LOT")
        ),
        "cfd_commission_percent": float(
            getenv_required("CFD_COMMISSION_PERCENT")
        )
    }


def load_strategy_configs() -> dict[str, Any]:
    return {
        "strategy": os.getenv("STRATEGY"),
        "ema_period_one": int(getenv_required("EMA_PERIOD_ONE")),
        "ema_period_two": int(getenv_required("EMA_PERIOD_TWO")),
    }


def load_and_set_ui_config() -> None:
    logging.basicConfig(
        level=getenv_required("LOGGING_LEVEL"),
        format="%(asctime)s - %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )