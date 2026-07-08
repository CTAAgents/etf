# -*- coding: utf-8 -*-
"""行业ETF趋势信号发现系统 v2.0 — 通道突破策略（通达信TQ-Local）

评分架构：
  Layer A: 唐奇安通道 (75%) — DC20短期突破 + DC55中期趋势
  Layer B: 布林带确认 (25%) — 带宽扩张/收缩 + 挤压检测 + %b位置
  Volume: 成交量确认 (独立加减分, -3 ~ ±10)

快速入口：
    from scripts.collect_data import EtfDataCollector
    from scripts.indicators import _compute_indicators_numpy
    from scripts.scoring_system import calculate_composite_score, score_dc20, score_dc55, score_bb, score_volume
    from scripts.config import SECTOR_ETF_MAPPING, CHANNEL_BREAKOUT_CONFIG
    from scripts.signal_screener import screen_signals
    from scripts.trade_plan import generate_trade_plan
"""

__all__ = [
    'EtfDataCollector',
    'TdxCollector',
    'calculate_composite_score',
    'score_dc20', 'score_dc55', 'score_bb', 'score_volume',
    'determine_grade', 'determine_direction', 'determine_signal_type',
    'screen_signals',
    'generate_trade_plan',
    'SECTOR_ETF_MAPPING',
    'CHANNEL_BREAKOUT_CONFIG',
]
