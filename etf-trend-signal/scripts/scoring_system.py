# -*- coding: utf-8 -*-
"""100分制多维打分系统 v1.1 — L1-L4四层架构（ETF优化版·通达信数据源）

权重重分配 (40/30/20/10)：L1(30→40)升权(通达信专业数据增强L1),
L2(30→30)保留, L3(25→20)降权, L4(15→10)降权。

🔴 内部分数等比例缩放原则（2026-07-03确立）：
   各层内部所有子信号的理论满分之和必须精确等于分层分数。
   当分层权重改变时，所有内部分数按相同比例缩放。
   当前内部总分-分层分映射：
   L1: 内部满分40 (ETF专属26 + 通用14) ← 原35→40缩放(40/35)
   L2: 内部满分30 (Vortex8+CCI7+Supertrend8+HMA7) ← 不变
   L3: 内部满分20 (RSI8+DMI6+新高6) ← 原25→20缩放(×0.8)
   L4: 内部满分10 (通道3+均线3+MACD1+DC55共振2+行业Rank1) ← 原14→10缩放(×0.714)

否决项扩充：折价>2%+扩大、份额连续5日流失、行业PE分位>90%。

期货→ETF的维度替换：
- L1: 去除OI三角/基差/期限/Spread，新增份额背离/IOPV/北向/融资/行业相对强度
- L2: 保留Vortex/CCI/Supertrend/HMA
- L3: 保留RSI/DMI/前高突破+行业β过滤
- L4: 保留通道/均线/MACD+行业轮动Rank
"""

from typing import Dict, Optional, List
import math

try:
    from scripts.indicators import assess_trend_maturity
except ImportError:
    from indicators import assess_trend_maturity


# ============================================================
# L1 萌芽/资金结构维度（30分）— ETF专属版
# ============================================================

def score_L1_germination(tech: dict, sym: dict, is_bull: bool,
                         etf_data: dict = None) -> dict:
    """L1 萌芽/资金结构维度打分（ETF版，满分40分，内部分数等比例缩放）。

    ETF信号（替代期货OI/基差，等比例缩放 35→40）：
    - [6分] 份额-价格背离 (替代OI三角)       ← 5→6
    - [5分] IOPV折溢价走阔 (替代基差)        ← 4→5
    - [5分] 行业相对强度 (替代期限结构)      ← 4→5
    - [5分] 北向资金5日累计                   ← 4→5
    - [3分] 融资余额斜率                      ← 3 (不变)

    保留通用信号（等比例缩放 13→15）：
    - [3分] ROC零轴
    - [3分] %b中线
    - [2分] ATR百分位
    - [4分] MA斜率                            ← 3→4
    - [2分] Higher Low / Lower High

    惩罚项：
    - [-3分] 份额连续流失
    """
    score = 0
    reasons = []
    last_price = sym.get('last_price')

    # ========== ETF专属信号（26分，原22→40/35缩放）==========

    # --- [6分] 份额-价格背离（原5→6） ---
    share_rate = tech.get('SHARE_RATE')
    share_increasing = tech.get('SHARE_INCREASING', False)
    share_decreasing = tech.get('SHARE_DECREASING', False)
    share_surge = tech.get('SHARE_SURGE', False)
    price_change_5d = tech.get('PRICE_CHANGE_5D', 0)

    if share_increasing:
        if is_bull:
            score += 6
            reasons.append(f'份额增长(真流入)(+6)')
        elif not is_bull:
            # 空头方向份额增 = 资金接盘
            score -= 3
            reasons.append(f'空头份额增长(资金接盘?)(-3)')
    elif share_decreasing:
        if not is_bull:
            score += 4
            reasons.append(f'份额流失(空方确认)(+4)')
        elif is_bull:
            score -= 3
            reasons.append(f'伪多头(份额流失)(-3)')

    if share_surge:
        score += 2
        reasons.append(f'份额突变({tech.get("SHARE_SURGE_PCT",0):.1f}%)(+2)')

    # --- [5分] IOPV折溢价 ---
    iopv_premium = tech.get('IOPV_PREMIUM', 0)
    iopv_overheat = tech.get('IOPV_OVERHEAT', False)
    iopv_panic = tech.get('IOPV_PANIC', False)

    if iopv_overheat:
        if is_bull:
            score += 5
            reasons.append(f'IOPV溢价走阔(+5)')
        else:
            score -= 2
            reasons.append(f'IOPV溢价过热(与空头矛盾)(-2)')
    elif iopv_panic:
        if not is_bull:
            score += 5
            reasons.append(f'IOPV折价加深(+5)')
        elif is_bull:
            score -= 3
            reasons.append(f'IOPV折价过深(与多头矛盾)(-3)')
    elif iopv_premium and abs(iopv_premium) < 0.5:
        score += 1
        reasons.append(f'IOPV折溢价正常(+1)')

    # --- [5分] 行业相对强度 ---
    relative_strength = tech.get('SECTOR_RELATIVE_STRENGTH', 1.0)
    if relative_strength > 1.05 and is_bull:
        score += 5
        reasons.append(f'行业相对强势(RS={relative_strength:.2f})(+5)')
    elif relative_strength < 0.95 and not is_bull:
        score += 5
        reasons.append(f'行业相对弱势(RS={relative_strength:.2f})(+5)')
    elif relative_strength > 1.1 and not is_bull:
        score -= 2
        reasons.append(f'行业强势但做空(-2)')

    # --- [5分] 北向资金 ---
    northbound_signal = tech.get('NORTHBOUND_SIGNAL', 'none')
    northbound_5d = tech.get('NORTHBOUND_5D', 0)

    if northbound_signal in ('strong_inflow', 'recent_inflow') and is_bull:
        score += 5
        reasons.append(f'北向流入(5日={northbound_5d:.0f}亿)(+5)')
    elif northbound_signal in ('strong_inflow', 'recent_inflow') and not is_bull:
        score -= 2
        reasons.append(f'北向流入但做空(-2)')
    elif northbound_signal in ('strong_outflow', 'recent_outflow') and not is_bull:
        score += 5
        reasons.append(f'北向流出(5日={northbound_5d:.0f}亿)(+5)')
    elif northbound_signal == 'inflow_reversal':
        score += 2
        reasons.append(f'北向拐点(流入反转)(+2)')

    # --- [3分] 融资余额 ---
    margin_net = tech.get('MARGIN_NET', 0)
    if margin_net > 0 and is_bull:
        score += 3
        reasons.append(f'融资净买入(+3)')
    elif margin_net < 0 and not is_bull:
        score += 2
        reasons.append(f'融资净偿还(+2)')

    # ========== 通用萌芽信号（15分，原13→40/35缩放）==========

    # --- [3分] ROC(10)零轴 ---
    roc10 = tech.get('ROC10')
    if roc10 is not None:
        if is_bull:
            if 0 < roc10 <= 3:
                score += 3; reasons.append(f'ROC10刚转正({roc10:.1f}%)(+3)')
            elif 3 < roc10 <= 8:
                score += 2; reasons.append(f'ROC10初期({roc10:.1f}%)(+2)')
        else:
            if -3 <= roc10 < 0:
                score += 3; reasons.append(f'ROC10刚转负({roc10:.1f}%)(+3)')
            elif -8 <= roc10 < -3:
                score += 2; reasons.append(f'ROC10初期下跌({roc10:.1f}%)(+2)')

    # --- [3分] %b中线 ---
    bb_pctb = tech.get('BB_PCTB')
    if bb_pctb is not None:
        if is_bull:
            if 0.45 <= bb_pctb <= 0.65:
                score += 3; reasons.append(f'%b刚过中线({bb_pctb:.2f})(+3)')
            elif 0.65 < bb_pctb <= 0.90:
                score += 2; reasons.append(f'%b偏强({bb_pctb:.2f})(+2)')
        else:
            if 0.35 <= bb_pctb <= 0.55:
                score += 3; reasons.append(f'%b刚下中线({bb_pctb:.2f})(+3)')
            elif 0.15 <= bb_pctb < 0.35:
                score += 2; reasons.append(f'%b偏弱({bb_pctb:.2f})(+2)')

    # --- [2分] ATR百分位 ---
    atr_pct = tech.get('ATR_PERCENTILE')
    if atr_pct is not None:
        if 15 <= atr_pct <= 35:
            score += 2; reasons.append(f'ATR脱低位({atr_pct:.0f}%)(+2)')
        elif atr_pct < 15:
            score += 1; reasons.append(f'ATR极度压缩({atr_pct:.0f}%)(+1)')

    # --- [4分] MA斜率（原3→4）---
    ma_slope = tech.get('MA20_SLOPE')
    if ma_slope is not None:
        if is_bull:
            if -0.5 <= ma_slope <= 0.5:
                score += 4; reasons.append(f'MA20转平({ma_slope:.2f})(+4)')
            elif 0.5 < ma_slope <= 2.0:
                score += 4; reasons.append(f'MA20微翘({ma_slope:.2f})(+4)')
            elif ma_slope > 2.0:
                score += 1; reasons.append(f'MA20已陡({ma_slope:.2f})(+1)')
        else:
            if -0.5 <= ma_slope <= 0.5:
                score += 4; reasons.append(f'MA20转平({ma_slope:.2f})(+4)')
            elif -2.0 <= ma_slope < -0.5:
                score += 4; reasons.append(f'MA20微降({ma_slope:.2f})(+4)')
            elif ma_slope < -2.0:
                score += 1; reasons.append(f'MA20已陡降({ma_slope:.2f})(+1)')

    # --- [2分] Higher Low / Lower High ---
    higher_low = tech.get('HIGHER_LOW')
    lower_high = tech.get('LOWER_HIGH')
    if is_bull and higher_low:
        score += 2; reasons.append('Higher Low形成(+2)')
    elif not is_bull and lower_high:
        score += 2; reasons.append('Lower High形成(+2)')

    # ========== 惩罚项 ==========
    # 份额连续流失
    share_decreasing = tech.get('SHARE_DECREASING', False)
    if share_decreasing and not is_bull:
        pass  # 空头方向份额流失=正常
    elif share_decreasing and is_bull:
        score -= 3; reasons.append('多头方向份额流失(-3)')

    return {'score': max(0, min(40, score)), 'reasons': reasons}


# ============================================================
# L2 量价领先维度（30分）
# ============================================================

def score_L2_volume_price(tech: dict, sym: dict, is_bull: bool) -> dict:
    """L2 量价领先维度打分（ETF版满分30分，保留commodity逻辑）。"""
    score = 0
    reasons = []

    # --- [8分] Vortex ---
    vi_plus = tech.get('VI_PLUS')
    vi_minus = tech.get('VI_MINUS')
    if vi_plus is not None and vi_minus is not None:
        if is_bull and vi_plus > vi_minus:
            score += 8; reasons.append(f'Vortex多头(VI+={vi_plus:.3f}>VI-={vi_minus:.3f})(+8)')
        elif not is_bull and vi_minus > vi_plus:
            score += 8; reasons.append(f'Vortex空头(VI-={vi_minus:.3f}>VI+={vi_plus:.3f})(+8)')

    # --- [7分] CCI ---
    cci = tech.get('CCI20')
    if cci is not None:
        if is_bull and 100 <= cci <= 200:
            score += 7; reasons.append(f'CCI破+100({cci:.0f})(+7)')
        elif is_bull and cci > 200:
            score += 2; reasons.append(f'CCI极度超买({cci:.0f})(+2)')
        elif not is_bull and -200 <= cci <= -100:
            score += 7; reasons.append(f'CCI破-100({cci:.0f})(+7)')
        elif not is_bull and cci < -200:
            score += 2; reasons.append(f'CCI极度超卖({cci:.0f})(+2)')

    # --- [8分] Supertrend ---
    st_dir = tech.get('SUPERTREND_DIR')
    if st_dir is not None:
        if is_bull and st_dir == 1:
            score += 8; reasons.append(f'Supertrend多头(+8)')
        elif not is_bull and st_dir == -1:
            score += 8; reasons.append(f'Supertrend空头(+8)')

    # --- [7分] HMA交叉 ---
    hma_cross = tech.get('HMA_CROSS')
    if hma_cross:
        if is_bull and hma_cross == 'bull':
            score += 7; reasons.append(f'HMA多头交叉(+7)')
        elif not is_bull and hma_cross == 'bear':
            score += 7; reasons.append(f'HMA空头交叉(+7)')

    return {'score': max(0, min(30, score)), 'reasons': reasons}


# ============================================================
# L3 价格结构维度（20分，内部分数 8+6+6=20，等比例缩放 25→20 ×0.8）
# ============================================================

def score_L3_structure(tech: dict, is_bull: bool) -> dict:
    """L3 价格结构维度打分（ETF版满分20分，RSI分段线性映射）。

    - [8分] RSI健康区间：分段线性（RSI=41得3分/50得7分/60得8分）
    - [6分] DMI方向确认
    - [6分] 前高/前低突破
    """
    score = 0
    reasons = []

    rsi = tech.get('RSI14')
    pdi = tech.get('DMI_PDI')
    mdi = tech.get('DMI_MDI')
    new_high_60 = tech.get('NEW_HIGH_60', False)
    new_low_60 = tech.get('NEW_LOW_60', False)

    # [8分] RSI分段线性映射（取代原区间恒分）
    #  多头：RSI=30→+1, 40→+4, 50→+7, 60→+8, 65→+7, 70→+5, 75→+3
    #  空头：RSI=60→+1, 55→+4, 45→+7, 35→+8, 30→+7, 25→+5, 20→+3
    if rsi is not None:
        if is_bull:
            if 30 <= rsi <= 40:
                # 30→+1, 40→+4: slope = (4-1)/(40-30) = 0.3
                rsi_score = 1 + (rsi - 30) * 0.3
            elif 40 < rsi <= 50:
                # 40→+4, 50→+7: slope = 0.3
                rsi_score = 4 + (rsi - 40) * 0.3
            elif 50 < rsi <= 60:
                # 50→+7, 60→+8: slope = 0.1
                rsi_score = 7 + (rsi - 50) * 0.1
            elif 60 < rsi <= 65:
                # 60→+8, 65→+7: slope = -0.2
                rsi_score = 8 + (rsi - 60) * -0.2
            elif 65 < rsi <= 75:
                # 65→+7, 75→+3: slope = -0.4
                rsi_score = 7 + (rsi - 65) * -0.4
            else:
                rsi_score = 0 if rsi < 30 else 3
            rsi_score = max(0, min(8, round(rsi_score)))
            if rsi_score > 0:
                score += rsi_score; reasons.append(f'RSI={rsi:.0f}→+{rsi_score}')
        else:
            if 20 <= rsi <= 35:
                # 35→+8, 20→+3: slope = (8-3)/(35-20) = 0.333
                rsi_score = 3 + (35 - rsi) * 0.333
            elif 35 < rsi <= 45:
                # 35→+8, 45→+7: slope = -0.1
                rsi_score = 8 + (rsi - 35) * -0.1
            elif 45 < rsi <= 55:
                # 45→+7, 55→+4: slope = -0.3
                rsi_score = 7 + (rsi - 45) * -0.3
            elif 55 < rsi <= 60:
                # 55→+4, 60→+1: slope = -0.6
                rsi_score = 4 + (rsi - 55) * -0.6
            else:
                rsi_score = 0 if rsi > 60 else 3
            rsi_score = max(0, min(8, round(rsi_score)))
            if rsi_score > 0:
                score += rsi_score; reasons.append(f'RSI={rsi:.0f}→+{rsi_score}')

    # [6分] DMI方向 (8→6)
    if pdi is not None and mdi is not None:
        if (is_bull and pdi > mdi) or (not is_bull and mdi > pdi):
            score += 6; reasons.append(f'DMI方向确认(+6)')

    # [6分] 前高/前低突破 (7→6)
    if is_bull and new_high_60:
        score += 6; reasons.append(f'突破60日新高(+6)')
    elif not is_bull and new_low_60:
        score += 6; reasons.append(f'跌破60日新低(+6)')

    return {'score': max(0, min(20, score)), 'reasons': reasons}


# ============================================================
# L4 确认维度（10分，内部分数 3+3+1+2+1=10，等比例缩放 14→10 ×0.714）
# ============================================================

def score_L4_confirmation(tech: dict, sym: dict, is_bull: bool,
                           days_since_breakout: int = 0,
                           sector_rank: int = 0) -> dict:
    """L4 确认维度打分（ETF版满分10分，内部分数等比例缩放下界=10）。

    - [3分] 通道突破（带衰减）     ← 4→3
    - [3分] 均线排列（带衰减）     ← 4→3
    - [1分] MACD确认               ← 2→1
    - [2分] DC55共振               ← 2(不变)
    - [1分] 行业轮动Rank前5        ← 2→1
    """
    score = 0
    reasons = []
    last_price = sym.get('last_price')

    decay = _calc_time_decay(days_since_breakout)

    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc55_trend = tech.get('DC55_TREND')

    if not last_price or not dc_upper or not dc_lower:
        return {'score': 0, 'reasons': ['通道数据不足'], 'decay': decay}

    # --- [3分] 通道突破（带衰减，原4→3）---
    breakout_score = 0
    if is_bull:
        if last_price > dc_upper:
            breakout_score = 3; reasons.append(f'突破DC20上轨(+3×{decay:.0%})')
        elif last_price > dc_upper * 0.99:
            breakout_score = 2; reasons.append(f'接近DC20上轨(+2)')
    else:
        if last_price < dc_lower:
            breakout_score = 3; reasons.append(f'跌破DC20下轨(+3×{decay:.0%})')
        elif last_price < dc_lower * 1.01:
            breakout_score = 2; reasons.append(f'接近DC20下轨(+2)')
    if breakout_score >= 3:
        breakout_score = int(breakout_score * decay)
    score += breakout_score

    # --- [3分] 均线排列（原4→3）---
    ma5 = tech.get('MA5')
    ma10 = tech.get('MA10')
    ma20 = tech.get('MA20')
    ma_score = 0
    if last_price and ma20:
        if is_bull:
            if ma5 and ma10 and ma5 > ma10 > ma20 and last_price > ma20:
                ma_score = 3; reasons.append(f'均线多头排列(+3×{decay:.0%})')
            elif last_price > ma20:
                ma_score = 1; reasons.append(f'价格>MA20(+1)')
        else:
            if ma5 and ma10 and ma5 < ma10 < ma20 and last_price < ma20:
                ma_score = 3; reasons.append(f'均线空头排列(+3×{decay:.0%})')
            elif last_price < ma20:
                ma_score = 1; reasons.append(f'价格<MA20(+1)')
    if ma_score >= 3:
        ma_score = int(ma_score * decay)
    score += ma_score

    # --- [1分] MACD确认（原2→1）---
    macd_dif = tech.get('MACD_DIF')
    macd_dea = tech.get('MACD_DEA')
    if macd_dif is not None:
        if is_bull:
            if macd_dif > 0 and (macd_dea is None or macd_dif > macd_dea):
                score += 1; reasons.append(f'MACD多头(+1)')
            elif macd_dif > 0:
                score += 1; reasons.append(f'MACD零轴上(+1)')
        else:
            if macd_dif < 0 and (macd_dea is None or macd_dif < macd_dea):
                score += 1; reasons.append(f'MACD空头(+1)')
            elif macd_dif < 0:
                score += 1; reasons.append(f'MACD零轴下(+1)')

    # --- [2分] DC55共振 ---
    if dc55_trend:
        if (is_bull and dc55_trend == 'up') or (not is_bull and dc55_trend == 'down'):
            score += 2; reasons.append(f'DC55同步扩张(+2)')

    # --- [1分] 行业轮动Rank加分（原2→1）---
    if sector_rank > 0 and sector_rank <= 5:
        score += 1; reasons.append(f'行业轮动Rank前5(+1)')

    return {'score': max(0, min(10, score)), 'reasons': reasons, 'decay': decay}


# ============================================================
# 否决维度（-20分）
# ============================================================

def score_veto_dimension(tech: dict, sym: dict, is_bull: bool,
                         etf_data: dict = None,
                         sector_rank: int = 0) -> dict:
    """否决维度打分（ETF版，扩充否决项）。

    期货版保留：
    - ADX<15震荡
    - RSI极端
    - CCI极端
    - 偏离MA20

    ETF新增：
    - 折价>2%且扩大
    - 份额连续5日流失
    - IOPV溢价过热
    """
    score = 0
    reasons = []

    adx = tech.get('ADX')
    bb_squeeze = tech.get('BB_SQUEEZE', False)
    rsi = tech.get('RSI14')
    last_price = sym.get('last_price')
    ma20 = tech.get('MA20')
    vol_ratio = tech.get('VOL_RATIO')

    # ADX分层
    if adx is not None and adx < 15:
        if bb_squeeze:
            score -= 6; reasons.append(f'ADX={adx:.0f}+Squeeze纯震荡(-6)')
        else:
            score -= 3; reasons.append(f'ADX={adx:.0f}趋势力度不足(-3)')

    # RSI极端
    if rsi is not None:
        if is_bull and rsi > 80:
            score -= 6; reasons.append(f'RSI={rsi:.0f}严重超买(-6)')
        elif not is_bull and rsi < 20:
            score -= 6; reasons.append(f'RSI={rsi:.0f}严重超卖(-6)')

    # CCI极端
    cci = tech.get('CCI20')
    if cci is not None:
        if is_bull and cci > 200:
            score -= 5; reasons.append(f'CCI={cci:.0f}极端超买(-5)')
        elif not is_bull and cci < -200:
            score -= 5; reasons.append(f'CCI={cci:.0f}极端超卖(-5)')

    # 偏离MA20
    if last_price and ma20 and ma20 > 0:
        deviation = abs((last_price - ma20) / ma20 * 100)
        if deviation > 15:
            score -= 4; reasons.append(f'偏离MA20={deviation:.1f}%(-4)')
        elif deviation > 10:
            score -= 2; reasons.append(f'偏离MA20={deviation:.1f}%(-2)')

    # ===== ETF新增否决项 =====

    # 成交额萎缩（比成交量更准确的资金指标）
    vol_ratio = tech.get('VOL_RATIO')
    if vol_ratio is not None and vol_ratio < 0.5:
        score -= 4; reasons.append(f'严重缩量({vol_ratio:.1f}x)(-4)')
    amount_ratio = tech.get('AMOUNT_RATIO')
    if amount_ratio is not None and amount_ratio < 0.4:
        score -= 3; reasons.append(f'成交额萎缩({amount_ratio:.1f}x)(-3)')

    # ===== ETF专属否决 =====

    # 折价>2%且扩大（非恐慌而是结构性流出的预警）
    iopv_premium = tech.get('IOPV_PREMIUM', 0)
    if iopv_premium < -2.0 and tech.get('IOPV_PANIC', False):
        if is_bull:
            score -= 4; reasons.append(f'IOPV折价>{abs(iopv_premium):.1f}%(与多头矛盾)(-4)')

    # IOPV溢价过热（情绪过热，追高风险）
    iopv_overheat = tech.get('IOPV_OVERHEAT', False)
    if iopv_overheat and is_bull:
        score -= 3; reasons.append(f'IOPV溢价过热(追高风险)(-3)')

    # 份额持续流失
    share_decreasing = tech.get('SHARE_DECREASING', False)
    if share_decreasing and is_bull:
        score -= 3; reasons.append(f'份额流失(资金出逃)(-3)')

    # ===== 硬约束移入否决（原_determine_direction撤销的约束）=====
    last_price = sym.get('last_price')
    ma20 = tech.get('MA20')

    # 原硬约束: 价格<MA20-2% → 否决-2
    if last_price and ma20 and ma20 > 0:
        if (ma20 - last_price) / ma20 > 0.02 and is_bull:
            score -= 2; reasons.append(f'价格低于MA20超过2%(否决-2)')

    # 原硬约束: Supertrend空头+价格<MA20+ADX>20 → 否决-4
    st_dir = tech.get('SUPERTREND_DIR')
    adx = tech.get('ADX')
    if st_dir == -1 and last_price and ma20 and last_price < ma20 and adx and adx > 20 and is_bull:
        score -= 4; reasons.append(f'ST空头+价<MA20+ADX>20(否决-4)')

    return {'score': max(-20, min(0, score)), 'reasons': reasons}


# ============================================================
# 时间衰减函数（ETF版：趋势周期更长，衰减更缓）
# ============================================================

def _calc_time_decay(days: int) -> float:
    """ETF专属衰减曲线：突破后有效窗口更长。

    期货版：0天=100% → 3天=90% → 7天=70% → 14天=50% → 20天+=30%
    ETF版： 0天=100% → 5天=95% → 10天=85% → 20天=65% → 30天=50% → 40天+=30%

    ETF趋势持续时间是期货2-3倍，衰减速度是期货的60%。
    """
    if days <= 0:
        return 1.0
    elif days <= 5:
        return 1.0 - days * 0.01     # 5天内衰减5%
    elif days <= 10:
        return 0.95 - (days - 5) * 0.02  # 5→10天衰减到85%
    elif days <= 20:
        return 0.85 - (days - 10) * 0.02  # 10→20天衰减到65%
    elif days <= 30:
        return 0.65 - (days - 20) * 0.015  # 20→30天衰减到50%
    elif days <= 40:
        return 0.50 - (days - 30) * 0.02   # 30→40天衰减到30%
    else:
        return 0.3


def estimate_days_since_breakout(tech: dict, is_bull: bool) -> int:
    dc_pos = tech.get('DC_POS')
    deviation = tech.get('PRICE_DEVIATION_PCT', 0)
    last_price = tech.get('last_price')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')

    is_breakout = False
    if last_price and dc_upper and dc_lower:
        if is_bull and last_price > dc_upper:
            is_breakout = True
        elif not is_bull and last_price < dc_lower:
            is_breakout = True

    if not is_breakout:
        return 0

    if abs(deviation) > 12:
        return 18
    elif abs(deviation) > 8:
        return 12
    elif abs(deviation) > 5:
        return 7
    elif abs(deviation) > 3:
        return 4
    elif abs(deviation) > 1:
        return 2
    return 1


# ============================================================
# 方向判断
# ============================================================

def _determine_direction(tech: dict, sym: dict, score_direction: int = 0) -> bool:
    """基于技术指标综合判断方向（ETF优化版，硬约束放宽）。

    🔴 硬约束（原4项减为2项，其余改为否决）：
    1. MA空头排列（MA5<MA10<MA20）→ 强制空头
    2. MACD+DMI+ROC+BB四指标全空头共振 → 强制空头

    ⚠️ 已撤销为否决的约束：
    - 原"价格<MA20-2%" → 改为否决 -2（不再强制）
    - 原"ST空头+价格<MA20" → 改为否决 -4（不再强制）
    """
    ma5 = tech.get('MA5')
    ma10 = tech.get('MA10')
    ma20 = tech.get('MA20')
    last_price = sym.get('last_price')
    macd_dif = tech.get('MACD_DIF')
    rsi = tech.get('RSI14')
    pdi = tech.get('DMI_PDI')
    mdi = tech.get('DMI_MDI')
    vi_plus = tech.get('VI_PLUS')
    vi_minus = tech.get('VI_MINUS')
    st_dir = tech.get('SUPERTREND_DIR')
    roc10 = tech.get('ROC10')

    # ===== 硬约束（保持2项，其余移入否决）=====

    # 硬约束1: MA空头排列（MA5<MA10<MA20）→ 强制空头
    if ma5 and ma10 and ma20:
        if ma5 < ma10 < ma20:
            return False

    # 硬约束2: MACD+DMI+ROC+BB四指标全空头共振 → 强制空头
    bb_middle = tech.get('BB_MIDDLE')
    if (macd_dif is not None and macd_dif < 0 and
        pdi is not None and mdi is not None and pdi < mdi and
        roc10 is not None and roc10 < 0 and
        bb_middle and last_price and last_price < bb_middle):
        return False

    # ===== 软约束投票（保持不变）=====
    votes_bull = 0
    votes_bear = 0

    if macd_dif is not None:
        if macd_dif > 0: votes_bull += 2
        else: votes_bear += 2
    if rsi is not None:
        if rsi > 55: votes_bull += 1
        elif rsi < 45: votes_bear += 1
    if pdi is not None and mdi is not None:
        if pdi > mdi: votes_bull += 2
        else: votes_bear += 2
    if last_price and ma20 and ma20 > 0:
        if last_price > ma20 * 1.005: votes_bull += 1
        elif last_price < ma20 * 0.995: votes_bear += 1
    if vi_plus is not None and vi_minus is not None:
        if vi_plus > vi_minus: votes_bull += 1
        else: votes_bear += 1
    if st_dir is not None:
        if st_dir == 1: votes_bull += 1
        elif st_dir == -1: votes_bear += 1
    if roc10 is not None:
        if roc10 > 0: votes_bull += 1
        else: votes_bear += 1

    total_votes = votes_bull + votes_bear
    if total_votes == 0:
        return score_direction > 0

    bull_ratio = votes_bull / total_votes
    if bull_ratio >= 0.6:
        return True
    elif bull_ratio <= 0.4:
        return False
    else:
        if last_price and ma20 and last_price > ma20:
            bb_middle = tech.get('BB_MIDDLE')
            if bb_middle and last_price > bb_middle:
                return True
        return score_direction > 0


# ============================================================
# 综合打分入口
# ============================================================

def calculate_composite_score(tech: dict, sym: dict, score_direction: int = 0,
                               kline_closes: list = None,
                               term_basis: dict = None,
                               etf_data: dict = None,
                               sector_rank: int = 0) -> dict:
    """计算100分制综合得分（ETF优化版 L1-L4四层架构）。

    ETF专属参数：
        etf_data: 份额/折溢价/北向/融资数据
        sector_rank: 行业轮动Rank（1-31）
    """
    is_bull = _determine_direction(tech, sym, score_direction)

    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    last_price = sym.get('last_price')
    if dc_upper and dc_lower and last_price and (dc_upper - dc_lower) > 0:
        if is_bull:
            tech['DC_POS'] = (last_price - dc_lower) / (dc_upper - dc_lower)
        else:
            tech['DC_POS'] = (dc_upper - last_price) / (dc_upper - dc_lower)

    ma20 = tech.get('MA20')
    if last_price and ma20 and ma20 > 0:
        tech['PRICE_DEVIATION_PCT'] = (last_price - ma20) / ma20 * 100
    tech['last_price'] = last_price

    days_since = estimate_days_since_breakout(tech, is_bull)

    # L1-L4 四层打分
    l1_raw = score_L1_germination(tech, sym, is_bull, etf_data)
    l2_raw = score_L2_volume_price(tech, sym, is_bull)
    l3_raw = score_L3_structure(tech, is_bull)
    l4_raw = score_L4_confirmation(tech, sym, is_bull, days_since, sector_rank)
    veto = score_veto_dimension(tech, sym, is_bull, etf_data)

    # 趋势成熟度调整
    maturity = assess_trend_maturity(tech, sym, 1 if is_bull else -1)
    stage = maturity.get('stage', 'unknown')

    if stage == 'exhausted':
        l4_raw['score'] = int(l4_raw['score'] * 0.5)
        veto['score'] -= 3
        veto['reasons'].append(f'趋势衰竭(成熟度={stage})(-3)')
    elif stage == 'reversal':
        veto['score'] -= 6
        veto['reasons'].append(f'趋势反转风险(成熟度={stage})(-6)')

    # ETF版权重：40/30/20/10（内部分数已等比例缩放确保内部总分=分层分）
    WL1, WL2, WL3, WL4 = 40, 30, 20, 10
    l1_scaled = round(min(l1_raw['score'], 40) * WL1 / 40.0)
    l2_scaled = round(l2_raw['score'] * WL2 / 30.0)
    l3_scaled = round(l3_raw['score'] * WL3 / 20.0)
    l4_scaled = round(l4_raw['score'] * WL4 / 10.0)

    l1 = {'score': l1_scaled, 'raw_score': l1_raw['score'], 'reasons': l1_raw['reasons']}
    l2 = {'score': l2_scaled, 'raw_score': l2_raw['score'], 'reasons': l2_raw['reasons']}
    l3 = {'score': l3_scaled, 'raw_score': l3_raw['score'], 'reasons': l3_raw['reasons']}
    l4 = {'score': l4_scaled, 'raw_score': l4_raw['score'], 'reasons': l4_raw['reasons']}

    total = l1_scaled + l2_scaled + l3_scaled + l4_scaled + veto['score']
    total = max(0, min(100, total))

    if total >= 75:
        grade = 'STRONG'
    elif total >= 60:
        grade = 'WATCH'
    elif total >= 40:
        grade = 'WEAK'
    else:
        grade = 'NOISE'

    all_reasons = []
    all_reasons.extend([f'[L1萌芽] {r}' for r in l1['reasons']])
    all_reasons.extend([f'[L2量价] {r}' for r in l2['reasons']])
    all_reasons.extend([f'[L3结构] {r}' for r in l3['reasons']])
    all_reasons.extend([f'[L4确认] {r}' for r in l4['reasons']])
    all_reasons.extend([f'[否决] {r}' for r in veto['reasons']])
    if stage != 'unknown' and stage != 'trending':
        all_reasons.append(f'[成熟度] {stage}')

    return {
        'total': total,
        'grade': grade,
        'maturity': {'stage': stage},
        'direction': 'BUY' if is_bull else 'SELL',
        'days_since_breakout': days_since,
        'decay_factor': l4.get('decay', 1.0),
        'dimensions': {
            'L1_germination': l1,
            'L2_volume_price': l2,
            'L3_structure': l3,
            'L4_confirmation': l4,
            'veto': veto,
        },
        'reasons': all_reasons,
        'L1_score': l1['score'],
        'L2_score': l2['score'],
        'L3_score': l3['score'],
        'L4_score': l4['score'],
        'veto_score': veto['score'],
    }
