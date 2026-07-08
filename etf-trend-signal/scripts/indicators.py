# -*- coding: utf-8 -*-
"""技术指标计算（ETF版）：保留通用技术指标，移除期货专属OI/期限等。"""

from typing import Optional


def safe_float(val) -> Optional[float]:
    """安全转换为float。"""
    try:
        import pandas as pd
        if isinstance(val, pd.Series):
            val = val.iloc[-1]
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None


def assess_trend_maturity(tech: dict, sym: dict, score: int) -> dict:
    """评估趋势阶段：launch/trending/exhausted/reversal (ETF版)。

    与commodity版本逻辑一致，但ETF无OI概念，纯技术指标判断。

    1. reversal: 价格穿越DC55中轨反方向 + ADX<35
    2. exhausted: DC20通道极值 + RSI极端
    3. launch: 突破DC20通道 + (Boll收口或DC55同向拐头)
    4. trending: DC20上半区 + ADX>=25强制promotion
    """
    last_price = sym.get('last_price')
    ma20 = tech.get('MA20')
    rsi = tech.get('RSI14')

    is_bull = score > 0

    price_deviation_pct = 0
    if last_price and ma20 and ma20 > 0:
        price_deviation_pct = (last_price - ma20) / ma20 * 100

    bb_upper = tech.get('BB_UPPER')
    bb_middle = tech.get('BB_MIDDLE')
    bb_lower = tech.get('BB_LOWER')
    dc_upper = tech.get('DC_UPPER')
    dc_lower = tech.get('DC_LOWER')
    dc_mid = tech.get('DC_MID')
    dc55_upper = tech.get('DC55_UPPER')
    dc55_lower = tech.get('DC55_LOWER')
    dc55_mid = tech.get('DC55_MID')
    dc55_trend = tech.get('DC55_TREND')
    bb_squeeze = tech.get('BB_SQUEEZE', False)

    dc_pos = None
    if dc_upper and dc_lower and last_price and (dc_upper - dc_lower) > 0:
        if is_bull:
            dc_pos = (last_price - dc_lower) / (dc_upper - dc_lower)
        else:
            dc_pos = (dc_upper - last_price) / (dc_upper - dc_lower)
        dc_pos = max(0, min(1.0, dc_pos))

    bb_pos = None
    if bb_upper and bb_lower and bb_middle and last_price and (bb_upper - bb_lower) > 0:
        if is_bull:
            bb_pos = (last_price - bb_middle) / (bb_upper - bb_middle) if (bb_upper - bb_middle) > 0 else 0.5
        else:
            bb_pos = (bb_middle - last_price) / (bb_middle - bb_lower) if (bb_middle - bb_lower) > 0 else 0.5
        bb_pos = max(0, min(2.0, bb_pos))

    dc55_pos = None
    if dc55_upper and dc55_lower and last_price and (dc55_upper - dc55_lower) > 0:
        if is_bull:
            dc55_pos = (last_price - dc55_lower) / (dc55_upper - dc55_lower)
        else:
            dc55_pos = (dc55_upper - last_price) / (dc55_upper - dc55_lower)
        dc55_pos = max(0, min(1.0, dc55_pos))

    rsi_extreme = False
    if rsi is not None:
        if is_bull and rsi > 75:
            rsi_extreme = True
        elif not is_bull and rsi < 25:
            rsi_extreme = True

    price_extreme = abs(price_deviation_pct) > 12

    stage = 'unknown'

    if dc55_mid and last_price:
        adx_val = tech.get("ADX")
        if adx_val is not None and adx_val >= 35:
            pass
        elif (is_bull and last_price < dc55_mid) or (not is_bull and last_price > dc55_mid):
            stage = "reversal"

    if stage == 'unknown' and dc_pos is not None:
        exhausted_bull = is_bull and dc_pos > 0.85
        exhausted_bear = not is_bull and dc_pos < 0.15
        if (exhausted_bull or exhausted_bear) and rsi_extreme:
            stage = 'exhausted'
        elif dc_pos > 0.85 and price_extreme and rsi_extreme:
            stage = 'exhausted'

    if stage == 'unknown' and dc_pos is not None:
        breakout = (is_bull and dc_pos > 0.7) or (not is_bull and dc_pos < 0.3)
        if breakout and (bb_squeeze or dc55_trend == 'up' and is_bull or dc55_trend == 'down' and not is_bull):
            stage = 'launch'
        elif breakout and dc_pos > 0.7 and dc_pos <= 0.85:
            stage = 'launch'
        elif not is_bull and breakout and dc_pos <= 0.15:
            stage = 'launch'

    if stage == 'unknown' and dc_pos is not None:
        if dc_pos > 0.5:
            stage = 'trending'
        elif dc_pos > 0.3:
            if bb_pos is not None and bb_pos > 0.3:
                stage = 'trending'
            else:
                stage = 'launch'
        else:
            stage = 'launch'

    if stage == 'launch':
        adx_val = tech.get('ADX')
        if adx_val is not None and adx_val >= 25:
            stage = 'trending'

    if stage == 'unknown':
        if price_extreme:
            stage = 'exhausted'
        elif abs(price_deviation_pct) > 5:
            stage = 'trending'
        else:
            stage = 'launch'

    if dc_pos is not None:
        if dc_pos <= 0.3:
            channel_position = 'near_lower'
        elif dc_pos <= 0.5:
            channel_position = 'below_mid'
        elif dc_pos <= 0.7:
            channel_position = 'above_mid'
        elif dc_pos <= 0.85:
            channel_position = 'near_upper'
        else:
            channel_position = 'at_extreme'
    else:
        channel_position = 'unknown'

    return {
        'stage': stage,
        'channel_position': channel_position,
        'dc_pos': round(dc_pos, 3) if dc_pos is not None else None,
        'dc55_pos': round(dc55_pos, 3) if dc55_pos is not None else None,
        'bb_pos': round(bb_pos, 3) if bb_pos is not None else None,
        'bb_squeeze': bb_squeeze,
        'bb_width_pct': round(tech.get('BB_WIDTH_PCT', 0), 1) if tech.get('BB_WIDTH_PCT') else None,
        'dc55_trend': dc55_trend,
        'price_deviation_pct': round(price_deviation_pct, 2),
        'price_extreme': price_extreme,
        'rsi_extreme': rsi_extreme,
    }


def identify_market_state(tech_data: dict, sym_data: dict) -> tuple:
    """识别市场状态。返回 (market_state, trend_score)。"""
    try:
        from scripts.config import CONFIG_MANAGER
    except ImportError:
        from config import CONFIG_MANAGER

    MARKET_STATE_SYSTEM = CONFIG_MANAGER['market_state']

    ma5 = tech_data.get('MA5')
    ma10 = tech_data.get('MA10')
    ma20 = tech_data.get('MA20')
    ma40 = tech_data.get('MA40')
    ma60 = tech_data.get('MA60')
    atr = tech_data.get('ATR14')
    last_price = sym_data.get('last_price')

    trend_score = 0
    if ma5 and ma10 and ma20:
        short_bull = ma5 > ma10 > ma20
        short_bear = ma5 < ma10 < ma20
        long_bull = (ma20 > ma40 > ma60) if (ma40 and ma60) else short_bull
        long_bear = (ma20 < ma40 < ma60) if (ma40 and ma60) else short_bear

        ma_spread = abs(ma5 - ma20) / ma20 if ma20 else 0
        is_tight = ma_spread < 0.005

        if short_bull and long_bull and not is_tight:
            trend_score = 30
        elif short_bull and not is_tight:
            trend_score = 15
        elif short_bear and long_bear and not is_tight:
            trend_score = -30
        elif short_bear and not is_tight:
            trend_score = -15

    volatility = 0
    if atr and last_price:
        volatility = atr / last_price * 100

    if abs(trend_score) >= MARKET_STATE_SYSTEM['trend_threshold']:
        if volatility >= MARKET_STATE_SYSTEM['volatile_threshold']:
            return 'volatile', trend_score
        return 'trending', trend_score
    elif abs(trend_score) <= MARKET_STATE_SYSTEM['range_threshold']:
        return 'ranging', trend_score
    return 'transitional', trend_score


def _compute_indicators_numpy(klines, symbol: str = None) -> dict:
    """Fallback: numpy/pandas 计算全部技术指标（ETF版）。

    与commodity版一致，移除OI相关指标。
    接受: DataFrame with columns [open,high,low,close,volume]
    """
    import pandas as pd, numpy as np
    if isinstance(klines, dict):
        df = pd.DataFrame(klines)
    else:
        df = klines if hasattr(klines, 'columns') else pd.DataFrame(klines)

    cn_to_en = {'开盘价': 'open', '最高价': 'high', '最低价': 'low', '收盘价': 'close',
                '成交量': 'volume', '成交额': 'amount', '日期': 'date'}
    df = df.rename(columns={k: v for k, v in cn_to_en.items() if k in df.columns})
    o = df['open'].values.astype(float)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    c = df['close'].values.astype(float)
    v = df.get('volume', np.zeros_like(c))
    if hasattr(v, 'values'): v = v.values.astype(float)

    tech = {}
    n = len(c)
    if n < 60: return tech

    def sma(x, p): return pd.Series(x).rolling(p).mean().values
    def wilder_rma(x, p):
        out = np.zeros_like(x)
        out[p-1] = np.mean(x[:p])
        for i in range(p, len(x)):
            out[i] = (x[i] + (p-1)*out[i-1]) / p
        return out
    def ema(x, p):
        a = 2/(p+1); e = np.zeros_like(x); e[0] = x[0]
        for i in range(1,len(x)): e[i] = a*x[i] + (1-a)*e[i-1]
        return e
    def sd(x, p): return pd.Series(x).rolling(p).std().values
    def md(x, p): return pd.Series(x).rolling(p).apply(lambda v: np.mean(np.abs(v-np.mean(v))), raw=True).values
    def max_(x,p): return pd.Series(x).rolling(p).max().values
    def min_(x,p): return pd.Series(x).rolling(p).min().values
    def atr_fn(p=14):
        tr = np.maximum(h-l, np.maximum(np.abs(h-np.roll(c,1)), np.abs(l-np.roll(c,1))))
        return wilder_rma(tr, p)

    # ---- MA ----
    for p in [5,10,20,40,60,120]:
        tech[f'MA{p}'] = float(sma(c, p)[-1])

    ma20_series = sma(c, 20)
    t = np.arange(5)
    slope, _ = np.polyfit(t, ma20_series[-5:], 1) if n >= 25 else (0, 0)
    tech['MA20_SLOPE'] = float(slope)

    # ---- MACD ----
    e12 = ema(c, 12); e26 = ema(c, 26)
    dif = e12 - e26
    dea = ema(dif, 9)
    tech['MACD_DIF'] = float(dif[-1])
    tech['MACD_DEA'] = float(dea[-1])

    # ---- RSI14 ----
    d = np.diff(c, prepend=c[0])
    g = np.clip(d, 0, None); ls = np.clip(-d, 0, None)
    ag = wilder_rma(g, 14); al = wilder_rma(ls, 14)
    tech['RSI14'] = float(100 - 100/(1 + ag[-1]/al[-1])) if al[-1] > 0 else 100.0

    # ---- CCI20 ----
    tp = (h + l + c) / 3
    tp_ma = sma(tp, 20); tp_md_ = md(tp, 20)
    tech['CCI20'] = float((tp[-1]-tp_ma[-1])/(0.015*tp_md_[-1])) if tp_md_[-1] > 0 else 0.0

    # ---- ATR14 ----
    a14 = atr_fn(14)
    tech['ATR14'] = float(a14[-1])
    tech['ATR_PERCENTILE'] = float(np.percentile(a14[-20:], [50])[0]) if n >= 20 else 0
    a20 = atr_fn(20) if n >= 20 else a14
    tech['ATR_RATIO_20'] = float(a14[-1]/np.mean(a20[-60:])) if n >= 60 and np.mean(a20[-60:]) > 0 else 1.0
    tech['volatility_pct'] = float(a14[-1]/c[-1]*100) if c[-1] > 0 else 0
    tech['volatility_state'] = 'high' if tech['volatility_pct'] > 3 else 'normal'

    # ---- DMI / ADX ----
    up_ = h - np.roll(h, 1); dn_ = np.roll(l, 1) - l
    pdm = np.where((up_ > dn_) & (up_ > 0), up_, 0.0)
    mdm = np.where((dn_ > up_) & (dn_ > 0), dn_, 0.0)
    at14 = a14
    with np.errstate(divide='ignore', invalid='ignore'):
        pdi = np.where(at14 != 0, 100 * wilder_rma(pdm, 14) / at14, 0.0)
        mdi = np.where(at14 != 0, 100 * wilder_rma(mdm, 14) / at14, 0.0)
    dx = 100 * np.abs(pdi - mdi) / (pdi + mdi + 1e-10)
    adx_ = wilder_rma(dx, 14)
    tech['DMI_PDI'] = float(pdi[-1]); tech['DMI_MDI'] = float(mdi[-1])
    tech['ADX'] = float(adx_[-1])

    # ---- DC Donchian ----
    for p, suffix in [(20,''),(55,'55')]:
        u = max_(h, p); lw = min_(l, p)
        tech[f'DC{suffix}_UPPER'] = float(u[-1]); tech[f'DC{suffix}_LOWER'] = float(lw[-1])
        tech[f'DC{suffix}_MID'] = float((u[-1]+lw[-1])/2)
    dc20_l = tech['DC_LOWER']; dc20_u = tech['DC_UPPER']
    tech['DC_POS'] = float((c[-1]-dc20_l)/(dc20_u-dc20_l)) if dc20_u > dc20_l else 0.5
    tech['DC55_TREND'] = 'up' if tech['MA20_SLOPE'] > 0.01 else ('down' if tech['MA20_SLOPE'] < -0.01 else 'flat')

    # ---- BB Bollinger ----
    bb_mid = sma(c, 20)
    bb_std = sd(c, 20)
    tech['BB_UPPER'] = float(bb_mid[-1] + 2*bb_std[-1])
    tech['BB_LOWER'] = float(bb_mid[-1] - 2*bb_std[-1])
    tech['BB_MIDDLE'] = float(bb_mid[-1])
    tech['BB_PCTB'] = float((c[-1]-tech['BB_LOWER'])/(tech['BB_UPPER']-tech['BB_LOWER'])) if tech['BB_UPPER'] > tech['BB_LOWER'] else 0.5
    tech['BB_WIDTH'] = float((tech['BB_UPPER']-tech['BB_LOWER'])/tech['BB_MIDDLE']*100) if tech['BB_MIDDLE'] > 0 else 0
    tech['BB_WIDTH_PCT'] = tech['BB_WIDTH']
    bw20 = (bb_mid + 2*bb_std - (bb_mid - 2*bb_std)) / bb_mid * 100
    tech['BB_SQUEEZE'] = bool(bw20[-1] < np.percentile(bw20[-60:], 10)) if n >= 60 else False

    # ---- SUPERTREND (10,3) ----
    at10 = atr_fn(10)
    hl = (h + l) / 2
    upper = hl + 3*at10; lower = hl - 3*at10
    st_arr = np.zeros(n); st_dir_arr = np.zeros(n)
    trend = 1; st_arr[0] = lower[0]; st_dir_arr[0] = 1
    for i in range(1, n):
        if trend == 1:
            if c[i] < st_arr[i-1]:
                trend = -1; st_arr[i] = upper[i]
            else:
                st_arr[i] = max(lower[i], st_arr[i-1])
        else:
            if c[i] > st_arr[i-1]:
                trend = 1; st_arr[i] = lower[i]
            else:
                st_arr[i] = min(upper[i], st_arr[i-1])
        st_dir_arr[i] = trend
    tech['SUPERTREND_DIR'] = int(st_dir_arr[-1])
    tech['SUPERTREND_JUST_FLIPPED'] = st_dir_arr[-1] != st_dir_arr[-2] if n >= 3 else False

    # ---- Vortex (14) ----
    vm_p = np.abs(h - np.roll(l, 1)); vm_m = np.abs(l - np.roll(h, 1))
    tr_v = atr_fn(14)
    with np.errstate(divide='ignore', invalid='ignore'):
        vp = np.where(tr_v != 0, wilder_rma(vm_p, 14) / tr_v, 0.0)
        vm = np.where(tr_v != 0, wilder_rma(vm_m, 14) / tr_v, 0.0)
    tech['VI_PLUS'] = float(vp[-1]); tech['VI_MINUS'] = float(vm[-1])

    # ---- HMA ----
    def hma_fn(x, p):
        h1 = sma(x, p//2) * 2 - sma(x, p)
        return sma(h1, int(np.sqrt(p)))
    if n >= 20:
        tech['HMA10'] = float(hma_fn(c, 10)[-1]) if n >= 10 else 0
        tech['HMA20'] = float(hma_fn(c, 20)[-1])
        hma10_series = hma_fn(c, 10)
        tech['HMA_CROSS'] = 1 if hma10_series[-1] > tech['HMA20'] else -1
        tech['HMA_JUST_CROSSED'] = (hma10_series[-2] <= tech.get('HMA20_PREV', tech['HMA20']) and tech['HMA_CROSS'] == 1) or \
                                    (hma10_series[-2] >= tech.get('HMA20_PREV', tech['HMA20']) and tech['HMA_CROSS'] == -1)
    else:
        tech['HMA10'] = 0; tech['HMA20'] = 0; tech['HMA_CROSS'] = 0; tech['HMA_JUST_CROSSED'] = False

    # ---- KAMA ----
    if n >= 10:
        eff = np.abs(c[-1] - c[-10]) / np.sum(np.abs(np.diff(c[-10:]))) if np.sum(np.abs(np.diff(c[-10:]))) > 0 else 0
        sc = (eff * (2/(3)-2/(31)) + 2/(31))**2
        kama = c[-10]
        for i in range(-9, 0): kama = kama + sc * (c[i] - kama)
        tech['KAMA10'] = float(kama)
        tech['KAMA_CROSS'] = 1 if c[-1] > kama else -1
    else:
        tech['KAMA10'] = 0; tech['KAMA_CROSS'] = 0

    # ---- CMF21 ----
    if np.sum(v) > 0:
        mfm = ((c - l) - (h - c)) / (h - l + 1e-10) * v
        cmf = sma(mfm, 21) / sma(v, 21)
        tech['CMF21'] = float(cmf[-1]) if np.isfinite(cmf[-1]) else 0
    else:
        tech['CMF21'] = 0

    # ---- OBV ----
    obv = np.zeros(n); obv[0] = v[0]
    for i in range(1, n):
        if c[i] > c[i-1]: obv[i] = obv[i-1] + v[i]
        elif c[i] < c[i-1]: obv[i] = obv[i-1] - v[i]
        else: obv[i] = obv[i-1]
    tech['OBV'] = float(obv[-1])
    tech['OBV_MA20'] = float(sma(obv, 20)[-1]) if n >= 20 else 0

    # ---- WILLR14 ----
    h14 = max_(h, 14); l14 = min_(l, 14)
    tech['WILLR14'] = float((h14[-1]-c[-1])/(h14[-1]-l14[-1]+1e-10)*-100)

    # ---- STOCH_K5 ----
    h5 = max_(h, 5); l5 = min_(l, 5)
    tech['STOCH_K5'] = float((c[-1]-l5[-1])/(h5[-1]-l5[-1]+1e-10)*100)

    # ---- ROC10 ----
    tech['ROC10'] = float((c[-1]/c[-11]-1)*100) if n >= 11 else 0

    # ---- Volume indicators ----
    v5 = np.mean(v[-5:]); v20 = np.mean(v[-20:])
    tech['VOL_5D_RATIO'] = float(v[-1]/v5) if v5 > 0 else 1
    tech['VOL_MA20'] = float(v20)
    tech['VOL_RATIO'] = float(v[-1]/v20) if v20 > 0 else 1
    # 成交额比率（用于否决项）
    amount = df.get('amount', None)
    if amount is not None and hasattr(amount, 'values'):
        amt = amount.values.astype(float)
        if n >= 20:
            amt20 = np.mean(amt[-20:])
            tech['AMOUNT_RATIO'] = float(amt[-1]/amt20) if amt20 > 0 else 1
    tech['VOL_PRICE_DIVERGENCE'] = 'negative' if (c[-1] < c[-5] and v[-1] > v5*1.2) else \
                                    ('positive' if (c[-1] > c[-5] and v[-1] > v5*1.2) else 'none')

    # ---- Price structure ----
    tech['PRICE_CHANGE_5D'] = float((c[-1]/c[-6]-1)*100) if n >= 6 else 0
    tech['HIGH_60'] = float(np.max(h[-60:])) if n >= 60 else 0
    tech['MA120'] = float(sma(c, 120)[-1]) if n >= 120 else 0
    tech['NEW_HIGH_60'] = c[-1] >= tech['HIGH_60'] * 0.99
    tech['NEW_LOW_60'] = c[-1] <= np.min(l[-60:]) * 1.01 if n >= 60 else False

    # HIGHER_LOW / LOWER_HIGH
    if n >= 20:
        l20 = l[-20:]; h20 = h[-20:]
        l_min = np.argmin(l20); h_max = np.argmax(h20)
        recent_l = np.min(l[-5:]); recent_h = np.max(h[-5:])
        tech['HIGHER_LOW'] = l_min < 10 and recent_l > np.min(l20[:10]) if l_min < len(l20) else False
        tech['LOWER_HIGH'] = h_max < 10 and recent_h < np.max(h20[:10]) if h_max < len(h20) else False
    else:
        tech['HIGHER_LOW'] = False; tech['LOWER_HIGH'] = False

    tech['PRICE_DEVIATION_PCT'] = float((c[-1]-tech.get('MA20',c[-1]))/tech.get('MA20',c[-1])*100) if tech.get('MA20',c[-1]) > 0 else 0
    tech['last_price'] = float(c[-1])

    return tech


def compute_indicators(klines, symbol: str = None) -> dict:
    """从K线数据计算技术指标。返回tech字典。优先tqsdk.ta，失败则fallback到numpy。"""
    import tqsdk.ta as ta

    tech = {}

    try:
        tech['MA5'] = safe_float(ta.MA(klines, 5).iloc[-1])
        tech['MA10'] = safe_float(ta.MA(klines, 10).iloc[-1])
        tech['MA20'] = safe_float(ta.MA(klines, 20).iloc[-1])
        tech['MA40'] = safe_float(ta.MA(klines, 40).iloc[-1])
        tech['MA60'] = safe_float(ta.MA(klines, 60).iloc[-1])
    except Exception:
        pass

    try:
        macd = ta.MACD(klines, 12, 26, 9)
        if hasattr(macd, 'columns'):
            dif_col = None
            dea_col = None
            for col in macd.columns:
                col_lower = str(col).lower().strip()
                if col_lower in ('dif', 'diff') and dif_col is None:
                    dif_col = col
                elif col_lower in ('dea', 'signal') and dea_col is None:
                    dea_col = col
            if dif_col:
                tech['MACD_DIF'] = safe_float(macd[dif_col].iloc[-1])
            if dea_col:
                tech['MACD_DEA'] = safe_float(macd[dea_col].iloc[-1])
    except Exception:
        pass

    try:
        tech['RSI14'] = safe_float(ta.RSI(klines, 14).iloc[-1])
    except Exception:
        pass

    try:
        dmi = ta.DMI(klines, 14, 6)
        if hasattr(dmi, 'columns'):
            for col in ['pdi', 'PDI', '+DI']:
                if col in dmi.columns:
                    tech['DMI_PDI'] = safe_float(dmi[col].iloc[-1])
                    break
            for col in ['mdi', 'MDI', '-DI']:
                if col in dmi.columns:
                    tech['DMI_MDI'] = safe_float(dmi[col].iloc[-1])
                    break
    except Exception:
        pass

    try:
        tech['ATR14'] = safe_float(ta.ATR(klines, 14).iloc[-1])
    except Exception:
        pass

    try:
        import pandas as pd
        close_prices = klines['close']
        volumes = klines['volume']
        obv = [0]
        for i in range(1, len(close_prices)):
            if close_prices.iloc[i] > close_prices.iloc[i - 1]:
                obv.append(obv[-1] + volumes.iloc[i])
            elif close_prices.iloc[i] < close_prices.iloc[i - 1]:
                obv.append(obv[-1] - volumes.iloc[i])
            else:
                obv.append(obv[-1])
        tech['OBV'] = obv[-1]
        obv_series = pd.Series(obv)
        if len(obv_series) >= 20:
            tech['OBV_MA20'] = safe_float(obv_series.rolling(20).mean().iloc[-1])
    except Exception:
        pass

    # Bollinger Bands
    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 20:
            bb_mid = close.rolling(20).mean()
            bb_std = close.rolling(20).std()
            tech['BB_UPPER'] = safe_float(bb_mid.iloc[-1] + 2 * bb_std.iloc[-1])
            tech['BB_MIDDLE'] = safe_float(bb_mid.iloc[-1])
            tech['BB_LOWER'] = safe_float(bb_mid.iloc[-1] - 2 * bb_std.iloc[-1])
            if bb_mid.iloc[-1] > 0:
                tech['BB_WIDTH'] = safe_float((bb_mid.iloc[-1] + 2 * bb_std.iloc[-1] - (bb_mid.iloc[-1] - 2 * bb_std.iloc[-1])) / bb_mid.iloc[-1] * 100)
    except Exception:
        pass

    # Donchian (20)
    try:
        import pandas as pd
        high_prices = klines['high']
        low_prices = klines['low']
        if len(high_prices) >= 20:
            tech['DC_UPPER'] = safe_float(high_prices.rolling(20).max().iloc[-1])
            tech['DC_LOWER'] = safe_float(low_prices.rolling(20).min().iloc[-1])
            dc_u = tech.get('DC_UPPER')
            dc_l = tech.get('DC_LOWER')
            if dc_u and dc_l:
                tech['DC_MID'] = safe_float((dc_u + dc_l) / 2)
    except Exception:
        pass

    # Donchian (55)
    try:
        import pandas as pd
        high_prices = klines['high']
        low_prices = klines['low']
        if len(high_prices) >= 55:
            tech['DC55_UPPER'] = safe_float(high_prices.rolling(55).max().iloc[-1])
            tech['DC55_LOWER'] = safe_float(low_prices.rolling(55).min().iloc[-1])
            dc55_u = tech.get('DC55_UPPER')
            dc55_l = tech.get('DC55_LOWER')
            if dc55_u and dc55_l:
                tech['DC55_MID'] = safe_float((dc55_u + dc55_l) / 2)
            if len(high_prices) >= 110:
                prev_dc55_upper = safe_float(high_prices.iloc[-110:-55].max())
                if prev_dc55_upper and dc55_u:
                    tech['DC55_TREND'] = 'up' if dc55_u > prev_dc55_upper else ('down' if dc55_u < prev_dc55_upper else 'flat')
    except Exception:
        pass

    # BB Squeeze
    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 60:
            bb_mid_series = close.rolling(20).mean()
            bb_std_series = close.rolling(20).std()
            bb_width_series = (4 * bb_std_series / bb_mid_series * 100).dropna()
            if len(bb_width_series) >= 20:
                current_width = bb_width_series.iloc[-1]
                recent_widths = bb_width_series.tail(20)
                percentile = (recent_widths < current_width).sum() / len(recent_widths) * 100
                tech['BB_WIDTH_PCT'] = safe_float(percentile)
                tech['BB_SQUEEZE'] = percentile <= 10
    except Exception:
        pass

    # MA60/MA120
    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 60:
            tech['MA60'] = safe_float(close.rolling(60).mean().iloc[-1])
        if len(close) >= 120:
            tech['MA120'] = safe_float(close.rolling(120).mean().iloc[-1])
    except Exception:
        pass

    # VOL
    try:
        import pandas as pd
        volumes = klines['volume']
        if len(volumes) >= 20:
            tech['VOL_MA20'] = safe_float(volumes.rolling(20).mean().iloc[-1])
            tech['VOL_RATIO'] = safe_float(volumes.iloc[-1] / volumes.rolling(20).mean().iloc[-1]) if volumes.rolling(20).mean().iloc[-1] > 0 else None
    except Exception:
        pass

    # HIGH_60
    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 60:
            high_60 = close.rolling(60).max().iloc[-1]
            tech['HIGH_60'] = safe_float(high_60)
            tech['NEW_HIGH_60'] = safe_float(close.iloc[-1]) >= safe_float(high_60) if high_60 else False
    except Exception:
        pass

    # v2.12 萌芽因子
    try:
        import pandas as pd
        import numpy as np
        close = klines['close']
        if len(close) >= 25:
            ma20_series = close.rolling(20).mean()
            recent_ma = ma20_series.tail(5).values
            if len(recent_ma) == 5 and not np.isnan(recent_ma).any():
                x = np.arange(5)
                slope = np.polyfit(x, recent_ma, 1)[0]
                if recent_ma[-1] > 0:
                    tech['MA20_SLOPE'] = safe_float(slope / recent_ma[-1] * 100)
    except Exception:
        pass

    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 11:
            roc = (close.iloc[-1] - close.iloc[-11]) / close.iloc[-11] * 100
            tech['ROC10'] = safe_float(roc)
    except Exception:
        pass

    try:
        import pandas as pd
        volumes = klines['volume']
        if len(volumes) >= 6:
            vol_5d_avg = volumes.iloc[-6:-1].mean()
            if vol_5d_avg > 0:
                tech['VOL_5D_RATIO'] = safe_float(volumes.iloc[-1] / vol_5d_avg)
    except Exception:
        pass

    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 6:
            change_5d = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100
            tech['PRICE_CHANGE_5D'] = safe_float(change_5d)
    except Exception:
        pass

    # Higher Low / Lower High
    try:
        import pandas as pd
        import numpy as np
        close = klines['close']
        if len(close) >= 20:
            mid = 10
            first_half = close.iloc[-20:-mid]
            second_half = close.iloc[-mid:]
            low1 = first_half.min()
            low2 = second_half.min()
            tech['HIGHER_LOW'] = bool(low2 > low1 * 1.003)
            high1 = first_half.max()
            high2 = second_half.max()
            tech['LOWER_HIGH'] = bool(high2 < high1 * 0.997)
    except Exception:
        pass

    # L2/L3 扩展指标
    try:
        import pandas as pd
        close = klines['close']
        if len(close) >= 20:
            bb_u = tech.get('BB_UPPER')
            bb_l = tech.get('BB_LOWER')
            last_p = safe_float(close.iloc[-1])
            if bb_u and bb_l and last_p and (bb_u - bb_l) > 0:
                tech['BB_PCTB'] = safe_float((last_p - bb_l) / (bb_u - bb_l))
    except Exception:
        pass

    # CCI20 (tqsdk 替代)
    try:
        import pandas as pd
        high_prices = klines['high']
        low_prices = klines['low']
        close = klines['close']
        if len(close) >= 20:
            tp = (high_prices + low_prices + close) / 3
            tp_ma = tp.rolling(20).mean()
            tp_md = tp.rolling(20).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
            last_tp = safe_float(tp.iloc[-1])
            last_ma = safe_float(tp_ma.iloc[-1])
            last_md = safe_float(tp_md.iloc[-1])
            if last_tp is not None and last_ma is not None and last_md is not None and last_md > 0:
                tech['CCI20'] = safe_float((last_tp - last_ma) / (0.015 * last_md))
    except Exception:
        pass

    # Fallback check
    tech_key_count = len(tech)
    if tech_key_count < 5:
        tech = _compute_indicators_numpy(klines, symbol)
    return tech
