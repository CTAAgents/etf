"""
A股ETF双动量轮动策略 - 策略核心逻辑模块
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from .config import Config
from .momentum import MomentumCalculator, MomentumResult


@dataclass
class TradeSignal:
    """交易信号"""
    date: datetime
    action: str  # buy / sell / hold
    code: str
    name: str
    weight: float  # 仓位权重 (0-1)
    reason: str


@dataclass
class RebalanceRecord:
    """调仓记录"""
    date: datetime
    is_bullish: bool
    benchmark_return: float
    momentum_ranking: List[MomentumResult]
    selected_etfs: List[str]  # 选中的ETF代码列表
    trade_signals: List[TradeSignal]
    reason: str


class DualMomentumStrategy:
    """双动量轮动策略"""

    def __init__(self, config: Config):
        self.config = config
        self.momentum_calc = MomentumCalculator(config)
        self.rebalance_records: List[RebalanceRecord] = []
        self.current_holdings: List[str] = []  # 当前持仓列表
        self._pe_data_cache: Optional[Dict[str, float]] = None

    def should_rebalance(self, current_date: datetime, last_rebalance: Optional[datetime] = None) -> bool:
        """判断是否需要调仓"""
        if last_rebalance is None:
            return True
        
        if self.config.rebalance_freq == "wednesday":
            # 周三收盘信号，周四调仓（遇节假日顺延至下一交易日）
            # weekday: 0=Mon, 2=Wed
            if current_date.weekday() == 2:
                return True
            # 如果错过周三（假期），距上次>=10天则强制补调
            days_since_last = (current_date - last_rebalance).days
            return days_since_last >= 10

        elif self.config.rebalance_freq == "weekly":
            days_since_last = (current_date - last_rebalance).days
            return days_since_last >= 7
        
        elif self.config.rebalance_freq == "biweekly":
            days_since_last = (current_date - last_rebalance).days
            return days_since_last >= 14
        
        else:  # monthly
            next_day = current_date + pd.Timedelta(days=1)
            return current_date.month != next_day.month

    def generate_signal(self, data: Dict[str, pd.DataFrame],
                       current_date: Optional[datetime] = None,
                       pe_data: Optional[Dict[str, float]] = None) -> RebalanceRecord:
        """
        生成调仓信号

        Args:
            data: ETF数据字典
            current_date: 当前日期（默认取数据最新日期）
            pe_data: PE分位数据，若为None且启用估值刹车则自动获取

        Returns:
            调仓记录
        """
        if current_date is None:
            # 取所有数据的最新日期
            dates = [df["date"].max() for df in data.values() if not df.empty]
            current_date = max(dates)

        # Step 1: 绝对动量检查
        is_bullish, benchmark_return = self.momentum_calc.calculate_absolute_momentum(data)

        if not is_bullish:
            # 空头市场，全仓货币ETF
            record = RebalanceRecord(
                date=current_date,
                is_bullish=False,
                benchmark_return=benchmark_return,
                momentum_ranking=[],
                selected_etfs=[self.config.defensive.code],
                trade_signals=[TradeSignal(
                    date=current_date,
                    action="buy",
                    code=self.config.defensive.code,
                    name=self.config.defensive.name,
                    weight=1.0,
                    reason=f"绝对动量不满足（沪深300收益率={benchmark_return:.2%}≤0），切换至防御"
                )],
                reason=f"空头市场，沪深300ETF {self.config.momentum_window}日收益率={benchmark_return:.2%}"
            )
            self.rebalance_records.append(record)
            self.current_holdings = [self.config.defensive.code]
            return record

        # Step 2: 相对动量计算
        momentum_results = self.momentum_calc.calculate_relative_momentum(data)
        self._last_momentum_results = momentum_results  # ★ v1.2.0: 暴露给回测做风险平价

        # Step 3: 估值分位刹车（若启用）
        if self.config.valuation_enabled:
            if pe_data is None and self._pe_data_cache is None:
                self._pe_data_cache = self.momentum_calc.fetch_all_valuation_data()
            effective_pe_data = pe_data or self._pe_data_cache
            momentum_results = self.momentum_calc.apply_valuation_brake(momentum_results, effective_pe_data)

        # Step 4: Top-N选股（跑赢基准过滤 + 等权分配）
        selected_codes = self.momentum_calc.select_targets(momentum_results, benchmark_return)

        if not selected_codes:
            # 无标的入选（全部刹车或未跑赢基准），持有货币ETF
            record = RebalanceRecord(
                date=current_date,
                is_bullish=True,
                benchmark_return=benchmark_return,
                momentum_ranking=momentum_results,
                selected_etfs=[self.config.defensive.code],
                trade_signals=[TradeSignal(
                    date=current_date,
                    action="buy",
                    code=self.config.defensive.code,
                    name=self.config.defensive.name,
                    weight=1.0,
                    reason="无ETF满足条件（估值刹车/未跑赢基准），切换至货币ETF"
                )],
                reason="无满足条件的行业ETF，防御性持有货币ETF"
            )
        else:
            # 等权分配仓位
            # ★ v1.2.0: ATR风险平价权重
            weights = self.momentum_calc.get_position_weights(momentum_results, selected_codes)
            signals = []
            for code in selected_codes:
                etf_cfg = self.config.get_etf_by_code(code)
                w = weights.get(code, 1.0/len(selected_codes))
                signals.append(TradeSignal(
                    date=current_date,
                    action="buy",
                    code=code,
                    name=etf_cfg.name,
                    weight=w,
                    reason=f"动量排名Top-{len(selected_codes)}，跑赢基准，风险平价{w:.0%}"
                ))
            names = [self.config.get_etf_by_code(c).name for c in selected_codes]
            record = RebalanceRecord(
                date=current_date,
                is_bullish=True,
                benchmark_return=benchmark_return,
                momentum_ranking=momentum_results,
                selected_etfs=selected_codes,
                trade_signals=signals,
                reason=f"多头市场，风险平价持有Top-{len(selected_codes)}: {', '.join(names)}"
            )

        self.rebalance_records.append(record)
        self.current_holdings = record.selected_etfs
        return record

    def get_holdings_at_date(self, date: datetime) -> List[str]:
        """获取指定日期的持仓列表"""
        for record in reversed(self.rebalance_records):
            if record.date <= date:
                return record.selected_etfs
        return []

    def get_all_trade_signals(self) -> List[TradeSignal]:
        """获取所有交易信号"""
        signals = []
        for record in self.rebalance_records:
            signals.extend(record.trade_signals)
        return signals
