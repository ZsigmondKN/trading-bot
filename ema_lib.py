"""
Author: Zsigmond Kovacs-Nagy
Description: Compute and use Exponential Moving Averages (EMAs).
"""

from datetime import datetime
import logging
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from config import EMA_WARMUP_MULTIPLIER
import df_lib
import mt5_lib


def check_and_order_emas(ema_period_one: int, ema_period_two: int) -> tuple[int, int]:
    if ema_period_one == ema_period_two:
        raise ValueError("EMA periods are equivalent.")

    return min(ema_period_one, ema_period_two), max(ema_period_one, ema_period_two)


def add_ema_to_df(dataframe: pd.DataFrame, ema_period: int) -> pd.DataFrame:
    ema_column = f"ema_{ema_period}"

    # Add an EMA column to the dataframe using pandas' Exponential Moving Window (EWM)
    dataframe[ema_column] = dataframe["close"].ewm(
        span=ema_period,
        # Calculate the EMA without adjusting for previous values, 
        # This is standard for trading.
        adjust=False
    ).mean()  # Convert EWM into EMA
    
    return dataframe


def add_ema_cross_and_action_to_df(
    dataframe: pd.DataFrame,
    warmup_period: int,
    faster_ema_period: int,
    slower_ema_period: int
) -> pd.DataFrame:
    is_current_pos_bullish = (
        dataframe[f"ema_{slower_ema_period}"] < dataframe[f"ema_{faster_ema_period}"]
    )
    is_previous_pos_bullish = is_current_pos_bullish.shift(1)

    dataframe["ema_cross"] = is_current_pos_bullish != is_previous_pos_bullish
    dataframe.loc[dataframe.index[0], "ema_cross"] = False
    dataframe.loc[:warmup_period - 1, "ema_cross"] = False

    dataframe["order_type"] = "n/a"
    dataframe.loc[
        dataframe["ema_cross"] & is_current_pos_bullish, "order_type"
    ] = "buy_stop"
    dataframe.loc[
        dataframe["ema_cross"] & ~is_current_pos_bullish, "order_type"
    ] = "sell_stop"

    return dataframe


def calculate_order_parameters(
    risk_reward_ratio: float,
    order_type: str,
    candle_high: float,
    candle_low: float,
    fast_ema: float,
    slow_ema: float,
) -> tuple[float | None, float | None, float | None]:
    if order_type == "buy_stop":
        stop_loss = min(fast_ema, slow_ema)
        entry_price = candle_high

        if stop_loss >= entry_price:
            return None, None, None

        risk = entry_price - stop_loss
        take_profit = entry_price + (risk * risk_reward_ratio)

    elif order_type == "sell_stop":
        stop_loss = max(fast_ema, slow_ema)
        entry_price = candle_low

        if entry_price >= stop_loss:
            return None, None, None

        risk = stop_loss - entry_price
        take_profit = entry_price - (risk * risk_reward_ratio)

    else:
        raise ValueError(f"Unsupported EMA cross order type: '{order_type}'.")

    return entry_price, stop_loss, take_profit


def add_ema_trade_parameters_to_df(
    dataframe: pd.DataFrame,
    risk_reward_ratio: float,
    faster_ema_period: int,
    slower_ema_period: int
) -> pd.DataFrame:
    dataframe["stop_loss"] = float("nan")
    dataframe["entry_price"] = float("nan")
    dataframe["take_profit"] = float("nan")

    crosses = dataframe.index[dataframe["ema_cross"]]

    for i in crosses:
        entry_price, stop_loss, take_profit = calculate_order_parameters(
            risk_reward_ratio=risk_reward_ratio,
            order_type=df_lib.get_df_val(dataframe, i, "order_type", str),
            candle_high=df_lib.get_df_val(dataframe, i, "high", float),
            candle_low=df_lib.get_df_val(dataframe, i, "low", float),
            fast_ema=df_lib.get_df_val(dataframe, i, f"ema_{faster_ema_period}", float),
            slow_ema=df_lib.get_df_val(dataframe, i, f"ema_{slower_ema_period}", float),
        )

        if entry_price is None:
            continue

        dataframe.loc[i, "entry_price"] = entry_price
        dataframe.loc[i, "stop_loss"] = stop_loss
        dataframe.loc[i, "take_profit"] = take_profit

    return dataframe


def create_ema_df(
    symbol: str,
    candles_df: pd.DataFrame,
    risk_reward_ratio: float,
    ema_period_one: int,
    ema_period_two: int,
) -> pd.DataFrame:
    faster_ema_period, slower_ema_period = check_and_order_emas(
        ema_period_one, ema_period_two
    )
    warmup_period = int(
        max(faster_ema_period, slower_ema_period) * EMA_WARMUP_MULTIPLIER
    )

    candles_df.insert(0, "symbol", symbol)

    # Add EMA values and trade parameters
    candles_df = add_ema_to_df(candles_df, faster_ema_period)
    candles_df = add_ema_to_df(candles_df, slower_ema_period)
    candles_df = add_ema_cross_and_action_to_df(
        dataframe=candles_df,
        warmup_period=warmup_period,
        faster_ema_period=faster_ema_period,
        slower_ema_period=slower_ema_period
    )
    candles_df = add_ema_trade_parameters_to_df(
        dataframe=candles_df,
        risk_reward_ratio=risk_reward_ratio,
        faster_ema_period=faster_ema_period,
        slower_ema_period=slower_ema_period
    )

    return candles_df


def log_ema_crosses(ema_df: pd.DataFrame, verbose: bool = False) -> None:
    ema_df_cross = ema_df[ema_df["ema_cross"]]
    ema_df_cross = mt5_lib.split_date_time(ema_df_cross)
    if not verbose:
        ema_df_cross = ema_df_cross.drop(
            columns=["high", "low", "tick_volume", "spread", "real_volume"]
        )
        logging.info("EMA dataframe (concise):")
    else:
        logging.info("EMA dataframe (verbose):")

    print(ema_df_cross.round(3).to_string(index=False))


def plot_ema_charts(
    ema_df: pd.DataFrame,
    ema_period_one: int,
    ema_period_two: int,
) -> None:
    for symbol, symbol_df in ema_df.groupby("symbol"):
        # Identify gaps between candles
        gap_mask = symbol_df["datetime"].diff() > pd.Timedelta(hours=2)

        warmup_period = int(  # TODO this is being done twice make into a function
            max(ema_period_one, ema_period_two)
            * EMA_WARMUP_MULTIPLIER
        )

        logging.info(
            f"{symbol}: received {len(symbol_df)} candles "
            f"(warmup requires {warmup_period})"
        )

        fig, ax = plt.subplots(figsize=(12, 6))

        # Shade EMA warmup period
        ax.axvspan(
            symbol_df["datetime"].iloc[0],
            symbol_df["datetime"].iloc[warmup_period - 1],
            facecolor="yellow",
            alpha=0.1,
            hatch="//",
            edgecolor="grey",
            label="EMA warmup",
        )

        # Shade gaps and break plotted lines
        for gap_index in symbol_df.index[gap_mask]:
            previous_index = gap_index - 1

            ax.axvspan(
                xmin=mdates.date2num(
                    df_lib.get_df_val(symbol_df, previous_index, "datetime", datetime)
                ),
                xmax=mdates.date2num(
                    df_lib.get_df_val(symbol_df, gap_index, "datetime", datetime)
                ),
                color="grey",
                alpha=0.1,
                label="Market closed"
                if gap_index == symbol_df.index[gap_mask][0]
                else "_nolegend_",
            )

        # Break lines at gaps
        plot_columns = [
            "close",
            f"ema_{ema_period_one}",
            f"ema_{ema_period_two}",
        ]

        symbol_df.loc[gap_mask, plot_columns] = float("nan")

        # Plot price and EMAs
        ax.plot(
            symbol_df["datetime"],
            symbol_df["close"],
            label="Price",
            color="royalblue",
            linewidth=1.2,
            alpha=0.8,
        )

        ax.plot(
            symbol_df["datetime"],
            symbol_df[f"ema_{ema_period_one}"],
            label=f"EMA {ema_period_one}",
            color="darkorange",
            linewidth=1.2,
            alpha=0.8,
        )

        ax.plot(
            symbol_df["datetime"],
            symbol_df[f"ema_{ema_period_two}"],
            label=f"EMA {ema_period_two}",
            color="purple",
            linewidth=1.2,
            alpha=0.8,
        )

        # Mark EMA crosses
        cross_mask = symbol_df["ema_cross"]
        cross_buy_mask = cross_mask & (symbol_df["order_type"] == "buy_stop")
        cross_sell_mask = cross_mask & (symbol_df["order_type"] == "sell_stop")

        ax.scatter(
            symbol_df.loc[cross_buy_mask, "datetime"],
            symbol_df.loc[cross_buy_mask, "close"],
            edgecolors="#004D00",  # Extra dark green
            linewidths=1.5,
            color="green",
            s=50,
            marker="^",
            zorder=10,
            label="Buy Signal",
        )

        ax.scatter(
            symbol_df.loc[cross_sell_mask, "datetime"],
            symbol_df.loc[cross_sell_mask, "close"],
            edgecolors="darkred",
            linewidths=1.5,
            color="red",
            s=50,
            marker="v",
            zorder=10,
            label="Sell Signal",
        )

        # Configure date/time axis
        locator = mdates.AutoDateLocator()

        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

        ax.set_title(str(symbol))
        ax.set_xlabel("Date and Time")
        ax.set_ylabel("Price")

        ax.legend()
        ax.grid(True)

        fig.autofmt_xdate()

        plt.show()


def generate_ema_report(
    symbol_configs: dict[str, Any],
    order_configs: dict[str, Any],
    strategy_configs: dict[str, Any],
) -> None:
    combined_ema_df = pd.DataFrame()
    for symbol in symbol_configs["symbols"]:
        candles_df = mt5_lib.collect_candlesticks(
            symbol=symbol,
            symbol_configs=symbol_configs,
        )
        symbol_ema_df = create_ema_df(
            symbol=symbol,
            candles_df=candles_df,
            risk_reward_ratio=order_configs["risk_reward_ratio"],
            ema_period_one=strategy_configs["ema_period_one"],
            ema_period_two=strategy_configs["ema_period_two"],
        )
        combined_ema_df = pd.concat([combined_ema_df, symbol_ema_df], ignore_index=True)

    log_ema_crosses(ema_df=combined_ema_df, verbose=False)
    plot_ema_charts(
        combined_ema_df, 
        strategy_configs["ema_period_one"], 
        strategy_configs["ema_period_two"]
    )