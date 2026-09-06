"""
Author: Zsigmond Kovacs-Nagy
Description: ...
"""

import logging
from time import sleep
from typing import Callable

import MetaTrader5 as mt5

from config import EMA_CROSS_STRATEGY, LOGGING_INDENT, STRATEGY_CHECK_FREQUENCY
import ema_strategy_lib
import mt5_lib
import order_lib


def log_setup_config(
    mt5_configs: dict[str, str],
    symbol_configs: dict[str, str], 
    order_configs: dict[str, str],
) -> None:
    user_name = mt5_configs["username"]
    server = mt5_configs["server"]

    symbols = symbol_configs["symbols"]
    timeframe = symbol_configs["timeframe"]

    risk_reward_ratio = order_configs["risk_reward_ratio"]
    risk_percentage_per_trade = order_configs["risk_percentage_per_trade"]
    max_margin_utilisation = order_configs["max_margin_utilisation"]


    logging.info(
        f"Using account {user_name}, on server {server}."
    )
    logging.info(
        f"Using a time frame of {timeframe}, for the following symbols: {symbols}."
    )
    logging.info(
        f"Using a risk per trade of {risk_percentage_per_trade * 100}% and "
        f"a max margin utilisation per trade of {max_margin_utilisation * 100}%."
    )
    logging.info(
        f"Using a risk-reward ratio of 1:{risk_reward_ratio}.\n"
    )


def select_trading_strategy(strategy_configs: dict[str, str]) -> Callable[..., str]:
    if strategy_configs["strategy"] == EMA_CROSS_STRATEGY:
        ema_period_one = strategy_configs["ema_period_one"]
        ema_period_two = strategy_configs["ema_period_two"]

        logging.info(
            f"Using the EMA cross strategy with periods {ema_period_one} "
            f"and {ema_period_two}.\n{LOGGING_INDENT}"
            "Waiting for EMA cross to occur..."
        )
        return ema_strategy_lib.ema_cross_strategy

    # TODO: implement another strategy using TaLib, refer to video
    raise RuntimeError(
        f"The selected trading strategy of '{strategy_configs['strategy']}' is incompatible "
        f"with the available options.")


def run_strategy(
    symbol_configs: dict[str, str],
    order_configs: dict[str, str],
    strategy_configs: dict[str, str]
) -> None:
    trading_strategy = select_trading_strategy(strategy_configs)
    symbols = symbol_configs["symbols"]
    timeframe = symbol_configs["timeframe"]
    previous_candle_times = {
        symbol: None
        for symbol in symbols
    }

    while True:
        # If order was not placed in the span of the STRATEGY_CHECK_FREQUENCY, cancel the order
        order_lib.cancel_all_pending_orders()

        has_active_position = mt5.positions_total() > 0

        for symbol in symbols:
            current_candle = mt5_lib.collect_current_candlesticks(
                symbol=symbol,
                timeframe=timeframe,
                number_of_candles=1
            )
            current_candle_time = current_candle.iloc[0]["datetime"]

            is_new_candle = (
                current_candle_time != previous_candle_times[symbol]
            )

            # TODO This part still missalignes with the backtesting strategy.
            if is_new_candle and not has_active_position:
                previous_candle_times[symbol] = current_candle_time

                report = trading_strategy(
                    symbol=symbol,
                    symbol_configs=symbol_configs,
                    order_configs=order_configs,
                    strategy_configs=strategy_configs,
                )
                logging.debug(report)

            else:
                logging.debug(
                    f"No new candle for {symbol}. "
                    f"Current completed candle: {current_candle_time}"
                )

        # TODO for the future: I would prefer to have the interval computed so the while loop only 
        # Ran a few seconds after each new candle.
        # TODO for the future: when the market is closed, make no requests.
        sleep(STRATEGY_CHECK_FREQUENCY)

