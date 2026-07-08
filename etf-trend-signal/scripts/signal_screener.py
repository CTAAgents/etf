# -*- coding: utf-8 -*-
"""信号筛选模块（通道突破策略 v2.0）。

基于 Layer A(唐奇安通道) + Layer B(布林带) + 成交量的评分结果进行筛选。
"""

from typing import List, Dict, Optional


def detect_trend_stage(tech: dict, score: float) -> dict:
    """检测趋势阶段（基于通道突破上下文做简化评判）。

    返回: {'stage': str, 'reasons': list}
    """
    price = tech.get('last_price', 0)
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc55_trend = tech.get('DC55_TREND', 'flat')
    adx = tech.get('ADX', 0)
    rsi = tech.get('RSI14', 50)

    reasons = []

    # 通道突破判断
    is_breakout_up = price > dc_upper if dc_upper else False
    is_breakout_down = price < dc_lower if dc_lower else False

    if adx >= 25 and (dc55_trend == 'up' or dc55_trend == 'down'):
        if is_breakout_up and rsi < 70:
            stage = 'launch'
            reasons.append('DC20突破+DC55趋势健康，初启阶段')
        elif adx > 45 and rsi > 75:
            stage = 'exhausted'
            reasons.append('ADX高+RSI极端，趋势可能衰竭')
        else:
            stage = 'trending'
            reasons.append('DC55趋势明确，主趋势运行中')
    elif is_breakout_down:
        stage = 'reversal'
        reasons.append('跌破DC20下轨，反转风险')
    elif adx < 20:
        stage = 'ranging'
        reasons.append('ADX偏低，震荡整理阶段')
    else:
        stage = 'unknown'
        reasons.append('趋势不明确')

    return {'stage': stage, 'reasons': reasons}


def count_resonance(tech: dict, score: float) -> dict:
    """计算多指标共振度（适配通道突破策略上下文）。

    检查DC20突破方向、DC55趋势方向、BB位置、成交量、ADX的方向一致性。
    """
    is_bull = score > 0
    confirmations = 0.0
    total_checks = 0
    details = []

    last_price = tech.get('last_price')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc55_trend = tech.get('DC55_TREND', 'flat')
    bb_pos = tech.get('BB_PCTB')
    adx = tech.get('ADX')
    vol_ratio = tech.get('VOL_RATIO', 1.0)
    ma_slope = tech.get('MA20_SLOPE')
    rsi = tech.get('RSI14')

    # 1. DC20突破方向
    total_checks += 1
    if last_price and dc_upper and dc_lower:
        dc20_bull = last_price > dc_upper
        dc20_bear = last_price < dc_lower
        if (is_bull and dc20_bull) or (not is_bull and dc20_bear):
            confirmations += 1
            details.append('DC20突破✓')
        elif (is_bull and not dc20_bull and last_price > dc_lower):
            confirmations += 0.3
            details.append('DC20通道内')
        else:
            details.append('DC20突破✗')

    # 2. DC55趋势方向
    total_checks += 1
    if (is_bull and dc55_trend == 'up') or (not is_bull and dc55_trend == 'down'):
        confirmations += 1
        details.append('DC55趋势✓')
    elif dc55_trend == 'flat':
        details.append('DC55平缓')
    else:
        details.append('DC55趋势✗')

    # 3. BB位置
    total_checks += 1
    if bb_pos is not None:
        if (is_bull and bb_pos > 0.5) or (not is_bull and bb_pos < 0.5):
            confirmations += 0.5
            details.append('%b✓')
        else:
            details.append('%b✗')

    # 4. ADX趋势强度
    total_checks += 1
    if adx is not None:
        if adx >= 25:
            confirmations += 1
            details.append(f'ADX{adx:.0f}✓')
        elif adx >= 20:
            confirmations += 0.5
            details.append(f'ADX{adx:.0f}偏弱')
        else:
            details.append(f'ADX{adx:.0f}震荡')

    # 5. 成交量配合
    total_checks += 1
    if vol_ratio is not None and vol_ratio > 1.2:
        confirmations += 1
        details.append('放量✓')
    elif vol_ratio is not None and vol_ratio > 0.8:
        confirmations += 0.3
        details.append('量正常')
    else:
        details.append('缩量✗')

    # 6. MA斜率方向
    total_checks += 1
    if ma_slope is not None:
        if (is_bull and ma_slope > -0.5) or (not is_bull and ma_slope < 0.5):
            confirmations += 0.5
            details.append('MA斜率✓')
        else:
            details.append('MA斜率✗')

    # 7. RSI方向
    total_checks += 1
    if rsi is not None:
        if (is_bull and rsi > 50) or (not is_bull and rsi < 50):
            confirmations += 0.5
            details.append('RSI✓')
        else:
            details.append('RSI✗')

    resonance_ratio = confirmations / total_checks if total_checks > 0 else 0

    return {
        'confirmations': confirmations,
        'total_checks': total_checks,
        'ratio': round(resonance_ratio, 2),
        'details': details,
    }


def screen_signals(symbols: List[dict], score_threshold: int = 20,
                   min_resonance: float = 0.4, exclude_exhausted: bool = True,
                   top_n: int = 0, beta_filter: bool = True,
                   bull_only: bool = True) -> List[dict]:
    """扫描所有ETF，筛选出有价值的信号（通道突破策略版）。

    默认纯多头模式：ETF只做多，过滤空头信号。

    Args:
        symbols: ETF信号数据列表
        score_threshold: 最低分数阈值（abs分）
        min_resonance: 最低共振度
        exclude_exhausted: 是否排除衰竭阶段
        top_n: 取前N名（0=全部）
        beta_filter: 是否启用β过滤
        bull_only: 纯多头模式，过滤空头信号（默认True）

    Returns:
        筛选后的候选列表
    """
    candidates = []

    for sym in symbols:
        score = abs(sym.get('total', 0))
        if score < score_threshold:
            continue

        # 纯多头模式：跳过空头信号
        if bull_only and sym.get('direction') not in ('bull', 'BUY'):
            continue

        tech = {k: sym.get(k) for k in ['ADX', 'RSI14', 'CCI20', 'VOL_RATIO',
                 'DC_UPPER', 'DC_LOWER', 'DC55_TREND', 'BB_PCTB',
                 'MA20_SLOPE', 'MA5', 'MA10', 'MA20', 'last_price', 'SECTOR_BETA']}
        tech['last_price'] = sym.get('last_price', 0) or sym.get('price', 0)
        # 多键名兜底（大小写兼容）
        if tech.get('ADX') is None: tech['ADX'] = sym.get('adx', 0)
        if tech.get('RSI14') is None: tech['RSI14'] = sym.get('rsi', 50)
        if tech.get('VOL_RATIO') is None: tech['VOL_RATIO'] = sym.get('vol_ratio', 1.0)
        if tech.get('DC55_TREND') is None: tech['DC55_TREND'] = sym.get('dc55_trend', 'flat')
        if tech.get('DC_UPPER') is None: tech['DC_UPPER'] = sym.get('dc_upper')
        if tech.get('DC_LOWER') is None: tech['DC_LOWER'] = sym.get('dc_lower')
        if tech.get('BB_PCTB') is None: tech['BB_PCTB'] = sym.get('bb_pos')
        if tech.get('MA20_SLOPE') is None: tech['MA20_SLOPE'] = sym.get('ma_slope', 0)
        if tech.get('SECTOR_BETA') is None: tech['SECTOR_BETA'] = sym.get('beta', 1.0)

        stage_data = detect_trend_stage(tech, sym.get('total', 0))
        if exclude_exhausted and stage_data['stage'] == 'exhausted':
            continue

        # β过滤
        if beta_filter:
            beta = sym.get('beta', 1.0)
            if beta < 1.1:
                continue

        resonance = count_resonance(tech, sym.get('total', 0))

        if resonance['ratio'] < min_resonance:
            continue

        direction = sym.get('direction', 'bull' if sym.get('total', 0) > 0 else 'bear')

        stage_factor = {
            'launch': 1.3, 'trending': 1.0,
            'exhausted': 0.4, 'reversal': 0.2, 'ranging': 0.6
        }.get(stage_data['stage'], 0.8)

        abs_score = abs(sym.get('total', 0))
        max_score = 76.0  # 理论最大绝对值
        signal_quality = round(abs_score / max_score * resonance['ratio'] * stage_factor, 3)

        grade = sym.get('grade', 'NOISE')
        if grade == 'STRONG':
            tier = 'T2'
        elif grade == 'WATCH':
            tier = 'T1'
        else:
            tier = 'T0'

        candidates.append({
            'sector': sym.get('sector', ''),
            'etf_code': sym.get('etf_code', ''),
            'last_price': sym.get('price', sym.get('last_price', 0)),
            'score': sym.get('total', 0),
            'abs_score': abs_score,
            'direction': direction,
            'trend_stage': stage_data,
            'resonance': resonance,
            'signal_quality': signal_quality,
            'tier': tier,
            'grade': grade,
            'signal_type': sym.get('signal_type', 'minor_signal'),
            'beta': sym.get('beta', 1.0),
            'rank': 0,
        })

    candidates.sort(key=lambda x: x['signal_quality'], reverse=True)

    if top_n > 0 and len(candidates) > top_n:
        candidates = candidates[:top_n]

    for i, c in enumerate(candidates):
        c['rank'] = i + 1

    return candidates
