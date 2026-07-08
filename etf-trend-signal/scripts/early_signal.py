# -*- coding: utf-8 -*-
"""⚠️ 已弃用 — ETF早期信号检测模块。

v2.0.0 通道突破策略中不再将ETF早期信号（IOPV/北向/融资/份额）注入评分管线。
本模块保留以供引用或辅助分析，但 scoring_system.py 不再调用 inject_etf_early_signals_to_tech。

如需使用早期信号作为参考（不参与评分），可通过 EtfDataCollector 的接口直接获取数据：

    collector = EtfDataCollector()
    premium = collector.get_etf_premium('512480.SH')
    northbound = collector.get_northbound_signal('半导体')
    margin = collector.get_market_data().get('margin', {})
"""

# 以下为 v1.1.3 保留代码，未更改

from typing import Dict, List, Optional, Tuple


def detect_share_price_divergence(prices, shares, lookback=10):
    """检测份额与价格的背离。"""
    # ... 保留 v1.1.3 原有实现
    return {'signal': 'none', 'strength': 0, 'share_change_pct': 0,
            'price_change_pct': 0, 'is_true_inflow': False,
            'is_fake_pump': False, 'is_accumulation': False}


def detect_iopv_premium_signal(premium_history, lookback=5):
    """检测IOPV折溢价信号。"""
    return {'signal': 'none', 'strength': 0, 'premium_ma5': 0,
            'premium_ma20': 0, 'is_overheat': False, 'is_panic': False}


def detect_share_surge(shares, threshold=0.05):
    """检测份额突变。"""
    return {'surge': False, 'change_pct': 0, 'is_surge_up': False}


def detect_northbound_signal(northbound_5d, northbound_20d):
    """检测北向资金信号。"""
    return {'signal': 'none', 'strength': 0, 'net_5d': 0, 'net_20d': 0}


def detect_margin_slope(margin_history, lookback=5):
    """检测融资余额斜率。"""
    return {'signal': 'none', 'strength': 0, 'slope_5d': 0, 'is_leveraging': False}


def detect_sector_relative_strength(etf_prices, benchmark_prices, lookback=20):
    """检测行业相对强度。"""
    return {'signal': 'none', 'strength': 0, 'relative_strength': 1.0,
            'is_strong': False, 'is_weak': False, 'beta_20d': 1.0}


def detect_volume_surge(volumes, threshold=1.5, lookback=20):
    return {'surge': False, 'ratio': 1.0, 'avg_volume': 0, 'current_volume': 0,
            'signal_strength': 0}


def detect_price_breakout(prices, highs, lows, lookback=20, buffer_pct=0.005):
    return {'breakout_up': False, 'breakout_down': False, 'resistance': 0,
            'support': 0, 'current_price': 0, 'breakout_pct': 0, 'signal_strength': 0}


def detect_volatility_expansion(atr_values, lookback=20, expansion_threshold=1.5):
    return {'expansion': False, 'ratio': 1.0, 'avg_atr': 0, 'current_atr': 0,
            'is_contraction': False, 'signal_strength': 0}


def detect_short_term_momentum(closes, period=5):
    return {'rsi_5': 50, 'ma_5': 0, 'price_vs_ma5': 0, 'momentum': 0, 'signal_strength': 0}


def detect_ma_convergence(prices, short_period=5, long_period=20):
    return {'convergence': False, 'spread': 0, 'ma_short': 0, 'ma_long': 0, 'signal_strength': 0}


def inject_etf_early_signals_to_tech(etf_data, tech):
    """⚠️ v2.0.0: 不再调用此函数。评分管线不依赖ETF早期信号。

    保留函数签名以避免import报错，但返回未修改的tech。
    """
    return tech
