# -*- coding: utf-8 -*-
"""ETF早期信号检测模块：替代期货的OI/基差/期限结构，使用ETF专属信号。

核心替换：
- OI三角 → 份额-价格背离（Fund Share Divergence）
- 基差走强/走弱 → IOPV折溢价走阔
- 期限结构 → 行业相对强度（ETF vs 沪深300 beta）
- 跨期Spread → 同行业多ETF联动

新增ETF专属早期信号：
- 份额突变（单日份额环比 > 5%，滞后1-3日往往有行情）
- 北向行业资金5日累计（替代"外资席位"逻辑）
- 融资余额斜率（两融数据）
"""

from typing import List, Dict, Optional
import numpy as np


def detect_share_price_divergence(prices: List[float], shares: List[float],
                                  lookback: int = 10) -> dict:
    """检测份额-价格背离信号（替代OI三角）。

    核心逻辑：
    - 价涨份额增 = 真流入（类OI增仓上行）
    - 价涨份额减 = 虚拉（类OI减仓上行，假突破）
    - 价稳份额增 = 建仓胚（类OI建仓）

    Args:
        prices: 收盘价序列
        shares: 基金份额序列（万份）
        lookback: 回看周期

    Returns:
        {'signal': str, 'strength': str, 'share_change_pct': float,
         'price_change_pct': float, 'is_true_inflow': bool, 'is_fake_pump': bool}
    """
    if len(prices) < lookback + 2 or len(shares) < lookback + 2:
        return {
            'signal': 'none', 'strength': 'weak',
            'share_change_pct': 0, 'price_change_pct': 0,
            'is_true_inflow': False, 'is_fake_pump': False,
            'is_accumulation': False,
        }

    current_share = shares[-1]
    avg_share = np.mean(shares[-(lookback+1):-1]) if len(shares) > lookback + 1 else current_share
    current_price = prices[-1]
    past_price = prices[-(lookback+1)]

    share_change_pct = (current_share - avg_share) / avg_share * 100 if avg_share > 0 else 0
    price_change_pct = (current_price - past_price) / past_price * 100 if past_price > 0 else 0

    signal = 'none'
    strength = 'weak'
    is_true_inflow = False
    is_fake_pump = False
    is_accumulation = False

    # 真流入：价涨 + 份额增
    if price_change_pct > 1.0 and share_change_pct > 1.0:
        is_true_inflow = True
        signal = 'true_inflow'
        strength = 'strong' if share_change_pct > 3.0 else 'moderate'

    # 假拉升：价涨但份额减
    elif price_change_pct > 1.0 and share_change_pct < -1.0:
        is_fake_pump = True
        signal = 'fake_pump'
        strength = 'moderate'

    # 建仓胚：价横 ±1.5% + 份额增
    elif abs(price_change_pct) < 1.5 and share_change_pct > 1.0:
        is_accumulation = True
        signal = 'accumulation'
        strength = 'strong' if share_change_pct > 3.0 else 'moderate'

    # 份额流失：价跌 + 份额减
    elif price_change_pct < -1.0 and share_change_pct < -1.0:
        signal = 'share_drain'
        strength = 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'share_change_pct': round(share_change_pct, 2),
        'price_change_pct': round(price_change_pct, 2),
        'is_true_inflow': is_true_inflow,
        'is_fake_pump': is_fake_pump,
        'is_accumulation': is_accumulation,
    }


def detect_iopv_premium_signal(premium_history: List[float], lookback: int = 5) -> dict:
    """检测IOPV折溢价信号（替代基差走强/走弱）。

    溢价率 > 1% 且扩大 = 情绪过热
    折价率 > 2% 且扩大 = 恐慌过度
    折溢价回归0轴 = 情绪正常化

    Args:
        premium_history: 溢价率序列（正=溢价，负=折价）
        lookback: MA计算周期

    Returns:
        {'signal': str, 'strength': str,
         'premium_ma5': float, 'premium_ma20': float,
         'is_overheat': bool, 'is_panic': bool}
    """
    if len(premium_history) < lookback + 5:
        return {
            'signal': 'none', 'strength': 'weak',
            'premium_ma5': None, 'premium_ma20': None,
            'is_overheat': False, 'is_panic': False,
        }

    premium_ma5 = np.mean(premium_history[-5:])
    premium_ma20 = np.mean(premium_history[-20:]) if len(premium_history) >= 20 else np.mean(premium_history)
    current_premium = premium_history[-1]

    is_overheat = current_premium > 1.0 and premium_ma5 > premium_ma20
    is_panic = current_premium < -2.0
    is_strengthening = premium_ma5 > premium_ma20
    is_weakening = premium_ma5 < premium_ma20

    signal = 'none'
    strength = 'weak'

    if is_overheat:
        signal = 'overheat_premium'
        strength = 'strong' if current_premium > 2.0 else 'moderate'
    elif is_panic:
        signal = 'panic_discount'
        strength = 'strong' if current_premium < -3.0 else 'moderate'
    elif is_strengthening and current_premium > 0:
        signal = 'premium_widening'
        strength = 'moderate'
    elif is_weakening and current_premium < 0:
        signal = 'discount_deepening'
        strength = 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'premium_ma5': round(premium_ma5, 2),
        'premium_ma20': round(premium_ma20, 2),
        'current_premium': round(current_premium, 2),
        'is_overheat': is_overheat,
        'is_panic': is_panic,
    }


def detect_share_surge(shares: List[float], threshold: float = 0.05) -> dict:
    """检测份额突变（单日份额环比 > 5%）。

    份额突变 滞后1-3日往往有行情，是非常早期的信号。

    Args:
        shares: 份额序列
        threshold: 突变阈值（默认5%）

    Returns:
        {'surge': bool, 'change_pct': float, 'is_surge_up': bool}
    """
    if len(shares) < 2:
        return {'surge': False, 'change_pct': 0, 'is_surge_up': False}

    change_pct = (shares[-1] / shares[-2] - 1) * 100 if shares[-2] > 0 else 0

    return {
        'surge': abs(change_pct) > threshold * 100,
        'change_pct': round(change_pct, 2),
        'is_surge_up': change_pct > 0,
    }


def detect_northbound_signal(northbound_5d: float, northbound_20d: float) -> dict:
    """检测北向资金信号（替代外资席位逻辑）。

    Args:
        northbound_5d: 近5日北向净流入
        northbound_20d: 近20日北向净流入

    Returns:
        {'signal': str, 'strength': str, 'net_5d': float, 'net_20d': float}
    """
    signal = 'none'
    strength = 'weak'

    # 5日持续流入
    if northbound_5d > 50:  # 5日累计 > 50亿
        if northbound_20d > 200:  # 20日 > 200亿
            signal = 'strong_inflow'
            strength = 'strong'
        else:
            signal = 'recent_inflow'
            strength = 'moderate'
    elif northbound_5d < -50:
        if northbound_20d < -200:
            signal = 'strong_outflow'
            strength = 'strong'
        else:
            signal = 'recent_outflow'
            strength = 'moderate'

    # 方向反转：5日流入但20日流出 → 拐点
    if northbound_5d > 30 and northbound_20d < -50:
        signal = 'inflow_reversal'
        strength = 'strong'
    elif northbound_5d < -30 and northbound_20d > 50:
        signal = 'outflow_reversal'
        strength = 'strong'

    return {
        'signal': signal,
        'strength': strength,
        'net_5d': round(northbound_5d, 1),
        'net_20d': round(northbound_20d, 1),
    }


def detect_margin_slope(margin_history: List[float], lookback: int = 5) -> dict:
    """检测融资余额斜率（两融数据替代场内杠杆）。

    Args:
        margin_history: 融资余额序列
        lookback: 斜率计算周期

    Returns:
        {'signal': str, 'strength': str, 'slope_5d': float, 'is_leveraging': bool}
    """
    if len(margin_history) < lookback + 1:
        return {
            'signal': 'none', 'strength': 'weak',
            'slope_5d': 0, 'is_leveraging': False,
        }

    recent = margin_history[-lookback:]
    x = np.arange(lookback)
    slope = np.polyfit(x, recent, 1)[0]

    is_leveraging = slope > 0

    signal = 'none'
    strength = 'weak'

    if slope > 50:  # 融资余额快速上升
        signal = 'margin_leveraging'
        strength = 'strong'
    elif slope > 10:
        signal = 'margin_rising'
        strength = 'moderate'
    elif slope < -50:  # 融资余额快速下降（去杠杆）
        signal = 'margin_deleveraging'
        strength = 'strong'
    elif slope < -10:
        signal = 'margin_falling'
        strength = 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'slope_5d': round(slope, 1),
        'is_leveraging': is_leveraging,
    }


def detect_sector_relative_strength(etf_prices: List[float], benchmark_prices: List[float],
                                    lookback: int = 20) -> dict:
    """检测行业相对强度（ETF vs 沪深300，替代期限结构）。

    相对强度 = ETF涨幅 / 基准涨幅。
    >1.1 = 相对强势，<0.9 = 相对弱势。

    Args:
        etf_prices: ETF收盘价序列
        benchmark_prices: 基准指数（沪深300）收盘价序列
        lookback: 计算周期

    Returns:
        {'signal': str, 'strength': str, 'relative_strength': float,
         'is_strong': bool, 'is_weak': bool, 'beta_20d': float}
    """
    if len(etf_prices) < lookback or len(benchmark_prices) < lookback:
        return {
            'signal': 'none', 'strength': 'weak',
            'relative_strength': 1.0, 'is_strong': False, 'is_weak': False,
            'beta_20d': 1.0,
        }

    etf_return = etf_prices[-1] / etf_prices[-lookback] - 1
    bench_return = benchmark_prices[-1] / benchmark_prices[-lookback] - 1

    relative_strength = (1 + etf_return) / (1 + bench_return) if bench_return > -1 else 1.0

    # 滚动Beta估算
    returns_etf = [etf_prices[i] / etf_prices[i-1] - 1 for i in range(-lookback, 0)]
    returns_bench = [benchmark_prices[i] / benchmark_prices[i-1] - 1 for i in range(-lookback, 0)]
    cov = np.cov(returns_etf, returns_bench)[0][1] if len(returns_etf) > 1 else 0
    var = np.var(returns_bench) if len(returns_bench) > 1 else 1e-10
    beta = cov / var if var > 1e-10 else 1.0

    is_strong = relative_strength > 1.05
    is_weak = relative_strength < 0.95

    signal = 'none'
    strength = 'weak'

    if relative_strength > 1.1 and beta > 1.2:
        signal = 'relative_strong_beta'
        strength = 'strong'
    elif relative_strength > 1.05:
        signal = 'relative_strong'
        strength = 'moderate'
    elif relative_strength < 0.9 and beta > 0:
        signal = 'relative_weak'
        strength = 'strong'
    elif relative_strength < 0.95:
        signal = 'relative_weak'
        strength = 'moderate'

    return {
        'signal': signal,
        'strength': strength,
        'relative_strength': round(relative_strength, 4),
        'is_strong': is_strong,
        'is_weak': is_weak,
        'beta_20d': round(beta, 3),
    }


def detect_volume_surge(volumes: List[float], threshold: float = 1.5, lookback: int = 20) -> dict:
    """检测成交量异动（放量突破）。"""
    if len(volumes) < lookback + 1:
        return {'surge': False, 'ratio': 0, 'avg_volume': 0, 'current_volume': 0, 'signal_strength': 'weak'}

    avg_volume = np.mean(volumes[-(lookback+1):-1])
    current_volume = volumes[-1]

    if avg_volume <= 0:
        return {'surge': False, 'ratio': 0, 'avg_volume': 0, 'current_volume': current_volume, 'signal_strength': 'weak'}

    ratio = current_volume / avg_volume

    if ratio >= 2.0:
        signal_strength = 'strong'
    elif ratio >= threshold:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'

    return {
        'surge': ratio >= threshold,
        'ratio': round(ratio, 2),
        'avg_volume': round(avg_volume, 2),
        'current_volume': current_volume,
        'signal_strength': signal_strength,
    }


def detect_price_breakout(prices, highs, lows, lookback: int = 20, buffer_pct: float = 0.005) -> dict:
    """检测价格突破关键阻力/支撑位。"""
    if len(prices) < lookback + 1:
        return {'breakout_up': False, 'breakout_down': False, 'resistance': 0, 'support': 0,
                'current_price': 0, 'breakout_pct': 0, 'signal_strength': 'weak'}

    recent_high = max(highs[-(lookback+1):-1])
    recent_low = min(lows[-(lookback+1):-1])
    current_price = prices[-1]
    resistance_buffer = recent_high * (1 + buffer_pct)
    support_buffer = recent_low * (1 - buffer_pct)

    breakout_up = current_price > resistance_buffer
    breakout_down = current_price < support_buffer

    if breakout_up:
        breakout_pct = (current_price - recent_high) / recent_high * 100
    elif breakout_down:
        breakout_pct = (recent_low - current_price) / recent_low * 100
    else:
        breakout_pct = 0

    if abs(breakout_pct) > 2:
        signal_strength = 'strong'
    elif abs(breakout_pct) > 1:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'

    return {
        'breakout_up': breakout_up, 'breakout_down': breakout_down,
        'resistance': round(recent_high, 2), 'support': round(recent_low, 2),
        'current_price': current_price, 'breakout_pct': round(breakout_pct, 2),
        'signal_strength': signal_strength,
    }


def detect_volatility_expansion(atr_values, lookback=20, expansion_threshold=1.5) -> dict:
    """检测波动率突破（ATR收缩后扩张）。"""
    if len(atr_values) < lookback + 1:
        return {'expansion': False, 'ratio': 0, 'avg_atr': 0, 'current_atr': 0,
                'is_contraction': False, 'signal_strength': 'weak'}

    avg_atr = np.mean(atr_values[-(lookback+1):-1])
    current_atr = atr_values[-1]

    if avg_atr <= 0:
        return {'expansion': False, 'ratio': 0, 'avg_atr': 0, 'current_atr': current_atr,
                'is_contraction': False, 'signal_strength': 'weak'}

    ratio = current_atr / avg_atr

    if len(atr_values) >= 6:
        recent_atr = atr_values[-6:-1]
        is_contraction = all(atr <= avg_atr for atr in recent_atr)
    else:
        is_contraction = ratio < 0.8

    expansion = is_contraction and ratio > expansion_threshold

    if expansion and ratio > expansion_threshold * 1.5:
        signal_strength = 'strong'
    elif expansion:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'

    return {
        'expansion': expansion, 'ratio': round(ratio, 2),
        'avg_atr': round(avg_atr, 4), 'current_atr': round(current_atr, 4),
        'is_contraction': is_contraction, 'signal_strength': signal_strength,
    }


def detect_short_term_momentum(closes, period=5) -> dict:
    """检测短期动量。"""
    if len(closes) < period + 1:
        return {'rsi_5': 50, 'ma_5': 0, 'price_vs_ma5': 'at',
                'momentum': 'neutral', 'signal_strength': 'weak'}

    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(0, change) for change in changes[-period:]]
    losses = [max(0, -change) for change in changes[-period:]]

    avg_gain = np.mean(gains) if gains else 0
    avg_loss = np.mean(losses) if losses else 0

    if avg_loss == 0 and avg_gain == 0:
        rsi_5 = 50
    elif avg_loss == 0:
        rsi_5 = 100
    else:
        rs = avg_gain / avg_loss
        rsi_5 = 100 - (100 / (1 + rs))

    ma_5 = np.mean(closes[-period:])
    current_price = closes[-1]

    if current_price > ma_5 * 1.005:
        price_vs_ma5 = 'above'
    elif current_price < ma_5 * 0.995:
        price_vs_ma5 = 'below'
    else:
        price_vs_ma5 = 'at'

    if rsi_5 > 70 and price_vs_ma5 == 'above':
        momentum = 'strong_up'
    elif rsi_5 > 60:
        momentum = 'up'
    elif rsi_5 < 30 and price_vs_ma5 == 'below':
        momentum = 'strong_down'
    elif rsi_5 < 40:
        momentum = 'down'
    else:
        momentum = 'neutral'

    if momentum in ['strong_up', 'strong_down']:
        signal_strength = 'strong'
    elif momentum in ['up', 'down']:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'

    return {'rsi_5': round(rsi_5, 2), 'ma_5': round(ma_5, 2),
            'price_vs_ma5': price_vs_ma5, 'momentum': momentum,
            'signal_strength': signal_strength}


def detect_ma_convergence(prices, short_period=5, long_period=20) -> dict:
    """检测均线收敛。"""
    if len(prices) < long_period + 1:
        return {'convergence': False, 'spread': 0, 'ma_short': 0, 'ma_long': 0, 'signal_strength': 'weak'}

    ma_short = np.mean(prices[-short_period:])
    ma_long = np.mean(prices[-long_period:])
    spread = abs(ma_short - ma_long) / ma_long * 100 if ma_long > 0 else 0
    convergence = 0 < spread < 1.0

    if spread == 0:
        signal_strength = 'weak'
    elif spread < 0.5:
        signal_strength = 'strong'
    elif spread < 1.0:
        signal_strength = 'moderate'
    else:
        signal_strength = 'weak'

    return {'convergence': convergence, 'spread': round(spread, 2),
            'ma_short': round(ma_short, 2), 'ma_long': round(ma_long, 2),
            'signal_strength': signal_strength}


def inject_etf_early_signals_to_tech(etf_data: dict, tech: dict) -> dict:
    """将ETF早期信号注入tech字典（纯通达信版）。

    Args:
        etf_data: ETF专属数据（折溢价/北向/融资）
        tech: 技术指标字典（会被原地修改）

    Returns:
        修改后的tech字典
    """
    # ── 份额信号（通达信不提供ETF级日份额历史，用市场级规模趋势估算）──
    scale = etf_data.get('scale', {})
    if scale:
        net_subscribe = scale.get('net_subscribe', 0)  # 净申赎(亿份)
        if net_subscribe > 0:
            tech['SHARE_INCREASING'] = True
            tech['SHARE_CHANGE_PCT'] = round(net_subscribe, 2)
        elif net_subscribe < 0:
            tech['SHARE_DECREASING'] = True
            tech['SHARE_CHANGE_PCT'] = round(net_subscribe, 2)

    # ── IOPV折溢价信号（纯TDX格式）──
    premium_data = etf_data.get('premium_data', {})
    if isinstance(premium_data, dict) and 'premium_pct' in premium_data:
        premium_pct = float(premium_data.get('premium_pct', 0))
        tech['IOPV_PREMIUM'] = round(premium_pct, 2)
        tech['IOPV_PREMIUM_LATEST'] = tech['IOPV_PREMIUM']
        tech['IOPV_OVERHEAT'] = premium_pct > 1.0
        tech['IOPV_PANIC'] = premium_pct < -2.0

    # ── 北向资金信号 ──
    northbound = etf_data.get('northbound', {})
    if northbound:
        nb_signal = detect_northbound_signal(
            northbound.get('net_inflow_5d', 0),
            northbound.get('net_inflow_20d', 0)
        )
        tech['NORTHBOUND_5D'] = northbound.get('net_inflow_5d', 0)
        tech['NORTHBOUND_20D'] = northbound.get('net_inflow_20d', 0)
        tech['NORTHBOUND_SIGNAL'] = nb_signal.get('signal', 'none')
        tech['NORTHBOUND_STRENGTH'] = nb_signal.get('strength', 'weak')

    # ── 融资余额信号（纯TDX格式：margin_balance / short_balance）──
    margin = etf_data.get('margin', {})
    if margin:
        tech['MARGIN_BALANCE'] = float(margin.get('margin_balance', 0) or 0)
        # TDX不提供逐日净买入，用余额环比变化近似
        tech['MARGIN_NET'] = 0  # TDX SC01只有当日余额无变化量

    # 注入汇总标记
    signal_count = 0
    if tech.get('IOPV_OVERHEAT') or tech.get('IOPV_PANIC'):
        signal_count += 1
    if tech.get('NORTHBOUND_SIGNAL', 'none') not in ('none', ''):
        signal_count += 1
    tech['ETF_EARLY_SIGNALS_COUNT'] = signal_count

    return tech
