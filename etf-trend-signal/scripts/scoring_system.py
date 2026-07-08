# -*- coding: utf-8 -*-
"""通道突破策略评分系统 v2.0 — Layer A唐奇安通道 + Layer B布林带 + 成交量确认

基于 signal_layer_business_logic.md 的业务逻辑，全面替换旧的L1-L4打分系统。

评分架构：
  Layer A: 唐奇安通道 (75%权重)
    A1: DC20短期突破 (占75%中的40% ≈ 总分30%)
    A2: DC55中期趋势 (占75%中的35% ≈ 总分26.25%)
  Layer B: 布林带确认 (25%权重)
    B1: 带宽扩张/收缩 (~10%)
    B2: 挤压检测 (~5%)
    B3: %b位置 (~10%)
  Volume: 成交量确认 (独立加减分, -3 ~ ±10)

  total_score = dc20_score + dc55_score + bb_score + volume_score
  典型范围: [-76, +76]

  方向:     bull  if total > 0, bear if total < 0, neutral if total = 0
  等级:     STRONG if |total| >= 50, WATCH if >= 40, WEAK if >= 20, NOISE if < 20
  信号类型: channel_breakout / trend_confirmation / bb_squeeze_prebreakout / minor_signal

🔴 评分单源原则（继承L1-L4规则）：
  所有评分逻辑必须且只能通过本文件实现。任何其他脚本不得内联评分逻辑。
"""

from typing import Dict, Optional
import math

try:
    from scripts.config import CHANNEL_BREAKOUT_CONFIG, SIGNAL_GRADE_THRESHOLDS
except ImportError:
    from config import CHANNEL_BREAKOUT_CONFIG, SIGNAL_GRADE_THRESHOLDS


# ============================================================
# 取配置辅助函数
# ============================================================

def _cfg(*keys, default=None):
    """从 CHANNEL_BREAKOUT_CONFIG 中安全取值。"""
    val = CHANNEL_BREAKOUT_CONFIG
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
    return val if val is not None else default


# ============================================================
# Layer A1: DC20 短期突破评分
# ============================================================

def score_dc20(tech: dict, sym: dict) -> dict:
    """DC20短期突破评分。

    前提：只对 dc20_break == "up" / "down" 的品种计算。
    无突破时 dc20_score = 0.0。

    返回:
        score: float  评分结果
        break_detected: str  "up" / "down" / "none"
        reasons: list[str]
    """
    result = {
        'score': 0.0,
        'break_detected': 'none',
        'break_pct': 0.0,
        'position': 0.5,
        'reasons': [],
    }

    last_price = sym.get('last_price')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc_pos = tech.get('DC_POS', 0.5)
    adx = tech.get('ADX')

    if not last_price or not dc_upper or not dc_lower:
        return result

    # ── 检测突破方向 ──
    if last_price > dc_upper:
        result['break_detected'] = 'up'
        result['break_pct'] = (last_price / dc_upper - 1) * 100
    elif last_price < dc_lower:
        result['break_detected'] = 'down'
        result['break_pct'] = (dc_lower / last_price - 1) * 100
    else:
        # 无突破
        return result

    is_up = result['break_detected'] == 'up'
    score = 0.0
    reasons = []

    # ── 基础分: ±30.0 ──
    base = _cfg('dc20', 'break_base_score', default=30.0)
    score += base if is_up else -base
    reasons.append(f'DC20突破基础分({"+" if is_up else "-"}{base})')

    # ── 突破幅度确认 ──
    bp = result['break_pct']
    strong_pct = _cfg('dc20', 'break_strong_pct', default=1.0)
    strong_bonus = _cfg('dc20', 'break_strong_bonus', default=10.0)
    moderate_pct = _cfg('dc20', 'break_moderate_pct', default=0.3)
    moderate_bonus = _cfg('dc20', 'break_moderate_bonus', default=5.0)

    if bp > strong_pct and is_up:
        score += strong_bonus
        reasons.append(f'大幅突破({bp:.1f}%)(+{strong_bonus})')
    elif bp > moderate_pct and is_up:
        score += moderate_bonus
        reasons.append(f'中等突破({bp:.1f}%)(+{moderate_bonus})')
    elif bp > strong_pct and not is_up:
        score -= strong_bonus
        reasons.append(f'大幅突破({bp:.1f}%)(-{strong_bonus})')
    elif bp > moderate_pct and not is_up:
        score -= moderate_bonus
        reasons.append(f'中等突破({bp:.1f}%)(-{moderate_bonus})')

    # ── DC20位置确认 ──
    upper_th = _cfg('dc20', 'pos_upper_threshold', default=0.7)
    upper_bonus = _cfg('dc20', 'pos_upper_bonus', default=5.0)
    lower_th = _cfg('dc20', 'pos_lower_threshold', default=0.3)

    if dc_pos > upper_th and is_up:
        score += upper_bonus
        reasons.append(f'DC20上轨区(DC_POS={dc_pos:.2f})(+{upper_bonus})')
    elif dc_pos < lower_th and not is_up:
        score -= upper_bonus  # 对称: -5.0
        reasons.append(f'DC20下轨区(DC_POS={dc_pos:.2f})(-{upper_bonus})')

    # ── ADX趋势评估 ──
    exhaustion_th = _cfg('adx', 'exhaustion_threshold', default=60)
    exhaustion_penalty = _cfg('adx', 'exhaustion_penalty', default=5.0)
    trend_th = _cfg('adx', 'trend_threshold', default=25)
    trend_bonus = _cfg('adx', 'trend_bonus', default=3.0)

    if adx is not None:
        if adx > exhaustion_th:
            if is_up:
                score -= exhaustion_penalty
                reasons.append(f'ADX={adx:.0f}衰竭警告(-{exhaustion_penalty})')
            else:
                score += exhaustion_penalty
                reasons.append(f'ADX={adx:.0f}空头衰竭(+{exhaustion_penalty})')
        elif adx >= trend_th:
            if is_up:
                score += trend_bonus
                reasons.append(f'ADX={adx:.0f}趋势健康(+{trend_bonus})')
            else:
                score -= trend_bonus
                reasons.append(f'ADX={adx:.0f}趋势健康(-{trend_bonus})')

    result['score'] = round(score, 1)
    result['position'] = dc_pos
    result['reasons'] = reasons
    return result


# ============================================================
# Layer A2: DC55 中期趋势评分（6级阶梯 + 趋势方向）
# ============================================================

def score_dc55(tech: dict, sym: dict) -> dict:
    """DC55中期趋势评分。

    第一步：6级阶梯评分匹配 DC55_POS
    第二步：趋势方向确认（方向一致/背离调整）

    返回:
        total: float            position_score + trend_score
        position_score: float   阶梯评分结果
        trend_score: float      趋势方向调整分
        position_label: str     位置标签
        trend: str              "up"/"down"/"flat"
        dc55_pos: float
        reasons: list[str]
    """
    result = {
        'total': 0.0,
        'position_score': 0.0,
        'trend_score': 0.0,
        'position_label': 'mid',
        'trend': 'flat',
        'dc55_pos': None,
        'reasons': [],
    }

    last_price = sym.get('last_price')
    dc55_upper = tech.get('DC55_UPPER')
    dc55_lower = tech.get('DC55_LOWER')
    dc55_trend = tech.get('DC55_TREND', 'flat')

    if not last_price or not dc55_upper or not dc55_lower:
        return result

    # ── 计算 DC55_POS ──
    dc55_range = dc55_upper - dc55_lower
    if dc55_range <= 0:
        return result
    dc55_pos = (last_price - dc55_lower) / dc55_range
    dc55_pos = max(0.0, min(1.0, dc55_pos))
    result['dc55_pos'] = dc55_pos
    result['trend'] = dc55_trend

    # ── 第一步：6级阶梯评分 ──
    pos_cfg = _cfg('dc55_position', default={})
    position_score = 0.0
    position_label = 'mid'

    if dc55_pos > pos_cfg.get('extreme_upper_threshold', 0.85):
        position_score = pos_cfg.get('extreme_upper_score', 25.0)
        position_label = 'extreme_upper'
    elif dc55_pos > pos_cfg.get('upper_threshold', 0.70):
        position_score = pos_cfg.get('upper_score', 15.0)
        position_label = 'upper'
    elif dc55_pos > 0.50:
        position_score = pos_cfg.get('mid_upper_score', 5.0)
        position_label = 'mid_upper'
    elif dc55_pos < pos_cfg.get('extreme_lower_threshold', 0.15):
        position_score = pos_cfg.get('extreme_lower_score', -25.0)
        position_label = 'extreme_lower'
    elif dc55_pos < pos_cfg.get('lower_threshold', 0.30):
        position_score = pos_cfg.get('lower_score', -15.0)
        position_label = 'lower'
    elif dc55_pos < 0.50:
        position_score = pos_cfg.get('mid_lower_score', -5.0)
        position_label = 'mid_lower'

    result['position_score'] = position_score
    result['position_label'] = position_label
    reasons = [f'DC55位置{position_label}(DC55_POS={dc55_pos:.3f})({position_score:+.0f})']

    # ── 第二步：趋势方向确认 ──
    trend_base = _cfg('dc55_trend', 'trend_base_score', default=10.0)
    alignment_bonus = _cfg('dc55_trend', 'trend_alignment_bonus', default=5.0)
    divergence_penalty = _cfg('dc55_trend', 'divergence_penalty', default=10.0)
    trend_score = 0.0

    if dc55_trend == 'up':
        if position_score >= 0:
            trend_score = trend_base + alignment_bonus  # +15
            reasons.append(f'DC55趋势向上+位置看多(方向一致)(+{trend_base+alignment_bonus})')
        else:
            trend_score = trend_base - divergence_penalty  # 0
            reasons.append(f'DC55趋势向上但位置看空(方向背离)(+0)')
    elif dc55_trend == 'down':
        if position_score <= 0:
            trend_score = -(trend_base + alignment_bonus)  # -15
            reasons.append(f'DC55趋势向下+位置看空(方向一致)(-{trend_base+alignment_bonus})')
        else:
            trend_score = -(trend_base + divergence_penalty)  # -20
            reasons.append(f'DC55趋势向下但位置看多(方向背离)(-{trend_base+divergence_penalty})')
    else:
        # flat: 不做方向调整
        reasons.append('DC55趋势平缓(无方向调整)')

    result['trend_score'] = trend_score
    result['total'] = round(position_score + trend_score, 1)
    result['reasons'] = reasons
    return result


# ============================================================
# Layer B: 布林带确认评分
# ============================================================

def score_bb(tech: dict, sym: dict, dc_score: float) -> dict:
    """布林带确认评分 (B1带宽 + B2挤压 + B3 %b位置 + DC-BB一致性)。

    Args:
        dc_score: DC总分 (dc20 + dc55)，用于方向跟随。

    返回:
        total: float  布林带总分
        b1_width: float / b2_squeeze: float / b3_position: float / consistency: float
        bb_width_pct: float / bb_squeeze: bool / bb_pos: float
        reasons: list[str]
    """
    result = {
        'total': 0.0,
        'b1_width': 0.0,
        'b2_squeeze': 0.0,
        'b3_position': 0.0,
        'consistency': 0.0,
        'bb_width_pct': None,
        'bb_squeeze': None,
        'bb_pos': None,
        'reasons': [],
    }

    bb_width_pct = tech.get('BB_WIDTH_PCT')
    bb_squeeze = tech.get('BB_SQUEEZE', False)
    bb_pos = tech.get('BB_PCTB')

    result['bb_width_pct'] = bb_width_pct
    result['bb_squeeze'] = bb_squeeze
    result['bb_pos'] = bb_pos

    score = 0.0
    reasons = []
    is_dc_bull = dc_score >= 0

    # ── B1: BB带宽扩张/收缩（方向跟随DC总分）──
    if bb_width_pct is not None:
        high_th = _cfg('bb', 'width_high_threshold', default=4.0)
        high_score = _cfg('bb', 'width_high_score', default=6.0)
        mod_th = _cfg('bb', 'width_moderate_threshold', default=2.5)
        mod_score = _cfg('bb', 'width_moderate_score', default=3.0)

        if bb_width_pct > high_th:
            b1 = high_score if is_dc_bull else -high_score
            score += b1
            reasons.append(f'BB带宽扩张({bb_width_pct:.1f}%)({b1:+.0f})')
        elif bb_width_pct > mod_th:
            b1 = mod_score if is_dc_bull else -mod_score
            score += b1
            reasons.append(f'BB带宽中等({bb_width_pct:.1f}%)({b1:+.0f})')

    # ── B2: BB挤压检测（无方向，多空都加）──
    squeeze_bonus = _cfg('bb', 'squeeze_bonus', default=2.0)
    if bb_squeeze:
        score += squeeze_bonus
        reasons.append(f'BB挤压检测(+{squeeze_bonus})')

    # ── B3: %b位置 ──
    if bb_pos is not None:
        ext_th = _cfg('bb', 'pos_extreme_threshold', default=1.05)
        ext_score = _cfg('bb', 'pos_extreme_score', default=6.0)
        upper_th = _cfg('bb', 'pos_upper_threshold', default=1.0)
        upper_score = _cfg('bb', 'pos_upper_score', default=4.0)
        mid_up_th = _cfg('bb', 'pos_mid_upper_threshold', default=0.7)
        mid_up_score = _cfg('bb', 'pos_mid_upper_score', default=2.0)
        mid_low_th = _cfg('bb', 'pos_mid_lower_threshold', default=0.15)
        mid_low_score = _cfg('bb', 'pos_mid_lower_score', default=-2.0)
        lower_score = _cfg('bb', 'pos_lower_score', default=-4.0)
        ext_low_score = _cfg('bb', 'pos_extreme_lower_score', default=-6.0)

        if bb_pos > ext_th:
            score += ext_score
            reasons.append(f'%b极端上方({bb_pos:.2f})(+{ext_score})')
        elif bb_pos > upper_th:
            score += upper_score
            reasons.append(f'%b上轨({bb_pos:.2f})(+{upper_score})')
        elif bb_pos > mid_up_th:
            score += mid_up_score
            reasons.append(f'%b中上区域({bb_pos:.2f})(+{mid_up_score})')
        elif bb_pos > 0.30:
            pass  # 中间区域，不加分
        elif bb_pos > mid_low_th:
            score += mid_low_score
            reasons.append(f'%b中下区域({bb_pos:.2f})({mid_low_score:+.0f})')
        elif bb_pos > 0:
            score += lower_score
            reasons.append(f'%b下轨({bb_pos:.2f})({lower_score:+.0f})')
        else:
            score += ext_low_score
            reasons.append(f'%b极端下方({bb_pos:.2f})({ext_low_score:+.0f})')

    # ── DC-BB一致性加分 ──
    consistency = _cfg('bb', 'dc_consistency_bonus', default=2.0)
    if bb_pos is not None:
        if (dc_score > 0 and bb_pos > 0.5) or (dc_score < 0 and bb_pos < 0.5):
            score += consistency
            reasons.append(f'DC-BB方向一致(+{consistency})')

    result['total'] = round(score, 1)
    result['reasons'] = reasons
    return result


# ============================================================
# 成交量确认评分（独立加减分）
# ============================================================

def score_volume(tech: dict, sym: dict, dc_score: float) -> dict:
    """成交量确认评分 (-3 ~ ±10)。

    与DC方向关联：放量时跟随方向，缩量时固定惩罚。
    """
    result = {
        'score': 0.0,
        'vol_ratio': 1.0,
        'reasons': [],
    }

    is_dc_bull = dc_score >= 0
    vol_ratio = tech.get('VOL_RATIO', 1.0)
    result['vol_ratio'] = vol_ratio

    explosive_ratio = _cfg('volume', 'explosive_ratio', default=1.5)
    explosive_score = _cfg('volume', 'explosive_score', default=10.0)
    elevated_ratio = _cfg('volume', 'elevated_ratio', default=1.2)
    elevated_score = _cfg('volume', 'elevated_score', default=5.0)
    weak_penalty = _cfg('volume', 'weak_penalty', default=-3.0)

    if vol_ratio > explosive_ratio:
        vs = explosive_score if is_dc_bull else -explosive_score
        result['score'] = vs
        result['reasons'].append(f'放量突破({vol_ratio:.1f}x)({vs:+.0f})')
    elif vol_ratio > elevated_ratio:
        vs = elevated_score if is_dc_bull else -elevated_score
        result['score'] = vs
        result['reasons'].append(f'放量中等({vol_ratio:.1f}x)({vs:+.0f})')
    elif vol_ratio > 0.8:
        result['reasons'].append(f'成交量正常({vol_ratio:.1f}x)')
    else:
        result['score'] = weak_penalty
        result['reasons'].append(f'缩量({vol_ratio:.1f}x)({weak_penalty:+.0f})')

    return result


# ============================================================
# 方向判定
# ============================================================

def determine_direction(total_score: float) -> str:
    """基于总分符号判定方向。纯符号判定，无死区或中性带。"""
    if total_score > 0:
        return 'bull'
    elif total_score < 0:
        return 'bear'
    return 'neutral'


# ============================================================
# 等级判定
# ============================================================

def determine_grade(total_score: float) -> str:
    """基于总分绝对值判定信号等级。"""
    abs_score = abs(total_score)
    if abs_score >= SIGNAL_GRADE_THRESHOLDS['strong']:
        return 'STRONG'
    elif abs_score >= SIGNAL_GRADE_THRESHOLDS['watch']:
        return 'WATCH'
    elif abs_score >= SIGNAL_GRADE_THRESHOLDS['weak']:
        return 'WEAK'
    return 'NOISE'


# ============================================================
# 信号类型判定（4级优先级）
# ============================================================

def determine_signal_type(dc20_score: float, dc55_score: float, dc_score: float,
                           bb_squeeze: bool) -> str:
    """判定信号类型，按优先级从高到低判定。

    优先级:
    1. channel_breakout:  abs(dc20_score) >= 30 AND abs(dc_score) >= 20
    2. trend_confirmation: abs(dc55_score) >= 15
    3. bb_squeeze_prebreakout: bb_squeeze == True
    4. minor_signal: 上述均不满足
    """
    cfg_st = _cfg('signal_type', default={})
    dc20_min = cfg_st.get('channel_breakout_dc20_min', 30)
    dc_total_min = cfg_st.get('channel_breakout_dc_total_min', 20)
    dc55_min = cfg_st.get('trend_confirmation_dc55_min', 15)

    if abs(dc20_score) >= dc20_min and abs(dc_score) >= dc_total_min:
        return 'channel_breakout'
    if abs(dc55_score) >= dc55_min:
        return 'trend_confirmation'
    if bb_squeeze:
        return 'bb_squeeze_prebreakout'
    return 'minor_signal'


# ============================================================
# 方向感知Z-score（保留commodity概念，简化实现）
# ============================================================

def compute_directional_zscore(total_score: float, all_scores: list = None) -> float:
    """计算单值方向感知Z-score（基于[-76, +76]理论范围归一化）。"""
    if all_scores and len(all_scores) > 2:
        from statistics import mean, stdev
        mu = mean(all_scores)
        sigma = stdev(all_scores)
        if sigma > 0:
            return round((total_score - mu) / sigma, 2)
    # 无足够数据时基于范围估算
    return round(total_score / 76.0 * 3.0, 2)


# ============================================================
# 综合打分入口（唯一的调用入口）
# ============================================================

def calculate_composite_score(tech: dict, sym: dict,
                               all_total_scores: list = None) -> dict:
    """计算通道突破策略综合得分（唯一的评分入口）。

    Args:
        tech: 技术指标字典（由 _compute_indicators_numpy 产出，60+字段）
        sym: 品种信息字典，至少含 {'last_price': float}
        all_total_scores: 可选，所有品种总分列表（用于Z-score计算）

    Returns:
        SignalResult 兼容字典，包含：
        - total, grade, direction, signal_type, z_score
        - sub_scores: {dc20, dc55, dc, bb, vol}
        - sub_details: {dc20, dc55, bb, volume} 明细
        - price, adx, atr, rsi, cci, ma_slope, dc20_break, dc55_pos, dc55_trend
        - bb_width_pct, bb_squeeze, bb_pos, vol_ratio, ma_align
        - reasons: 评分原因列表
    """
    # ── 确保last_price存在 ──
    last_price = sym.get('last_price') or tech.get('last_price')
    if not last_price:
        return {'total': 0, 'grade': 'NOISE', 'direction': 'neutral',
                'signal_type': 'minor_signal', 'reasons': ['价格数据缺失']}
    sym['last_price'] = last_price

    # ── Layer A1: DC20短期突破 ──
    dc20 = score_dc20(tech, sym)
    dc20_score = dc20['score']

    # ── Layer A2: DC55中期趋势 ──
    dc55 = score_dc55(tech, sym)
    dc55_score = dc55['total']

    # ── DC总分 ──
    dc_score = dc20_score + dc55_score

    # ── Layer B: 布林带确认 ──
    bb = score_bb(tech, sym, dc_score)
    bb_score = bb['total']

    # ── 成交量确认 ──
    vol = score_volume(tech, sym, dc_score)
    vol_score = vol['score']

    # ── 总分 ──
    total_score = round(dc_score + bb_score + vol_score, 1)

    # ── 方向 ──
    direction = determine_direction(total_score)

    # ── 等级 ──
    grade = determine_grade(total_score)

    # ── 信号类型 ──
    signal_type = determine_signal_type(
        dc20_score, dc55_score, dc_score,
        tech.get('BB_SQUEEZE', False)
    )

    # ── Z-score ──
    z_score = compute_directional_zscore(total_score, all_total_scores)

    # ── ma_align 推导 ──
    ma5, ma10, ma20 = tech.get('MA5'), tech.get('MA10'), tech.get('MA20')
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20 and last_price > ma20:
            ma_align = 'bull'
        elif ma5 < ma10 < ma20 and last_price < ma20:
            ma_align = 'bear'
        else:
            ma_align = 'mixed'
    else:
        ma_align = 'unknown'

    # ── 评分原因 ──
    reasons = []
    reasons.extend([f'[DC20] {r}' for r in dc20.get('reasons', [])])
    reasons.extend([f'[DC55] {r}' for r in dc55.get('reasons', [])])
    reasons.extend([f'[BB] {r}' for r in bb.get('reasons', [])])
    reasons.extend([f'[VOL] {r}' for r in vol.get('reasons', [])])

    # 兼容性字段：保留绝大多数字段名以便下游引用
    result = {
        'total': total_score,
        'grade': grade,
        'direction': direction,
        'signal_type': signal_type,
        'z_score': min(3.0, max(-3.0, z_score)),
        'reasons': reasons,
        # 子层分数
        'sub_scores': {
            'dc20': round(dc20_score, 1),
            'dc55': round(dc55_score, 1),
            'dc': round(dc_score, 1),
            'bb': round(bb_score, 1),
            'vol': round(vol_score, 1),
        },
        # 详细明细（含内部breakdown）
        'sub_details': {
            'dc20': {
                'score': round(dc20_score, 1),
                'break_detected': dc20['break_detected'],
                'break_pct': round(dc20.get('break_pct', 0), 2),
                'position': round(dc20.get('position', 0.5), 3),
                'reasons': dc20.get('reasons', []),
            },
            'dc55': {
                'total': round(dc55_score, 1),
                'position_score': dc55['position_score'],
                'trend_score': dc55['trend_score'],
                'position_label': dc55['position_label'],
                'dc55_pos': dc55.get('dc55_pos'),
                'reasons': dc55.get('reasons', []),
            },
            'bb': {
                'total': round(bb_score, 1),
                'b1_width': bb.get('b1_width', 0),
                'b2_squeeze': bb.get('b2_squeeze', 0),
                'b3_position': bb.get('b3_position', 0),
                'consistency': bb.get('consistency', 0),
                'bb_width_pct': bb.get('bb_width_pct'),
                'bb_squeeze': bb.get('bb_squeeze'),
                'bb_pos': bb.get('bb_pos'),
                'reasons': bb.get('reasons', []),
            },
            'volume': {
                'score': round(vol_score, 1),
                'vol_ratio': vol.get('vol_ratio', 1.0),
                'reasons': vol.get('reasons', []),
            },
        },
        # 技术指标快照
        'price': last_price,
        'adx': tech.get('ADX', 0),
        'atr': tech.get('ATR14', 0),
        'rsi': tech.get('RSI14', 0),
        'cci': tech.get('CCI20', 0),
        'ma_slope': tech.get('MA20_SLOPE', 0),
        'macd_cross': tech.get('macd_cross', 'none'),
        'dc20_break': dc20['break_detected'],
        'dc55_pos': dc55.get('dc55_pos'),
        'dc55_trend': dc55.get('trend', 'flat'),
        'bb_width_pct': bb.get('bb_width_pct'),
        'bb_squeeze': bb.get('bb_squeeze', False),
        'bb_pos': bb.get('bb_pos'),
        'vol_ratio': vol.get('vol_ratio', 1.0),
        'ma_align': ma_align,
        'stage': 'N/A',  # 兼容旧字段
    }

    return result
