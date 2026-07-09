"""
A股ETF双动量轮动策略 - 动量计算模块
计算绝对动量、相对动量、估值分位
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

from .config import Config


@dataclass
class MomentumResult:
    """动量计算结果"""
    code: str
    name: str
    return_252d: float  # 252日累计收益率
    rank: int  # 相对动量排名
    pe_percentile: Optional[float] = None  # PE分位数
    pb_percentile: Optional[float] = None  # PB分位数
    valuation_triggered: bool = False  # 估值刹车是否触发


class MomentumCalculator:
    """动量计算器"""

    # ETF代码到跟踪指数代码的映射
    ETF_TO_INDEX = {
        "510300": "000300",  # 沪深300ETF → 沪深300
        "512400": "399395",  # 有色金属ETF → 中证申万有色金属
        "510650": "000951",  # 银行ETF → 中证银行
        "516860": "399808",  # 高端制造ETF → 中证高端制造
        "159928": "000932",  # 消费ETF → 中证消费
        "512010": "000933",  # 医药ETF → 中证医药
        "515000": "931087",  # 科技ETF → 中证科技
        "511880": None,      # 货币ETF无估值
    }

    def __init__(self, config: Config):
        self.config = config

    def calculate_absolute_momentum(self, data: Dict[str, pd.DataFrame]) -> Tuple[bool, float]:
        """
        计算绝对动量（金丝雀检查）

        Returns:
            (is_bullish, return_252d)
            is_bullish: 沪深300ETF 252日收益率 > 0
            return_252d: 252日累计收益率
        """
        benchmark_code = self.config.benchmark.code
        if benchmark_code not in data:
            return False, 0.0

        df = data[benchmark_code]
        if len(df) < self.config.momentum_window:
            return False, 0.0

        # 计算252日收益率
        close_now = df["close"].iloc[-1]
        close_252ago = df["close"].iloc[-self.config.momentum_window]
        return_252d = (close_now / close_252ago) - 1

        is_bullish = return_252d > self.config.abs_momentum_threshold
        return is_bullish, return_252d

    def calculate_relative_momentum(self, data: Dict[str, pd.DataFrame]) -> List[MomentumResult]:
        """
        计算相对动量（行业赛马）

        Returns:
            按252日收益率降序排列的动量结果列表
        """
        results = []
        for etf in self.config.industry_etfs:
            code = etf.code
            if code not in data:
                continue

            df = data[code]
            if len(df) < self.config.relative_momentum_window:
                continue

            # 计算相对动量收益率
            close_now = df["close"].iloc[-1]
            close_ago = df["close"].iloc[-self.config.relative_momentum_window]
            return_252d = (close_now / close_ago) - 1

            result = MomentumResult(
                code=code,
                name=etf.name,
                return_252d=return_252d,
                rank=0  # 后续排序赋值
            )
            results.append(result)

        # 按收益率降序排序
        results.sort(key=lambda x: x.return_252d, reverse=True)

        # 赋予排名
        for i, result in enumerate(results):
            result.rank = i + 1

        return results

    def fetch_market_pe_data(self) -> Optional[Dict[str, float]]:
        """通过AKShare获取沪深300历史PE并计算当前分位数（带缓存）。"""
        # 缓存：避免每次调仓都重新请求AKShare
        if hasattr(self, '_market_pe_cache'):
            return self._market_pe_cache
        try:
            import akshare as ak
            df = ak.stock_index_pe_lg(symbol='沪深300')
            if df is None or df.empty:
                return None
            pe_series = df['滚动市盈率'].dropna()
            if len(pe_series) < 252:
                return None
            current_pe = float(pe_series.iloc[-1])
            lookback = self.config.valuation_lookback_years * 252
            hist = pe_series.iloc[-min(len(pe_series), lookback):]
            percentile = (hist < current_pe).mean() * 100
            self._market_pe_cache = {'pe_current': round(current_pe, 2), 'pe_percentile': round(percentile, 1), 'n_days': len(hist)}
            return self._market_pe_cache
        except Exception as e:
            print(f"  估值刹车(AKShare): {e}")
            return None

    def fetch_all_valuation_data(self, etf_codes=None) -> Dict[str, float]:
        """市场级估值刹车：沪深300 PE分位替代逐ETF估值。"""
        market_pe = self.fetch_market_pe_data()
        if market_pe is None:
            return {}
        pe_pct = market_pe['pe_percentile']
        pe_val = market_pe['pe_current']
        print(f"  沪深300 PE={pe_val} 分位={pe_pct:.1f}% (刹车阈值={self.config.valuation_pe_threshold}%)")
        return {'_market': pe_pct}

    def apply_valuation_brake(self, momentum_results, pe_data=None):
        """市场级估值刹车：沪深300 PE分位>阈值 → 跳过涨幅>30%的热门ETF。"""
        if momentum_results is None:
            return []
        if pe_data is None:
            pe_data = self.fetch_all_valuation_data()
        market_pct = pe_data.get('_market')
        if market_pct is None:
            return momentum_results
        if market_pct > self.config.valuation_pe_threshold:
            print(f"  ⚠ 估值刹车触发: 沪深300 PE分位={market_pct:.1f}% > {self.config.valuation_pe_threshold}%")
            for r in momentum_results:
                if r.return_252d > self.config.valuation_return_threshold:
                    r.valuation_triggered = True
        else:
            for r in momentum_results:
                r.valuation_triggered = False
    def select_targets(self, momentum_results, benchmark_return=None):
        """Top-N选股：动量排名中选取未触发估值刹车的ETF。"""
        if momentum_results is None:
            return []
        selected = []
        for result in momentum_results:
            if result.valuation_triggered:
                continue
            selected.append(result.code)
            if len(selected) >= self.config.top_n:
                break
        return selected

    def generate_momentum_report(self, momentum_results: List[MomentumResult],
                                is_bullish: bool, benchmark_return: float) -> str:
        """生成动量排名报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("双动量轮动策略 - 动量排名报告")
        lines.append("=" * 80)

        # 绝对动量状态
        status = "多头市场 ✓" if is_bullish else "空头市场 ✗"
        lines.append(f"\n【绝对动量】沪深300ETF {self.config.momentum_window}日收益率: {benchmark_return:.2%} → {status}")

        # 相对动量排名
        lines.append(f"\n【相对动量】行业ETF排名（Top {self.config.top_n}）:")
        lines.append("-" * 80)
        lines.append(f"{'排名':<6}{'代码':<10}{'名称':<12}{'收益':<12}{'PE分位':<10}{'PB分位':<10}{'刹车':<8}{'入选':<8}")
        lines.append("-" * 80)

        targets = self.select_targets(momentum_results, benchmark_return)
        for r in momentum_results:
            pe_str = f"{r.pe_percentile:.1f}%" if r.pe_percentile is not None else "N/A"
            pb_str = f"{r.pb_percentile:.1f}%" if r.pb_percentile is not None else "N/A"
            brake = "✓ 触发" if r.valuation_triggered else "✗"
            selected = "✓" if r.code in targets else ""
            lines.append(f"{r.rank:<6}{r.code:<10}{r.name:<12}"
                        f"{r.return_252d:<12.2%}{pe_str:<10}{pb_str:<10}{brake:<8}{selected:<8}")

        if targets:
            names = [self.config.get_etf_by_code(c).name for c in targets]
            weight = f"{1/len(targets):.0%}"
            lines.append(f"\n【选股结果】: {len(targets)} 只ETF等权持有（各{weight}）")
            for c, n in zip(targets, names):
                lines.append(f"  - {n} ({c})")
        else:
            lines.append(f"\n【选股结果】: 无合适标的，建议持有货币ETF ({self.config.defensive.code})")

        return "\n".join(lines)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    计算 ATR (Average True Range)

    Args:
        df: 含 high, low, close 列的 DataFrame
        period: ATR 周期（默认14）

    Returns:
        ATR 序列，NaN 填充到与输入等长
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]

    tr = np.maximum(
        high - low,
        np.maximum(
            np.abs(high - prev_close),
            np.abs(low - prev_close)
        )
    )
    # Wilder's smoothing
    atr = np.full(len(df), np.nan)
    atr[period] = np.mean(tr[1:period+1])  # 初始值用简单平均
    for i in range(period + 1, len(df)):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

    return pd.Series(atr, index=df.index)
