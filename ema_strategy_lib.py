"""
Author: Zsigmond Kovacs-Nagy
Description: Compute and use Exponential Moving Averages (EMAs).
"""

from config import LOGGING_INDENT
import ema_lib
import mt5_lib
import order_lib

# TODO: Add systematic strategy parameter optimisation once backtest model is stable.
# Most likely Optuna. 
def ema_cross_strategy(
    symbol: str,
    symbol_configs: dict[str, str],
    order_configs: dict[str, str],
    strategy_configs: dict[str, str]
) -> str:
    report = ""

    candles_df = mt5_lib.collect_current_candlesticks(
        symbol,
        symbol_configs["timeframe"],
        int(symbol_configs["number_of_candles"])
    )
    ema_df = ema_lib.create_ema_df(
        symbol,
        candles_df,
        float(order_configs["risk_reward_ratio"]),
        int(strategy_configs["ema_period_one"]),
        int(strategy_configs["ema_period_two"]),
    )

    latest_signal = ema_df.iloc[-1]

    if latest_signal["ema_cross"]:
        lot_size = order_lib.calculate_lot_size(
            balance=mt5_lib.get_account_info().balance,
            risk_percentage=float(order_configs["risk_percentage_per_trade"]),
            max_margin_utilisation=float(order_configs["max_margin_utilisation"]),
            order_type=latest_signal["order_type"],
            symbol=symbol,
            entry_price=latest_signal["entry_price"],
            stop_loss=latest_signal["stop_loss"]
        )
        if lot_size is not None:
            order_outcome = order_lib.place_order(
                symbol=symbol,
                lot_size=lot_size,
                order_type=latest_signal["order_type"],
                entry_price=latest_signal["entry_price"],
                stop_loss=latest_signal["stop_loss"],
                take_profit=latest_signal["take_profit"],
                comment=f"EMA_Cross_Strategy_{symbol}",
                bypass_order_check=False
            )
            
            report += (
                "New order submitted. The order response is:\n "
                f"{order_outcome}\n"
            )
        else:
            report += "New order exceeds user defined margin requirements.\n"
    else:
        report += "The EMA values did not cross and so no order was placed.\n"
    
    report += latest_signal.to_frame().T.to_string(index=False)
    report = report.replace("\n", f"\n{LOGGING_INDENT}")

    return report