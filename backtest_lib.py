"""
Author: Zsigmond Kovacs-Nagy
Description: ...
"""

from datetime import datetime
from decimal import Decimal
import logging
import os
import warnings
import webbrowser

import MetaTrader5 as mt5
from nautilus_trader.analysis import create_tearsheet
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model import Money, Currency
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.enums import (
    AccountType, AssetClass, OmsType, OrderSide, OrderType
)
from nautilus_trader.model.events import PositionClosed
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import Instrument, Cfd, CurrencyPair
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy
import pandas as pd

from config import LOGGING_INDENT, MOCK_ACCOUNT_BALANCE, MT5_TIMEFRAME_TO_NAUTILUS_BAR
import ema_lib
import mt5_lib
import order_lib

# TODO add descriptive comments where needed and review the rest
class BacktestStatistics:
    def __init__(self):
        self.signals_generated = 0
        self.margin_rejections = 0
        self.orders_submitted = 0
        self.positions_closed_by_opposite_signal = 0
        self.backtest_wind_down_closures = 0
        self.positions_closed = 0

    def reset(self) -> None:
        self.signals_generated = 0
        self.margin_rejections = 0
        self.orders_submitted = 0
        self.positions_closed_by_opposite_signal = 0
        self.backtest_wind_down_closures = 0
        self.positions_closed = 0

    def report(self, symbol: str) -> None:
        logging.info(
            (
                f"For symbol {symbol}, trade signals: {self.signals_generated}, "
                f"margin rejections: {self.margin_rejections}, "
                f"orders submitted: {self.orders_submitted},\n"
                f"{LOGGING_INDENT}positions closed by opposite signal: "
                f"{self.positions_closed_by_opposite_signal}, "
                f"backtest wind down closures: "
                f"{self.backtest_wind_down_closures}, "
                f"positions closed: {self.positions_closed}.\n"
            )
        )


class EMACrossConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    symbol: str
    risk_percentage: float
    max_margin_utilisation: float
    contract_size: Decimal
    ema_df: pd.DataFrame
    statistics: BacktestStatistics


class EMACross(Strategy):
    def __init__(self, config: EMACrossConfig):
        super().__init__(config)

        self.ema_df = config.ema_df
        self.stats = config.statistics
        self.current_row = 0

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self.current_row >= len(self.ema_df):
            return

        signal = self.ema_df.iloc[self.current_row]
        self.current_row += 1

        if not signal["ema_cross"]:
            return

        self.stats.signals_generated += 1

        if signal["order_type"] == "buy_stop":
            if self.portfolio.is_net_short(self.config.instrument_id):
                positions = self.cache.positions_open(
                    instrument_id=self.config.instrument_id,
                )
                self.stats.positions_closed_by_opposite_signal += len(positions)

                self.close_all_positions(self.config.instrument_id)

            if self.portfolio.is_flat(self.config.instrument_id):
                self.buy(
                    entry_price=signal["entry_price"],
                    stop_loss=signal["stop_loss"],
                    take_profit=signal["take_profit"],
                )

        elif signal["order_type"] == "sell_stop":
            if self.portfolio.is_net_long(self.config.instrument_id):
                positions = self.cache.positions_open(
                    instrument_id=self.config.instrument_id,
                )
                self.stats.positions_closed_by_opposite_signal += len(positions)

                self.close_all_positions(self.config.instrument_id)

            if self.portfolio.is_flat(self.config.instrument_id):
                self.sell(
                    entry_price=signal["entry_price"],
                    stop_loss=signal["stop_loss"],
                    take_profit=signal["take_profit"],
                )

    def _calculate_quantity(
        self,
        instrument: Instrument,
        order_type: str,
        entry_price: float,
        stop_loss: float,
    ) -> Quantity | None:
        account = self.portfolio.account(self.config.instrument_id.venue)
        balance = account.balance_total().as_double()

        lot_size = order_lib.calculate_lot_size(
            balance=balance,
            risk_percentage=self.config.risk_percentage,
            max_margin_utilisation=self.config.max_margin_utilisation,
            order_type=order_type,
            symbol=str(instrument.raw_symbol),
            entry_price=entry_price,
            stop_loss=stop_loss,
        )
        if lot_size is None:
            self.stats.margin_rejections += 1
            return None

        return instrument.make_qty(
            Decimal(str(lot_size)) * self.config.contract_size
        )

    def buy(self, entry_price: float, stop_loss: float, take_profit: float) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        quantity = self._calculate_quantity(
            instrument=instrument,
            order_type="buy_stop",
            entry_price=entry_price,
            stop_loss=stop_loss
        )

        if quantity is None:
            return

        entry_price = instrument.make_price(entry_price)
        stop_loss = instrument.make_price(stop_loss)
        take_profit = instrument.make_price(take_profit)
        
        orders = self.order_factory.bracket(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=quantity,
            entry_order_type=OrderType.MARKET,
            sl_trigger_price=stop_loss,
            tp_price=take_profit,
        )

        self.submit_order_list(orders)
        self.stats.orders_submitted += 1

    def sell(self, entry_price: float, stop_loss: float, take_profit: float) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        quantity = self._calculate_quantity(
            instrument=instrument,
            order_type="sell_stop",
            entry_price=entry_price,
            stop_loss=stop_loss
        )

        if quantity is None:
            return

        entry_price = instrument.make_price(entry_price)
        stop_loss = instrument.make_price(stop_loss)
        take_profit = instrument.make_price(take_profit)

        orders = self.order_factory.bracket(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=quantity,
            entry_order_type=OrderType.MARKET, # TODO not exactly like my code
            sl_trigger_price=stop_loss,
            tp_price=take_profit,
        )

        self.submit_order_list(orders)
        self.stats.orders_submitted += 1

    def on_position_closed(self, event: PositionClosed) -> None:
        self.stats.positions_closed += 1

    def on_stop(self) -> None:
        positions = self.cache.positions_open(
            instrument_id=self.config.instrument_id,
        )
        self.stats.backtest_wind_down_closures += len(positions)

        self.close_all_positions(self.config.instrument_id)


def get_decimal_precision(value: Decimal) -> int: # TODO add stuff like this to a helper file
    if not value.is_finite():
        raise ValueError(f"Expected a finite Decimal, got {value}.")

    exponent = value.as_tuple().exponent

    if not isinstance(exponent, int):
        raise ValueError(
            f"Expected an integer Decimal exponent, got {exponent}."
        )

    return max(0, -exponent)

def create_instrument_from_mt5(
        symbol_info: mt5.SymbolInfo,
        instrument_class: type[Instrument],
        order_commission: float,
        asset_class: AssetClass | None = None,
        base_currency: str | None = None,
        quote_currency: str | None = None
    ) -> Instrument:
    currency_profit = (
        quote_currency
        if quote_currency is not None
        else mt5_lib.get_currency_profit(symbol_info)
    )
    currency_base = (
        base_currency
        if base_currency is not None
        else mt5_lib.get_currency_base(symbol_info)
    )
    digits = mt5_lib.get_digits(symbol_info)
    tick_size = mt5_lib.get_trade_tick_size(symbol_info)
    contract_size = mt5_lib.get_trade_contract_size(symbol_info)
    volume_step = mt5_lib.get_volume_step(symbol_info)
    volume_min = mt5_lib.get_volume_min(symbol_info)
    volume_max = mt5_lib.get_volume_max(symbol_info)

    mt5_lib.validate_volume(
        symbol_info=symbol_info,
        volume_step=volume_step,
        volume_min=volume_min,
        volume_max=volume_max
    )

    # Convert MT5 lot-based volume constraints to Nautilus instrument units.
    size_increment = volume_step * contract_size
    min_quantity = volume_min * contract_size
    max_quantity = volume_max * contract_size
    size_precision = get_decimal_precision(size_increment)

    if get_decimal_precision(tick_size) > digits:
        raise RuntimeError(
            f"Tick size {tick_size} for '{symbol_info.name}' requires more "
            f"decimal places than MT5 digits={digits}."
        )

    common_kwargs = dict(
        instrument_id=InstrumentId.from_str(f"{symbol_info.name}.SIM"),
        raw_symbol=Symbol(symbol_info.name),
        quote_currency=Currency.from_str(currency_profit),
        price_precision=digits,
        size_precision=size_precision,
        price_increment=Price.from_str(str(tick_size)),
        size_increment=Quantity.from_str(str(size_increment)),
        ts_event=0,
        ts_init=0,
        base_currency=Currency.from_str(currency_base),
        lot_size=Quantity.from_str(str(contract_size)),
        max_quantity=Quantity.from_str(str(max_quantity)),
        min_quantity=Quantity.from_str(str(min_quantity)),
        maker_fee=Decimal(str(order_commission)),
        taker_fee=Decimal(str(order_commission))
    )

    if instrument_class is CurrencyPair:
        return CurrencyPair(**common_kwargs)

    return instrument_class(**common_kwargs, asset_class=asset_class)


def create_fx(
        symbol_info: mt5.SymbolInfo,
        order_commission: float,
        base_currency: str | None = None,
        quote_currency: str | None = None,
    ) -> CurrencyPair:
    return create_instrument_from_mt5(
        symbol_info=symbol_info,
        instrument_class=CurrencyPair,
        order_commission=order_commission,
        base_currency=base_currency,
        quote_currency=quote_currency
    )


def create_cfd(
        symbol_info: mt5.SymbolInfo,
        order_commission: float,
    ) -> Cfd:
    return create_instrument_from_mt5(
        symbol_info=symbol_info,
        instrument_class=Cfd,
        # The asset class is arbitrary assigned as there is no reliable way to 
        # automatically retrieve it. Additionally it has no effect on backtesting results.
        asset_class=AssetClass.COMMODITY,
        order_commission=order_commission
    )


def create_instrument(symbol_info: mt5.SymbolInfo, order_configs: dict) -> Instrument:
    if symbol_info is None:
        raise RuntimeError("MT5 symbol was not found.")

    if symbol_info.trade_calc_mode == mt5.SYMBOL_CALC_MODE_FOREX:
        return create_fx(
            symbol_info=symbol_info,
            # TODO since the fee for this is in usd/lot the a seperate function will be required
            # to calculate it and then turn it into the account currency if different.
            order_commission=order_configs["cfd_commission_percent"] # Temp value
        )

    if symbol_info.trade_calc_mode in (
        mt5.SYMBOL_CALC_MODE_CFD,
        mt5.SYMBOL_CALC_MODE_CFDINDEX,
        mt5.SYMBOL_CALC_MODE_CFDLEVERAGE,
    ):
        return create_cfd(
            symbol_info=symbol_info,
            order_commission=order_configs["cfd_commission_percent"]
        )

    raise NotImplementedError(
        f"Unsupported MT5 trade calculation mode "
        f"{symbol_info.trade_calc_mode} for '{symbol_info.name}'."
    )


def get_backtest_bars(
    bar_type: BarType,
    instrument: Instrument,
    ema_df: pd.DataFrame
) -> list[Bar]:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                "A value is being set on a copy of a "
                "DataFrame or Series through chained assignment."
            ),
        )

        return BarDataWrangler(bar_type, instrument).process(
            ema_df[["open", "high", "low", "close"]]
        )
    

def get_conversion_symbol(
    instrument: Instrument,
    account_currency: str,
) -> str | None:
    quote_currency = str(instrument.quote_currency)

    if quote_currency == account_currency:
        return None

    # Use the available MT5 conversion pair. Nautilus handles any required inversion.
    direct_symbol = f"{quote_currency}{account_currency}"
    inverse_symbol = f"{account_currency}{quote_currency}"

    if mt5.symbol_info(direct_symbol) is not None:
        return direct_symbol

    if mt5.symbol_info(inverse_symbol) is not None:
        return inverse_symbol

    raise RuntimeError(
        f"No FX conversion pair found for "
        f"{quote_currency}/{account_currency}. "
        f"Tried '{direct_symbol}' and '{inverse_symbol}'."
    )


def load_exchange_rate_data(
    symbol: str,
    symbol_configs: dict
) -> tuple[Instrument, list[QuoteTick]]:
    symbol_info = mt5_lib.get_symbol_info(symbol)

    instrument = create_fx(
        symbol_info=symbol_info,
        order_commission=0.00004, # TODO find and add reallistic value TODO fee changes have no affect
    )

    candles_df = mt5_lib.collect_candlesticks(
        symbol=symbol,
        symbol_configs=symbol_configs,
    )

    quote_ticks = []
    for _, candle in candles_df.iterrows():
        timestamp = pd.Timestamp(candle["datetime"]).value
        price = instrument.make_price(float(candle["close"]))

        quote_size = Quantity.from_str(
            f"{1:.{instrument.size_precision}f}"
        )

        quote_ticks.append(
            QuoteTick(
                instrument_id=instrument.id,
                bid_price=price,
                ask_price=price,
                bid_size=quote_size,
                ask_size=quote_size,
                ts_event=timestamp,
                ts_init=timestamp,
            )
        )

    return instrument, quote_ticks


def run_symbol_backtest(
    backtest_engine: BacktestEngine,
    symbol: str,
    symbol_configs: dict,
    order_configs: dict,
    strategy_configs: dict,
    statistics: BacktestStatistics,
) -> None:
    symbol_info = mt5_lib.get_symbol_info(symbol)

    instrument = create_instrument(
        symbol_info=symbol_info, 
        order_configs=order_configs
    )
    contract_size = mt5_lib.get_trade_contract_size(symbol_info)

    candles_df = mt5_lib.collect_candlesticks(
        symbol=symbol,
        symbol_configs=symbol_configs,
    )
    ema_df = ema_lib.create_ema_df(
        symbol=symbol,
        candles_df=candles_df,
        risk_reward_ratio=order_configs["risk_reward_ratio"],
        ema_period_one=strategy_configs["ema_period_one"],
        ema_period_two=strategy_configs["ema_period_two"],
    ).set_index("datetime")

    bar_time = MT5_TIMEFRAME_TO_NAUTILUS_BAR[symbol_configs["timeframe"]]
    bar_type = BarType.from_str(f"{symbol}.SIM-{bar_time}-LAST-EXTERNAL")
    bars = get_backtest_bars(bar_type, instrument, ema_df)

    strategy = EMACross(
        EMACrossConfig(
            instrument_id=instrument.id,
            symbol=symbol,
            risk_percentage=order_configs["risk_percentage_per_trade"],
            max_margin_utilisation=order_configs["max_margin_utilisation"],
            contract_size=contract_size,
            ema_df=ema_df,
            bar_type=bar_type,
            statistics=statistics
        ),
    )

    backtest_engine.add_instrument(instrument)
    backtest_engine.add_data(bars)

    account_currency = order_configs["base_currency"]
    exchange_rate_symbol  = get_conversion_symbol(
        instrument=instrument,
        account_currency=account_currency,
    )
    
    if exchange_rate_symbol  is not None:
        (
            exchange_rate_instrument,
            exchange_rate_quotes,
        ) = load_exchange_rate_data(
            symbol=exchange_rate_symbol,
            symbol_configs=symbol_configs,
        )

        backtest_engine.add_instrument(exchange_rate_instrument)
        backtest_engine.add_data(exchange_rate_quotes)

    backtest_engine.add_strategy(strategy)


def create_backtest_engine(
    account_balance: float,
    base_currency: str,
) -> BacktestEngine:
    currency = Currency.from_str(base_currency)
    backtest_engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR"))
    )
    backtest_engine.add_venue(
        venue=Venue("SIM"),
        oms_type=OmsType.HEDGING,
        account_type=AccountType.MARGIN,
        starting_balances=[Money(account_balance, currency)],
        base_currency=currency,
    )

    return backtest_engine


def run_backtest(
    symbol_configs: dict,
    order_configs: dict,
    strategy_configs: dict,
    use_real_account_balance: bool = True,
) -> None:
    if use_real_account_balance:
        account_balance = mt5_lib.get_account_balance()
    else:
        account_balance = MOCK_ACCOUNT_BALANCE

    statistics = BacktestStatistics()

    for symbol in symbol_configs["symbols"]:
        backtest_engine = create_backtest_engine(
            account_balance=account_balance,
            base_currency=order_configs["base_currency"],
        )

        logging.info(f"Running backtest on {symbol} symbol.")

        run_symbol_backtest(
            backtest_engine=backtest_engine,
            symbol=symbol,
            symbol_configs=symbol_configs,
            order_configs=order_configs,
            strategy_configs=strategy_configs,
            statistics=statistics
        )

        backtest_engine.run()
        statistics.report(symbol)
        statistics.reset()

        tearsheet_name = f".\\reports\\backtest_tearsheet_{symbol}.html"
        create_tearsheet(
            engine=backtest_engine,
            output_path=tearsheet_name
        )
        report_path = os.path.realpath(tearsheet_name)
        webbrowser.open(report_path)