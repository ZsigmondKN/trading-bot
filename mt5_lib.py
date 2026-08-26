"""
Author: Zsigmond Kovacs-Nagy
Description: ...
"""

from datetime import datetime
from decimal import Decimal
import logging

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from config import LOGIN_TIMEOUT, MAXIMUM_MT5_CANDLE_COUNT_PER_REQUEST


def login(configs: dict[str, str]) -> None:
    account_username = configs["username"]
    account_server = configs["server"]
    account_password = configs["password"]

    login_success = mt5.initialize(
        login=int(account_username),
        password=account_password,
        server=account_server,
        timeout=LOGIN_TIMEOUT
    )

    if not login_success:
        raise RuntimeError(
            "Failed to initialize MT5 with the provided login credentials."
        )
    logging.info("Connection established to MT5.")


def validate_and_initialise_symbols(symbol_configs: dict[str, str]) -> None:
    available_symbols = {symbol.name for symbol in mt5.symbols_get()}

    for symbol in symbol_configs["symbols"]:
        if symbol not in available_symbols:
            raise ValueError(
                f"Symbol '{symbol}' not found in this MT5 version. Update symbol name."
            )
        # Enable the symbol in MT5 Market Watch
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Failed to initialise symbol: {symbol}")

    logging.info("All requested symbols successfully initialised.\n")


def validate_timeframe(timeframe: str) -> int:
    try:
        return getattr(mt5, f"TIMEFRAME_{timeframe}")
    except AttributeError:
        raise ValueError(f"Unsupported timeframe: {timeframe}")


def validate_candles(symbol: str, candles: np.ndarray | None) -> np.ndarray:
    if candles is None:
        raise RuntimeError(
            f"Failed to retrieve data for {symbol}. Error provided: {mt5.last_error()}"
        )

    return candles

def conver_datetime(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe["time"] = pd.to_datetime(dataframe["time"], unit="s", utc=True)
    dataframe.rename(columns={"time": "datetime"}, inplace=True)

    return dataframe


def split_date_time(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe.insert(1, "date", dataframe["datetime"].dt.date)
    dataframe.insert(2, "time", dataframe["datetime"].dt.time)
    dataframe.drop(columns=["datetime"], inplace=True)
    
    return dataframe


def collect_current_candlesticks(
    symbol: str,
    timeframe: str,
    number_of_candles: int
) -> pd.DataFrame:
    if number_of_candles > MAXIMUM_MT5_CANDLE_COUNT_PER_REQUEST:
        raise ValueError(
            f"Cannot retrieve more than {MAXIMUM_MT5_CANDLE_COUNT_PER_REQUEST} "
            "candlesticks at once."
        )

    mt5_timeframe = validate_timeframe(timeframe)

    # Skip the current candle
    initial_candle_index = 1
    
    candles = mt5.copy_rates_from_pos(
        symbol,
        mt5_timeframe,
        initial_candle_index,
        number_of_candles # TODO add conversion so datetime can be used to calculate candle count
    )
    candles = validate_candles(symbol, candles)

    if len(candles) == 0:
        raise RuntimeError(
            f"No live data was returned for {symbol}, "
            f"using {number_of_candles} candles."
        )

    candles_df = pd.DataFrame(candles)
    candles_df = conver_datetime(candles_df)
    
    return candles_df


def collect_historical_candlesticks(
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime
) -> pd.DataFrame:
    mt5_timeframe = validate_timeframe(timeframe)

    if start_date >= end_date:
        raise ValueError("The start date must be earlier than the end date.")

    candles = mt5.copy_rates_range(
        symbol,
        mt5_timeframe,
        start_date,
        end_date
    )
    candles = validate_candles(symbol, candles)

    if len(candles) == 0:
        raise RuntimeError(
            f"No historical data was returned for {symbol}, "
            f"between {start_date} and {end_date}."
        )

    candles_df = pd.DataFrame(candles)
    candles_df = conver_datetime(candles_df)
    
    return candles_df


def collect_candlesticks(
    symbol: str,
    symbol_configs: dict
) -> pd.DataFrame:
    if symbol_configs["historical_timeframe"]:
        historical_start_time = symbol_configs["historical_start_time"]
        historical_end_time = symbol_configs["historical_end_time"]
        candles_df = collect_historical_candlesticks(
            symbol=symbol,
            timeframe=symbol_configs["timeframe"],
            start_date=historical_start_time,
            end_date=historical_end_time,
        )
    else:
        timeframe = symbol_configs["timeframe"]
        number_of_candles = symbol_configs["number_of_candles"]
        candles_df = collect_current_candlesticks(
            symbol=symbol,
            timeframe=timeframe,
            number_of_candles=number_of_candles,
        )

    return candles_df


def get_account_balance() -> float:
    account_info = mt5.account_info()
    if account_info is None:
        raise RuntimeError(f"Unable to retrieve account information: {mt5.last_error()}")

    return account_info.balance


def get_symbol_info(symbol: str) -> mt5.SymbolInfo:
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        raise ValueError(f"Unknown symbol: {symbol}")
    
    return symbol_info


def validate_order_direction(order_type: str) -> int:
    if order_type == "buy_stop":
        return mt5.ORDER_TYPE_BUY
    elif order_type == "sell_stop":
        return mt5.ORDER_TYPE_SELL
    else:
        raise ValueError(f"Unsupported order type: '{order_type}'.")


def validate_order_type(order_type: str) -> int:
    if order_type == "buy_stop":
        return mt5.ORDER_TYPE_BUY_STOP
    elif order_type == "sell_stop":
        return mt5.ORDER_TYPE_SELL_STOP
    else:
        raise ValueError(f"Unsupported order type: '{order_type}'.")


def get_currency_profit(symbol_info: mt5.SymbolInfo) -> str:
    currency_profit = symbol_info.currency_profit

    if not currency_profit:
        raise RuntimeError(
            f"MT5 did not provide a profit currency for '{symbol_info.name}'."
        )

    return currency_profit


def get_currency_base(symbol_info: mt5.SymbolInfo) -> str:
    currency_base = symbol_info.currency_base

    if not currency_base:
        raise RuntimeError(
            f"MT5 did not provide a base currency for '{symbol_info.name}'."
        )

    return currency_base


def get_digits(symbol_info: mt5.SymbolInfo) -> int:
    digits = symbol_info.digits

    if digits < 0:
            raise RuntimeError(
                f"Invalid price precision of {digits} "
                f"for {symbol_info.name}"
            )

    return digits


def get_trade_tick_size(symbol_info: mt5.SymbolInfo) -> Decimal:
    tick_size = symbol_info.trade_tick_size

    if tick_size <= 0:
        raise ValueError(
            f"Invalid trade tick size of {tick_size} "
            f"for '{symbol_info.name}'."
        )

    return Decimal(str(tick_size))


def get_trade_contract_size(symbol_info: mt5.SymbolInfo) -> Decimal:
    contract_size = symbol_info.trade_contract_size

    if contract_size <= 0:
        raise ValueError(
            f"Invalid trade contract size of {contract_size} "
            f"for '{symbol_info.name}'."
        )

    return Decimal(str(contract_size))


def get_volume_step(symbol_info: mt5.SymbolInfo) -> Decimal:
    volume_step = symbol_info.volume_step

    if volume_step <= 0:
        raise ValueError(
            f"Invalid volume step of {volume_step} "
            f"for '{symbol_info.name}"
        )

    return Decimal(str(volume_step))


def get_volume_min(symbol_info: mt5.SymbolInfo) -> Decimal:
    volume_min = symbol_info.volume_min

    if volume_min <= 0:
        raise ValueError(
            f"Invalid minimum volume of {volume_min} "
            f"for {symbol_info.name}"
        )

    return Decimal(str(volume_min))

def get_volume_max(symbol_info: mt5.SymbolInfo) -> Decimal:
    volume_max = symbol_info.volume_max

    if volume_max <= 0:
        raise ValueError(
            f"Invalid maximum volume of {volume_max} "
            f"for {symbol_info.name}"
        )

    return Decimal(str(volume_max))


def validate_volume(
    symbol_info: mt5.SymbolInfo,
    volume_min: Decimal,
    volume_max: Decimal,
    volume_step: Decimal
) -> None:
    if volume_max < volume_min:
        raise RuntimeError(
            f"Invalid volume limits for '{symbol_info.name}': "
            f"minimum={volume_min}, maximum={volume_max}"
        )

    if volume_step > volume_max:
        raise RuntimeError(
            f"Invalid volume step for '{symbol_info.name}': "
            f"step={volume_step}, maximum={volume_max}"
        )