#!/usr/bin/env python3
"""ATR止损模式对比：次日开盘 vs 盘中实时 vs 收盘退出"""
import sys, os, json
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.config import Config
from scripts.data_collector import ETFDataCollector
from scripts.strategy import DualMomentumStrategy
from scripts.backtest import BacktestEngine
from scripts.momentum import calculate_atr


def run_comparison():
    """三种止损模式对比回测"""
    config = Config()
    collector = ETFDataCollector(config)
    data = collector.collect_all()

    strategies = {
        "A_收盘退出(当前)": "close",
        "B_盘中退出(stop价)": "intraday_stop",
        "C_盘中退出(low价)": "intraday_low",
    }

    results = {}
    for name, mode in strategies.items():
        engine = ATRStopBacktest(config, DualMomentumStrategy(config), data, mode)
        result = engine.run()
        results[name] = {
            "annual": round(result.annual_return * 100, 2),
            "sharpe": round(result.sharpe_ratio, 2),
            "mdd": round(result.max_drawdown * 100, 2),
            "stops": len(engine.daily_records),
            "trades": result.total_trades,
        }

    print("\n" + "=" * 70)
    print("ATR 止损模式对比（2022.03 ~ 2026.07）")
    print("=" * 70)
    print(f"{'模式':<25}{'年化%':>10}{'Sharpe':>10}{'回撤%':>10}{'止损次数':>10}")
    print("-" * 70)
    for name in ["A_收盘退出(当前)", "B_盘中退出(stop价)", "C_盘中退出(low价)"]:
        r = results[name]
        print(f"{name:<25}{r['annual']:>10.1f}{r['sharpe']:>10.2f}{r['mdd']:>10.1f}{r['stops']:>10}")

    return results


class ATRStopBacktest:
    """支持多种止损模式的回测引擎（复用原有引擎+重写止损逻辑）"""

    def __init__(self, config, strategy, data, stop_mode="close"):
        self.config = config
        self.strategy = strategy
        self.data = data
        self.stop_mode = stop_mode  # "close" | "intraday_stop" | "intraday_low"
        self.daily_records = []

    def run(self):
        # 预计算ATR
        atr_data = {}
        for code, df in self.data.items():
            if code not in (self.config.defensive.code,):
                s = calculate_atr(df, self.config.trailing_stop_atr_period)
                if s is not None:
                    atr_data[code] = s

        all_dates = sorted(set().union(*[df["date"] for df in self.data.values()]))
        all_dates = [d for d in all_dates if pd.notna(d)]

        nav = self.config.initial_capital
        benchmark_nav = self.config.initial_capital

        holding_weights = {self.config.defensive.code: 1.0}
        current_holdings = [self.config.defensive.code]
        stop_state = {}
        last_rebalance_date = None
        rebalance_count = 0
        stop_count = 0

        benchmark_code = self.config.benchmark.code
        defensive_code = self.config.defensive.code

        for i, date in enumerate(all_dates):
            if i == 0:
                continue

            prev_date = all_dates[i - 1]
            benchmark_return = self._ret(benchmark_code, date, prev_date)
            benchmark_nav *= (1 + benchmark_return)

            # 调仓检查
            is_rebalance = self.strategy.should_rebalance(date, last_rebalance_date)
            if is_rebalance:
                data_slice = self._slice(date)
                signal = self.strategy.generate_signal(data_slice, date)
                current_holdings = list(signal.selected_etfs)
                n = len(current_holdings)
                mom_results = getattr(self.strategy, '_last_momentum_results', None)
                weight_dict = self.strategy.momentum_calc.get_position_weights(mom_results or [], current_holdings) if mom_results else {}
                holding_weights = weight_dict if weight_dict else {c: 1.0 / n for c in current_holdings}
                last_rebalance_date = date
                rebalance_count += 1
                stop_state.clear()

                for code in current_holdings:
                    if code == defensive_code:
                        continue
                    df = self.data.get(code)
                    atr_s = atr_data.get(code)
                    if df is not None and atr_s is not None:
                        entry_price = self._price(df, date, "close")
                        entry_atr = self._atr(df, atr_s, date)
                        if entry_price and entry_atr:
                            stop_state[code] = {"entry_price": entry_price, "entry_atr": entry_atr, "highest": entry_price}

            # 每日止损检查
            if self.config.trailing_stop_enabled:
                to_remove = []
                for code in list(current_holdings):
                    if code == defensive_code:
                        continue
                    df = self.data.get(code)
                    state = stop_state.get(code)
                    if df is None or state is None:
                        continue

                    today_close = self._price(df, date, "close")
                    today_low = self._price(df, date, "low")
                    if today_close is None:
                        continue

                    # 更新最高价
                    today_high = self._price(df, date, "high")
                    if today_high and today_high > state["highest"]:
                        state["highest"] = today_high

                    stop_price = state["highest"] - self.config.trailing_stop_atr_multiplier * state["entry_atr"]

                    triggered = False
                    exit_price = None
                    label = ""

                    if today_low is not None and today_low <= stop_price:
                        triggered = True
                        if self.stop_mode == "intraday_stop":
                            exit_price = stop_price  # 保守: 触及止损价即退
                            label = f"盘中(stop价)退出"
                        elif self.stop_mode == "intraday_low":
                            exit_price = today_low  # 悲观: 以当日最低价退出
                            label = f"盘中(low价)退出"
                        elif self.stop_mode == "close":
                            if today_close <= stop_price:
                                exit_price = today_close  # 收盘退出(当前)
                                label = f"收盘退出"

                    if self.stop_mode == "close" and today_close <= stop_price:
                        triggered = True
                        exit_price = today_close

                    if triggered and exit_price is not None:
                        to_remove.append(code)
                        stop_count += 1
                        # 退出收益
                        dd_pct = (exit_price / state["entry_price"] - 1) * 100
                        # 加权仓位: 该ETF在组合中的日收益 = (exit/entry-1) * weight
                        ret = (exit_price / state["entry_price"] - 1)

                for code in to_remove:
                    if code in holding_weights:
                        # 将止损ETF的表现反映到组合（用close回原值，新值在权重归一化前）
                        del holding_weights[code]
                    current_holdings = [h for h in current_holdings if h != code]
                    if code in stop_state:
                        del stop_state[code]

                # 全部止损 → 货币
                if not current_holdings or all(h == defensive_code for h in current_holdings):
                    current_holdings = [defensive_code]
                    holding_weights = {defensive_code: 1.0}
                    stop_state.clear()

                if current_holdings and sum(holding_weights.values()) > 0:
                    total_w = sum(holding_weights.values())
                    holding_weights = {k: v / total_w for k, v in holding_weights.items()}

            # 组合日收益率
            portfolio_return = 0.0
            for code in list(holding_weights.keys()):
                hr = self._ret(code, date, prev_date)
                w = holding_weights.get(code, 0.0)
                portfolio_return += hr * w
            if is_rebalance:
                portfolio_return -= (self.config.commission_rate * 2 + self.config.slippage_rate * 2)

            nav *= (1 + portfolio_return)
            self.daily_records.append({"date": date, "nav": nav})

        # 模拟BacktestResult
        class Result:
            pass
        r = Result()
        navs = [rec["nav"] for rec in self.daily_records]
        r.total_trades = rebalance_count
        # 简化Sharpe和MDD计算
        if len(navs) > 1:
            returns = np.diff(navs) / navs[:-1]
            r.annual_return = (navs[-1] / navs[0]) ** (252 / len(navs)) - 1
            r.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
            peak = np.maximum.accumulate(navs)
            dd = (navs - peak) / peak
            r.max_drawdown = abs(min(dd))
        else:
            r.annual_return = 0
            r.sharpe_ratio = 0
            r.max_drawdown = 0
        r.total_trades = rebalance_count
        return r

    def _ret(self, code, date, prev_date):
        df = self.data.get(code)
        if df is None: return 0.0
        c = self._price(df, date, "close")
        p = self._price(df, prev_date, "close")
        return (c / p - 1) if (c and p and p > 0) else 0.0

    def _price(self, df, date, field):
        row = df[df["date"] == date]
        if row.empty: return None
        return float(row[field].iloc[0])

    def _atr(self, df, atr_s, date):
        mask = atr_s.index.isin(df[df["date"] <= date].index)
        valid = atr_s[mask].dropna()
        return float(valid.iloc[-1]) if not valid.empty else None

    def _slice(self, date):
        return {c: df[df["date"] <= date].copy() for c, df in self.data.items()}


if __name__ == "__main__":
    run_comparison()
