from datetime import datetime
from typing import Any, Protocol
import numpy as np


ORDER_TYPE_BUY: int
ORDER_TYPE_SELL: int
ORDER_TYPE_BUY_STOP: int
ORDER_TYPE_SELL_STOP: int
ORDER_TIME_GTC: int
ORDER_FILLING_RETURN: int
TRADE_ACTION_PENDING: int
TRADE_ACTION_REMOVE: int
TRADE_RETCODE_DONE: int
SYMBOL_CALC_MODE_FOREX: int
SYMBOL_CALC_MODE_EXCH_STOCKS: int
SYMBOL_CALC_MODE_CFD: int
SYMBOL_CALC_MODE_CFDINDEX: int
SYMBOL_CALC_MODE_CFDLEVERAGE: int
SECTOR_CURRENCY: int
SECTOR_EQUITY: int
SECTOR_INDEX: int
SECTOR_COMMODITIES: int


class SymbolInfo:
    name: str
    trade_contract_size: float
    trade_calc_mode: int
    digits: int
    volume_step: float
    volume_min: float
    volume_max: float
    trade_tick_size: float
    currency_profit: str
    currency_base: str


class AccountInfo:
    balance: float
    currency: str


class MT5Result(Protocol):
    retcode: int
    comment: str


class OrderSendResult(MT5Result):
    pass


class OrderCheckResult(MT5Result):
    pass


class TradeOrder:
    ticket: int


def initialize(
    *,
    login: int,
    password: str,
    server: str,
    timeout: int = ...,
) -> bool: ...


def shutdown() -> None: ...


def last_error() -> tuple[int, str]: ...


def symbols_get() -> tuple[SymbolInfo, ...]: ...


def symbol_select(symbol: str, enable: bool) -> bool: ...


def symbol_info(symbol: str) -> SymbolInfo | None: ...


def account_info() -> AccountInfo | None: ...


def positions_total() -> int: ...


def copy_rates_from_pos(
    symbol: str,
    timeframe: int,
    start_pos: int,
    count: int,
) -> np.ndarray | None: ...


def copy_rates_range(
    symbol: str,
    timeframe: int,
    date_from: datetime,
    date_to: datetime,
) -> np.ndarray | None: ...


def order_calc_margin(
    action: int,
    symbol: str,
    volume: float,
    price: float,
) -> float | None: ...


def order_calc_profit(
    action: int,
    symbol: str,
    volume: float,
    price_open: float,
    price_close: float,
) -> float | None: ...


def order_check(request: dict[str, Any]) -> OrderCheckResult | None: ...


def order_send(request: dict[str, Any]) -> OrderSendResult | None: ...


def orders_get() -> tuple[TradeOrder, ...]: ...

