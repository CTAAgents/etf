# -*- coding: utf-8 -*-
"""行业轮动分析模块 — 新增ETF专属。

功能：
1. 申万31行业Rank（赛马排序）
2. 行业β过滤（ETF vs 沪深300 20日滚动β > 1.1 才进入赛马）
3. 宏观时钟→行业轮动映射
4. 行业景气/验证信号
"""

from typing import List, Dict, Optional
import numpy as np
from datetime import datetime

try:
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES, SECTOR_GROUPS, \
        SECTOR_BETA_DEFAULT, MACRO_CLOCK_SECTOR
except ImportError:
    from scripts.config import SECTOR_ETF_MAPPING, SECTOR_NAMES, SECTOR_GROUPS, \
        SECTOR_BETA_DEFAULT, MACRO_CLOCK_SECTOR


def compute_sector_relative_strength(etf_closes: List[float],
                                     benchmark_closes: List[float],
                                     lookback: int = 20) -> dict:
    """计算行业相对强度（ETF vs 沪深300）。

    Args:
        etf_closes: ETF收盘价序列
        benchmark_closes: 沪深300收盘价序列
        lookback: 计算周期（默认20日）

    Returns:
        {'relative_strength': float, 'beta_20d': float,
         'is_strong': bool, 'is_weak': bool, 'rolling_rank': int}
    """
    if len(etf_closes) < lookback or len(benchmark_closes) < lookback:
        return {'relative_strength': 1.0, 'beta_20d': 1.0,
                'is_strong': False, 'is_weak': False, 'rolling_rank': 0}

    etf_return = etf_closes[-1] / etf_closes[-lookback] - 1
    bench_return = benchmark_closes[-1] / benchmark_closes[-lookback] - 1
    relative_strength = (1 + etf_return) / (1 + bench_return) if bench_return > -1 else 1.0

    # 20日滚动Beta
    returns_etf = [etf_closes[i] / etf_closes[i-1] - 1 for i in range(-lookback, 0)]
    returns_bench = [benchmark_closes[i] / benchmark_closes[i-1] - 1 for i in range(-lookback, 0)]

    if len(returns_etf) >= 2:
        cov = np.cov(returns_etf, returns_bench)[0][1]
        var_bench = np.var(returns_bench)
        beta = cov / var_bench if var_bench > 1e-10 else 1.0
    else:
        beta = 1.0

    return {
        'relative_strength': round(relative_strength, 3),
        'beta_20d': round(beta, 3),
        'is_strong': relative_strength > 1.05,
        'is_weak': relative_strength < 0.95,
        'rolling_rank': 0,  # rank在 rank_sectors 中计算
    }


def compute_beta_filter(beta: float, threshold: float = 1.1) -> dict:
    """行业β过滤：ETF 相对沪深300 的20日滚动β > 1.1 才进入赛马。

    Args:
        beta: 20日滚动β值
        threshold: 阈值（默认1.1）

    Returns:
        {'pass': bool, 'beta': float, 'note': str}
    """
    if beta >= threshold:
        return {'pass': True, 'beta': beta, 'note': f'β={beta:.2f}≥{threshold}，通过'}
    else:
        return {'pass': False, 'beta': beta, 'note': f'β={beta:.2f}<{threshold}，低β行业不参与赛马'}


def rank_sectors(sector_signals: List[dict]) -> List[dict]:
    """对31个申万行业进行赛马排序。

    排序依据：综合L1-L4得分（来自scoring_system）。

    Args:
        sector_signals: 各行业的信号数据，每项包含
            {'sector': str, 'total_score': int, 'grade': str, ...}

    Returns:
        按信号质量降序排列的行业列表，每项包含rank字段
    """
    if not sector_signals:
        return []

    # 按总分降序
    ranked = sorted(sector_signals, key=lambda x: x.get('total_score', 0), reverse=True)

    for i, r in enumerate(ranked):
        r['rank'] = i + 1

    return ranked


def filter_ranked_for_trading(ranked: List[dict], sector_betas: dict = None,
                              top_n: int = 5) -> List[dict]:
    """从排序结果中筛选可交易行业。

    规则：
    1. TOP5 进入核心观察池
    2. β > 1.1 才可交易（排除低β防御行业）
    3. 排除 exhausted/reversal 阶段的行业

    Args:
        ranked: rank_sectors() 的输出
        sector_betas: {sector: beta} 字典
        top_n: 最多取前N个

    Returns:
        可交易行业列表
    """
    if not ranked:
        return []

    tradable = []
    for r in ranked:
        sector = r.get('sector', '')
        stage = r.get('trend_stage', '')

        # 排除衰竭和反转
        if stage in ('exhausted', 'reversal'):
            continue

        # β过滤
        beta = (sector_betas or {}).get(sector, SECTOR_BETA_DEFAULT.get(sector, 1.0))
        if beta < 1.1:
            continue

        tradable.append(r)

        if len(tradable) >= top_n:
            break

    return tradable


def get_macro_clock_sectors(macro_phase: str = 'default') -> list:
    """根据宏观时钟阶段获取偏好行业。

    Args:
        macro_phase: 宏观阶段
            '复苏' / '过热1' / '过热2' / '滞胀' / '衰退1' / '衰退2' / 'default'

    Returns:
        建议配置的行业名称列表
    """
    preferred_groups = MACRO_CLOCK_SECTOR.get(macro_phase, MACRO_CLOCK_SECTOR['default'])
    sectors = []
    for group in preferred_groups:
        sectors.extend(SECTOR_GROUPS.get(group, []))
    return sectors


def compute_sector_intensity(bench_return: float) -> str:
    """根据基准收益判断宏观时钟阶段（简化版）。

    Args:
        bench_return: 沪深300近60日收益率

    Returns:
        str: 宏观阶段
    """
    if bench_return > 0.10:
        return '过热2'
    elif bench_return > 0.05:
        return '过热1'
    elif bench_return > 0:
        return '复苏'
    elif bench_return > -0.08:
        return '衰退1'
    else:
        return '衰退2'


def sector_momentum_rank(all_closes: dict, lookback: int = 20) -> List[dict]:
    """行业动量排序（基于价格回报）。

    Args:
        all_closes: {sector: [close_prices]} 所有行业的收盘价序列
        lookback: 动量计算周期

    Returns:
        按动量强度排序的行业列表 [{'sector': '', 'momentum': float}, ...]
    """
    rankings = []
    for sector, closes in all_closes.items():
        if len(closes) < lookback:
            continue
        momentum = closes[-1] / closes[-lookback] - 1
        rankings.append({'sector': sector, 'momentum': round(momentum * 100, 2)})

    rankings.sort(key=lambda x: x['momentum'], reverse=True)
    for i, r in enumerate(rankings):
        r['rank'] = i + 1

    return rankings
