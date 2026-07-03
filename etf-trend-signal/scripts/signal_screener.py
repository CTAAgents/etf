# -*- coding: utf-8 -*-
"""信号筛选模块（ETF版）。

保留commodity版本的L1-L4筛选举架，新增行业β过滤。
"""

from typing import List, Dict, Optional

try:
    from scripts.indicators import assess_trend_maturity
except ImportError:
    from indicators import assess_trend_maturity


def detect_trend_stage(tech: dict, score: int) -> dict:
    """检测趋势阶段 — 委派 indicators.assess_trend_maturity()"""
    price = tech.get('last_price', 0)
    sym = {'last_price': price}
    maturity = assess_trend_maturity(tech, sym, 1 if score > 0 else -1)
    stage = maturity.get('stage', 'unknown')
    reasons_map = {
        'launch': ['趋势刚启动，通道突破+均线排列初期'],
        'trending': ['主趋势运行中'],
        'exhausted': ['趋势衰竭，RSI极端+通道极值'],
        'reversal': ['趋势反转，价格穿越DC55中轨'],
    }
    return {'stage': stage, 'reasons': reasons_map.get(stage, ['趋势不明确'])}


def count_resonance(tech: dict, score: int) -> dict:
    """计算多指标共振度（ETF版，保留commodity逻辑，去除OI相关项）。"""
    is_bull = score > 0
    confirmations = 0
    total_checks = 0
    details = []

    # ROC方向
    roc10 = tech.get('ROC10')
    if roc10 is not None:
        total_checks += 1
        if (is_bull and roc10 > 0) or (not is_bull and roc10 < 0):
            confirmations += 1; details.append('ROC✓')
        else:
            details.append('ROC✗')

    # MA斜率
    ma_slope = tech.get('MA20_SLOPE')
    if ma_slope is not None:
        total_checks += 1
        if (is_bull and ma_slope > -0.5) or (not is_bull and ma_slope < 0.5):
            confirmations += 0.5; details.append('MA斜率✓')
        else:
            details.append('MA斜率✗')

    # %b位置
    bb_pctb = tech.get('BB_PCTB')
    if bb_pctb is not None:
        total_checks += 1
        if (is_bull and bb_pctb > 0.5) or (not is_bull and bb_pctb < 0.5):
            confirmations += 0.5; details.append('%b✓')
        else:
            details.append('%b✗')

    # OBV方向
    obv, obv_ma = tech.get('OBV'), tech.get('OBV_MA20')
    if obv is not None and obv_ma is not None:
        total_checks += 1
        if (is_bull and obv > obv_ma) or (not is_bull and obv < obv_ma):
            confirmations += 1; details.append('OBV✓')
        else:
            details.append('OBV✗')

    # CMF方向
    cmf21 = tech.get('CMF21')
    if cmf21 is not None:
        total_checks += 1
        if (is_bull and cmf21 > 0) or (not is_bull and cmf21 < 0):
            confirmations += 0.5; details.append('CMF✓')
        else:
            details.append('CMF✗')

    # Vortex方向
    vi_plus, vi_minus = tech.get('VI_PLUS'), tech.get('VI_MINUS')
    if vi_plus is not None and vi_minus is not None:
        total_checks += 1
        if (is_bull and vi_plus > vi_minus) or (not is_bull and vi_minus > vi_plus):
            confirmations += 1; details.append('Vortex✓')
        else:
            details.append('Vortex✗')

    # CCI方向
    cci = tech.get('CCI20')
    if cci is not None:
        total_checks += 1
        if (is_bull and cci > 0) or (not is_bull and cci < 0):
            confirmations += 0.5; details.append('CCI✓')
        else:
            details.append('CCI✗')

    # Supertrend方向
    st_dir = tech.get('SUPERTREND_DIR')
    if st_dir is not None:
        total_checks += 1
        if (is_bull and st_dir == 1) or (not is_bull and st_dir == -1):
            confirmations += 1; details.append('Supertrend✓')
        else:
            details.append('Supertrend✗')

    # HMA交叉
    hma_cross = tech.get('HMA_CROSS')
    if hma_cross is not None:
        total_checks += 1
        if (is_bull and hma_cross == 'bull') or (not is_bull and hma_cross == 'bear'):
            confirmations += 0.5; details.append('HMA✓')
        else:
            details.append('HMA✗')

    # RSI方向
    rsi = tech.get('RSI14')
    if rsi is not None:
        total_checks += 1
        if (is_bull and rsi > 50) or (not is_bull and rsi < 50):
            confirmations += 1; details.append('RSI✓')
        else:
            details.append('RSI✗')

    # DMI方向
    pdi, mdi = tech.get('DMI_PDI'), tech.get('DMI_MDI')
    if pdi is not None and mdi is not None:
        total_checks += 1
        if (is_bull and pdi > mdi) or (not is_bull and mdi > pdi):
            confirmations += 1; details.append('DMI✓')
        else:
            details.append('DMI✗')

    # MA排列
    ma5, ma10, ma20 = tech.get('MA5'), tech.get('MA10'), tech.get('MA20')
    ma40, ma60 = tech.get('MA40'), tech.get('MA60')
    if ma5 and ma10 and ma20:
        total_checks += 1
        short_bull = ma5 > ma10 > ma20
        short_bear = ma5 < ma10 < ma20
        long_bull = (ma20 > ma40 > ma60) if (ma40 and ma60) else True
        long_bear = (ma20 < ma40 < ma60) if (ma40 and ma60) else True
        if (is_bull and short_bull and long_bull) or (not is_bull and short_bear and long_bear):
            confirmations += 1; details.append('MA排列✓')
        elif (is_bull and short_bull) or (not is_bull and short_bear):
            confirmations += 0.5; details.append('MA短周期✓')
        else:
            details.append('MA排列✗')

    # MACD
    macd_dif = tech.get('MACD_DIF')
    if macd_dif is not None:
        total_checks += 1
        if (is_bull and macd_dif > 0) or (not is_bull and macd_dif < 0):
            confirmations += 1; details.append('MACD✓')
        else:
            details.append('MACD✗')

    # 价格位置
    last_price = tech.get('last_price')
    if last_price and ma20:
        total_checks += 1
        if (is_bull and last_price > ma20) or (not is_bull and last_price < ma20):
            confirmations += 1; details.append('价格位✓')
        else:
            details.append('价格位✗')

    resonance_ratio = confirmations / total_checks if total_checks > 0 else 0

    return {
        'confirmations': confirmations,
        'total_checks': total_checks,
        'ratio': round(resonance_ratio, 2),
        'details': details,
    }


def screen_signals(symbols: List[dict], score_threshold: int = 20,
                   min_resonance: float = 0.5, exclude_exhausted: bool = True,
                   top_n: int = 0, beta_filter: bool = True) -> List[dict]:
    """扫描所有ETF，筛选出有交易价值的信号（ETF版）。

    新增：
    - beta_filter: 是否启用行业β过滤（默认启用，排除β<1.1的低贝塔行业）

    Args:
        symbols: ETF信号数据列表
        score_threshold: 最低分数阈值
        min_resonance: 最低共振度
        exclude_exhausted: 是否排除衰竭阶段
        top_n: 取前N名（0=全部）
        beta_filter: 是否启用β过滤

    Returns:
        筛选后的候选列表
    """
    buy_count = sum(1 for s in symbols if s.get('direction', '') == 'BUY' and s.get('score', 0) > score_threshold)
    sell_count = sum(1 for s in symbols if s.get('direction', '') == 'SELL' and s.get('score', 0) > score_threshold)
    market_bearish = sell_count > buy_count * 1.5
    market_bullish = buy_count > sell_count * 1.5

    candidates = []

    for sym in symbols:
        score = sym.get('score', 0)
        if score < score_threshold:
            continue

        tech = sym.get('tech', {})
        tech_with_price = dict(tech)
        tech_with_price['last_price'] = sym.get('last_price')

        stage = detect_trend_stage(tech_with_price, score)
        if exclude_exhausted and stage['stage'] == 'exhausted':
            continue

        # β过滤
        if beta_filter:
            beta = sym.get('beta_20d', sym.get('beta', 1.0))
            if beta < 1.1:
                continue

        resonance = count_resonance(tech_with_price, score)

        direction = sym.get('direction', 'BUY' if score > 0 else 'SELL')
        required_resonance = min_resonance
        if market_bearish and direction == 'BUY':
            required_resonance = 0.6
        elif market_bullish and direction == 'SELL':
            required_resonance = 0.6

        if resonance['ratio'] < required_resonance:
            continue

        stage_factor = {'launch': 1.3, 'trending': 1.0, 'exhausted': 0.4, 'reversal': 0.2}.get(stage['stage'], 0.8)
        signal_quality = round(abs(score) / 100.0 * resonance['ratio'] * stage_factor, 3)

        total_100 = sym.get('total_score', sym.get('score', 0))
        if total_100 >= 75:
            tier = 'T2'
        elif total_100 >= 60:
            tier = 'T1'
        else:
            tier = 'T0'

        candidates.append({
            'sector': sym.get('sector', sym.get('product_id', '')),
            'etf_code': sym.get('etf_code', ''),
            'last_price': sym.get('last_price', 0),
            'score': score,
            'direction': direction,
            'trend_stage': stage,
            'resonance': resonance,
            'signal_quality': signal_quality,
            'tier': tier,
            'composite_total': total_100,
            'tech': tech,
            'beta': sym.get('beta', 1.0),
            'rank': 0,
        })

    candidates.sort(key=lambda x: x['signal_quality'], reverse=True)

    if top_n > 0 and len(candidates) > top_n:
        candidates = candidates[:top_n]

    for i, c in enumerate(candidates):
        c['rank'] = i + 1

    return candidates
