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
    return_252d: float  # 简单收益率（保留用于估值刹车判断）
    score: float = 0.0  # ★ v1.2.0: 动量得分 = 年化斜率 × R²
    slope: float = 0.0  # 线性回归年化斜率
    r_squared: float = 0.0  # R²（趋势质量，0-1）
    rank: int = 0  # 相对动量排名
    atr: Optional[float] = None  # ★ v1.2.0: 20日ATR（风险平价用）
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

    def _calc_slope_r2(self, closes: np.ndarray) -> Tuple[float, float, float]:
        """
        计算线性回归斜率、年化斜率和R²。
        
        原理（Clenow / Gray & Vogel）:
        得分 = 年化斜率 × R² — 惩罚锯齿趋势，奖励平滑趋势
        """
        n = len(closes)
        if n < 10:
            return 0.0, 0.0, 0.0
        
        x = np.arange(n, dtype=float)
        y = closes / closes[0]
        
        cov = np.cov(x, y, ddof=1)
        slope = cov[0, 1] / cov[0, 0]
        
        y_pred = slope * x + np.mean(y) - slope * np.mean(x)
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        r_squared = max(0.0, min(1.0, r_squared))
        
        annualized_slope = slope * 252
        return annualized_slope, r_squared, slope

    def calculate_relative_momentum(self, data: Dict[str, pd.DataFrame]) -> List[MomentumResult]:
        """
        计算相对动量（行业赛马）— v1.2.0: 斜率×R²排名
        """
        results = []
        for etf in self.config.industry_etfs:
            code = etf.code
            if code not in data:
                continue

            df = data[code]
            if len(df) < self.config.relative_momentum_window:
                continue

            closes = df["close"].values[-self.config.relative_momentum_window:]

            # 简单收益率（保留，用于估值刹车涨幅判断）
            return_252d = (closes[-1] / closes[0]) - 1

            # ★ v1.2.0: 斜率 × R² 动量得分
            annual_slope, r2, _ = self._calc_slope_r2(closes)
            score = annual_slope * r2

            # 20日ATR（风险平价用）
            atr_val = None
            try:
                atr_series = calculate_atr(df, 20)
                if atr_series is not None:
                    atr_val = float(atr_series.dropna().iloc[-1])
            except Exception:
                pass

            result = MomentumResult(
                code=code,
                name=etf.name,
                return_252d=return_252d,
                rank=0,
                score=score,
                slope=annual_slope,
                r_squared=r2,
                atr=atr_val,
            )
            results.append(result)

        # ★ v1.2.0: 按得分降序，同等分时按收益率降序
        results.sort(key=lambda x: (x.score, x.return_252d), reverse=True)

        for i, result in enumerate(results):
            result.rank = i + 1

        return results

    def fetch_etf_pe_data(self, etf_code: str) -> Optional[Dict[str, float]]:
        """逐ETF获取PE数据：AKShare csindex 20条近期PE，计算当前PE的相对位置（缓存）。"""
        cache_key = f'_pe_{etf_code}'
        if hasattr(self, cache_key):
            return getattr(self, cache_key)

        index_code = self.config.get_index_code(etf_code)
        if index_code is None:
            setattr(self, cache_key, None)
            return None

        try:
            import akshare as ak
            df = ak.stock_zh_index_value_csindex(symbol=index_code)
            if df is None or df.empty or len(df) < 5:
                setattr(self, cache_key, None)
                return None

            pe_col = '市盈率1' if '市盈率1' in df.columns else None
            if pe_col is None:
                setattr(self, cache_key, None)
                return None

            pe_vals = df[pe_col].dropna().astype(float)
            if len(pe_vals) < 5:
                setattr(self, cache_key, None)
                return None

            current_pe = float(pe_vals.iloc[-1])
            pe_min, pe_max = float(pe_vals.min()), float(pe_vals.max())
            # 当前PE在20条数据范围中的相对位置（0-100）
            if pe_max > pe_min:
                position = (current_pe - pe_min) / (pe_max - pe_min) * 100
            else:
                position = 50.0

            result = {
                'pe_current': round(current_pe, 2),
                'pe_position': round(position, 1),
                'pe_min': round(pe_min, 2),
                'pe_max': round(pe_max, 2),
                'n_points': len(pe_vals),
            }
            setattr(self, cache_key, result)
            return result
        except Exception:
            setattr(self, cache_key, None)
            return None

    def fetch_all_valuation_data(self, etf_codes=None) -> Dict[str, float]:
        """逐ETF估值数据：返回所有可获取PE位置的ETF（不做阈值过滤）。"""
        if etf_codes is None:
            etf_codes = [e.code for e in self.config.industry_etfs]
        pe_data = {}
        for code in etf_codes:
            info = self.fetch_etf_pe_data(code)
            if info:
                pe_data[code] = info['pe_position']
        return pe_data  # 返回全部PE数据，包括低于阈值的

    def apply_valuation_brake(self, momentum_results, pe_data=None):
        """逐ETF估值刹车：单只ETF的PE相对位置>阈值 且 涨幅>30% → 跳过该ETF。"""
        if momentum_results is None:
            return []
        if pe_data is None:
            pe_data = self.fetch_all_valuation_data()

        for r in momentum_results:
            pe_pct = pe_data.get(r.code)
            r.valuation_triggered = False
            if pe_pct is not None:
                r.pe_percentile = pe_pct
                if pe_pct > self.config.valuation_pe_threshold and r.return_252d > self.config.valuation_return_threshold:
                    r.valuation_triggered = True

        return momentum_results
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

    def get_position_weights(self, momentum_results, selected_codes=None) -> Dict[str, float]:
        """
        ★ v1.2.0: ATR风险平价权重。

        原理（Clenow / Antonacci）:
        - 分配的是风险预算，不是资金预算
        - 高波动ETF = 小仓位，低波动ETF = 大仓位
        - 权重 ∝ 1/ATR

        Returns:
            {code: weight} — 权重之和=1.0
        """
        if selected_codes is None:
            selected_codes = self.select_targets(momentum_results)

        if not selected_codes:
            return {}

        # 构建 code → MomentumResult 查找表
        code_map = {r.code: r for r in momentum_results}

        inv_atr = {}
        for code in selected_codes:
            r = code_map.get(code)
            if r and r.atr and r.atr > 0:
                inv_atr[code] = 1.0 / r.atr
            else:
                # 无ATR数据 → 等权fallback
                inv_atr[code] = 1.0

        total = sum(inv_atr.values())
        if total <= 0:
            n = len(selected_codes)
            return {c: 1.0 / n for c in selected_codes}

        return {c: v / total for c, v in inv_atr.items()}

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
        lines.append(f"\n【相对动量】行业ETF排名（Top {self.config.top_n}）— v1.2.0 斜率×R²得分:")
        lines.append("-" * 80)
        lines.append(f"{'排名':<6}{'代码':<10}{'名称':<12}{'得分':<10}{'斜率':<10}{'R²':<8}{'收益':<10}{'刹车':<8}{'入选':<8}")
        lines.append("-" * 80)

        targets = self.select_targets(momentum_results, benchmark_return)
        for r in momentum_results:
            brake = "✓ 触发" if r.valuation_triggered else "✗"
            selected = "✓" if r.code in targets else ""
            lines.append(f"{r.rank:<6}{r.code:<10}{r.name:<12}"
                        f"{r.score:<10.4f}{r.slope:<10.4f}{r.r_squared:<8.4f}"
                        f"{r.return_252d:<10.2%}{brake:<8}{selected:<8}")

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
