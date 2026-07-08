# -*- coding: utf-8 -*-
"""ETF交易方案生成（T+1适配 + 行业轮动切换）— 通道突破策略 v2.0。

关键差异（期货→ETF）：
1. T+1 → 止损不能日内硬砍，用"跌破关键均线减仓 + 尾盘决断"
2. 无杠杆（除非两融）→ 仓位公式基于ETF实际σ（一般20-35%）
3. 无到期 → 不处理换月，但增加"行业轮动切换"逻辑
"""


def calc_confidence(symbol_score: float, tech_indicators: dict, direction: str,
                    composite_score: dict = None) -> float:
    """计算ETF置信度 (0.0 ~ 1.0)。

    适配通道突破策略 v2.0 评分体系。
    """
    is_bullish = symbol_score > 0

    if composite_score and isinstance(composite_score, dict) and 'sub_scores' in composite_score:
        ss = composite_score['sub_scores']
        dc20 = abs(ss.get('dc20', 0))
        dc55 = abs(ss.get('dc55', 0))
        bb = abs(ss.get('bb', 0))
        vol = abs(ss.get('vol', 0))

        # 通道突破策略方向：DC20(30%) + DC55(26.25%) + BB(25%) + VOL(18.75%)
        dc20_norm = min(dc20 / 48.0, 1.0)   # DC20 max ≈ 48
        dc55_norm = min(dc55 / 40.0, 1.0)   # DC55 max ≈ 40
        bb_norm = min(bb / 16.0, 1.0)        # BB max ≈ 16
        vol_norm = min(vol / 10.0, 1.0)      # VOL max ≈ 10

        four_dim_score = (0.30 * dc20_norm + 0.2625 * dc55_norm +
                          0.25 * bb_norm + 0.1875 * vol_norm)
    else:
        signal_strength = min(abs(symbol_score) / 76.0, 1.0)

        confirmations = 0
        if is_bullish:
            if tech_indicators.get('RSI14', 50) > 50: confirmations += 1
            if tech_indicators.get('MACD_DIF', 0) > 0: confirmations += 1
            if tech_indicators.get('DMI_PDI', 0) > tech_indicators.get('DMI_MDI', 0): confirmations += 1
        else:
            if tech_indicators.get('RSI14', 50) < 50: confirmations += 1
            if tech_indicators.get('MACD_DIF', 0) < 0: confirmations += 1
            if tech_indicators.get('DMI_MDI', 0) > tech_indicators.get('DMI_PDI', 0): confirmations += 1

        indicator_resonance = confirmations / 3.0
        four_dim_score = 0.50 * signal_strength + 0.50 * indicator_resonance

    confidence = four_dim_score

    # 偏离度调整
    last_price = tech_indicators.get('last_price')
    ma20 = tech_indicators.get('MA20')
    rsi = tech_indicators.get('RSI14')
    adx = tech_indicators.get('ADX')

    if last_price and ma20 and ma20 > 0:
        price_deviation_pct = (last_price - ma20) / ma20 * 100
        if is_bullish:
            if price_deviation_pct > 15:
                confidence *= 0.5
            elif price_deviation_pct > 10:
                confidence *= 0.7
        else:
            if price_deviation_pct < -15:
                confidence *= 0.5
            elif price_deviation_pct < -10:
                confidence *= 0.7

    if rsi is not None:
        if is_bullish and rsi > 75:
            confidence *= 0.7
        elif not is_bullish and rsi < 25:
            confidence *= 0.7

    if adx is not None and adx > 50:
        confidence *= 0.8

    return round(min(max(confidence, 0.0), 1.0), 3)


def calc_adaptive_target(current_price: float, atr_value: float, daily_volatility: float,
                         direction: str, tech_data: dict = None) -> float:
    """按波动率分档计算目标价（ETF版）。"""
    if daily_volatility > 0.03:
        base_pct = 0.10
    elif daily_volatility > 0.02:
        base_pct = 0.07
    elif daily_volatility > 0.015:
        base_pct = 0.05
    elif daily_volatility > 0.01:
        base_pct = 0.04
    else:
        base_pct = 0.035

    adx = (tech_data or {}).get('ADX', 25)
    if adx > 40:
        adx_mult = 1.5
    elif adx > 35:
        adx_mult = 1.3
    elif adx > 30:
        adx_mult = 1.2
    elif adx > 25:
        adx_mult = 1.1
    elif adx > 20:
        adx_mult = 1.0
    elif adx > 15:
        adx_mult = 0.9
    else:
        adx_mult = 0.8

    base_target = current_price * base_pct * adx_mult
    atr_target = atr_value * 2.5 if atr_value > 0 else 0
    base_target = max(base_target, atr_target)

    return round(current_price + base_target if direction == 'BUY' else current_price - base_target, 3)


def generate_trade_plan(symbol_data: dict, tech_data: dict = None,
                        composite_score: dict = None, sector_rank: int = 0,
                        is_sector_rotation: bool = False,
                        bull_only: bool = True) -> dict:
    """生成ETF交易方案（T+1适配版）— 适配通道突破策略 v2.1。

    默认纯多头模式：ETF只做多，空头信号返回HOLD。

    ETF特有逻辑：
    1. T+1 → 尾盘决断策略
    2. 无杠杆 → 基于σ的仓位公式
    3. 行业轮动切换 → 当Rank掉出前5触发移仓
    """
    price = symbol_data.get('price', 0) or symbol_data.get('last_price', 0)
    score = symbol_data.get('total', symbol_data.get('score', 0))
    atr = symbol_data.get('atr', 0)
    daily_vol = symbol_data.get('volatility', 0.02)

    if composite_score and isinstance(composite_score, dict) and 'direction' in composite_score:
        raw_dir = composite_score['direction']
        # 纯多头模式：空头方向→HOLD
        if bull_only and raw_dir in ('bear', 'SELL'):
            return {
                'sector': symbol_data.get('sector', ''),
                'etf_code': symbol_data.get('etf_code', ''),
                'decision': 'HOLD', 'confidence': 0, 'recommend_score': 0,
                'reason': f'纯多头模式：空头信号不生成交易计划(direction={raw_dir})',
            }
        direction = 'BUY' if raw_dir == 'bull' else 'SELL'
    else:
        if bull_only and score <= 0:
            return {
                'sector': symbol_data.get('sector', ''),
                'etf_code': symbol_data.get('etf_code', ''),
                'decision': 'HOLD', 'confidence': 0, 'recommend_score': 0,
                'reason': f'纯多头模式：非多头信号不生成交易计划(score={score:.0f})',
            }
        if score >= 20:
            direction = 'BUY'
        elif score <= -20:
            direction = 'SELL'
        else:
            return {
                'sector': symbol_data.get('sector', ''),
                'etf_code': symbol_data.get('etf_code', ''),
                'decision': 'HOLD', 'confidence': 0, 'recommend_score': 0,
                'reason': f'信号强度不足(得分={abs(score):.0f}<20)',
            }

    abs_total = abs(score)
    if abs_total < 20:
        return {
            'sector': symbol_data.get('sector', ''),
            'etf_code': symbol_data.get('etf_code', ''),
            'decision': 'HOLD', 'confidence': 0, 'recommend_score': 0,
            'reason': f'信号强度不足(总分={abs_total:.0f}<20)',
        }

    confidence = calc_confidence(score, tech_data or {}, direction, composite_score)
    if confidence < 0.4:
        return {
            'sector': symbol_data.get('sector', ''),
            'etf_code': symbol_data.get('etf_code', ''),
            'decision': 'HOLD', 'confidence': confidence, 'recommend_score': 0,
            'reason': f'置信度过低({confidence:.1%}<40%)',
        }

    # T+1止损处理
    stop_mult = 1.5 if daily_vol > 0.02 else 1.8
    stop_distance = max(atr * stop_mult, price * 0.015)

    if direction == 'BUY':
        entry = price
        stop_loss = price - stop_distance
    else:
        entry = price
        stop_loss = price + stop_distance

    target = calc_adaptive_target(price, atr, daily_vol, direction, tech_data)

    reward = abs(target - entry)
    risk = abs(entry - stop_loss)
    rr = round(reward / risk, 2) if risk > 0 else 0

    if rr < 0.8 and confidence < 0.6:
        return {
            'sector': symbol_data.get('sector', ''),
            'etf_code': symbol_data.get('etf_code', ''),
            'decision': 'HOLD', 'confidence': confidence, 'recommend_score': 0,
            'reason': f'盈亏比不足({rr}:1<0.8:1)',
        }

    recommend_score = round(confidence * 0.70 + min(rr / 3.0, 1.0) * 0.30, 3)

    # 阶梯化仓位（适配新评分体系：STRONG≥50, WATCH≥40, WEAK≥20）
    if abs_total >= 65:
        base = 2.0   # 过热减仓
        tier = 'T3'
    elif abs_total >= 50:
        base = 5.0   # STRONG
        tier = 'T2'
    elif abs_total >= 40:
        base = 3.0   # WATCH
        tier = 'T1'
    elif abs_total >= 30:
        base = 2.0   # WEAK高段
        tier = 'T0'
    else:
        base = 1.0
        tier = 'T0'

    # 波动率调整
    if daily_vol > 0.03:
        vol_mult = 0.6
    elif daily_vol > 0.02:
        vol_mult = 0.8
    elif daily_vol > 0.015:
        vol_mult = 1.0
    else:
        vol_mult = 1.2

    pos = round(min(max(base * vol_mult, 1.0), 10.0), 1)

    # 行业轮动切换逻辑
    switch_reason = None
    if is_sector_rotation and sector_rank > 5:
        switch_reason = f'行业Rank{sector_rank}掉出前5，建议切换到Rank更高的行业'

    return {
        'sector': symbol_data.get('sector', ''),
        'etf_code': symbol_data.get('etf_code', ''),
        'decision': direction,
        'entry_price': round(entry, 3),
        'target_price': target,
        'stop_loss': round(stop_loss, 3),
        'risk_reward_ratio': rr,
        'confidence': confidence,
        'recommend_score': recommend_score,
        'position_size': f'{pos}%',
        'validity': '1-3日(T+1适用，尾盘决断)',
        'tier': tier,
        'composite_total': abs_total,
        'switch_reason': switch_reason,
        'strategy_note': 'T+1止损策略：跌破MA20减半仓，尾盘确认后清仓。通道突破策略 v2.0',
    }


def generate_rotation_plan(all_plans: list, sector_ranks: list = None) -> dict:
    """生成行业轮动切换方案（保留原有逻辑）。"""
    if not all_plans:
        return {'switch_from': [], 'switch_to': [], 'rotation_note': '无活跃持仓'}

    actionable = [p for p in all_plans if p['decision'] != 'HOLD']
    switch_from = [p for p in actionable if p.get('switch_reason')]

    top_targets = []
    if sector_ranks:
        held_sectors = {p['sector'] for p in actionable}
        for r in sector_ranks[:5]:
            if r['sector'] not in held_sectors and r['rank'] <= 3:
                top_targets.append(r)

    rotation_note = ''
    if switch_from:
        rotation_note = f"建议{len(switch_from)}个行业轮动出清"
    if top_targets:
        target_names = [t['sector'] for t in top_targets]
        rotation_note += f"，关注新赛道: {', '.join(target_names)}"

    return {
        'switch_from': [p['sector'] for p in switch_from],
        'switch_to': [t['sector'] for t in top_targets],
        'rotation_note': rotation_note,
    }
