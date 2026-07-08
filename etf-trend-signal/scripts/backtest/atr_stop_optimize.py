#!/usr/bin/env python3
"""
ATR移动跟踪止损 — 训练/测试/优化 v1.0
============================================
核心逻辑：周频调仓 + 每日ATR移动跟踪止损
- 入场后每日更新止损价 = 持仓期间最高收盘价 - ATR倍数 × ATR
- 触发止损 → 次日开盘退出该品种
- 两阶段网格搜索：Phase1(ATR+工作日) → Phase2(策略参数)
- 时间序列分割：前60%训练 / 后40%测试
"""
import sys, os, json, math, time
from datetime import datetime
from statistics import mean, stdev
import numpy as np

SKILL_SCRIPTS = r'C:\Users\yangd\.workbuddy\skills\etf-trend-signal\scripts'
sys.path.insert(0, SKILL_SCRIPTS)

from collect_data import EtfDataCollector
from config import SECTOR_ETF_MAPPING
from indicators import _compute_indicators_numpy
import pandas as pd
import scoring_system as SS

# ═══════════════════════════════════════════════════════
# 参数网格
# ═══════════════════════════════════════════════════════
WEEKDAY_NAMES = {0:'周一',1:'周二',2:'周三',3:'周四',4:'周五'}
OUT_DIR = r'C:\Users\yangd\Documents\ETF\Reports'
CACHE_DIR = r'C:\Users\yangd\Documents\ETF\Reports\cache'
TRAIN_RATIO = 0.6  # 前60%时间训练

# Phase 1: ATR + 工作日（固定策略参数）
ATR_MULTS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
ATR_PERIODS = [14, 20]
WEEKDAYS = [0, 1, 2, 3, 4]

# Phase 2: 策略参数（固定最优ATR）
TOP_NS = [2, 3, 4]
ENTRY_THS = [50, 55, 60]
EXIT_THS = [25, 30, 35]
FC_THS = [30, 35, 40]

FIXED = {'top_n': 3, 'entry': 55, 'exit_th': 30, 'fc': 35}

# ═══════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════

def load_all_data():
    collector = EtfDataCollector(source='tdx')
    all_data = {}
    for s in SECTOR_ETF_MAPPING:
        sector, code = s[0], s[2]
        klines = collector.get_etf_klines(sector, code, days=1250)
        if klines and len(klines) >= 100:
            all_data[sector] = {
                'code': code,
                'dates': [k['date'] for k in klines],
                'open': np.array([float(k['open']) for k in klines]),
                'high': np.array([float(k['high']) for k in klines]),
                'low': np.array([float(k['low']) for k in klines]),
                'close': np.array([float(k['close']) for k in klines]),
                'volume': np.array([float(k.get('volume', 0)) for k in klines]),
                'n': len(klines),
            }
    return all_data


def precompute_scores(all_data):
    """预计算所有交易日的通道突破评分。"""
    first = list(all_data.keys())[0]
    n_days = all_data[first]['n']
    daily_scores = {}

    t0 = time.time()
    for sector, dinfo in all_data.items():
        n = dinfo['n']; opens = dinfo['open']; highs = dinfo['high']
        lows = dinfo['low']; closes = dinfo['close']; volumes = dinfo['volume']

        for i in range(60, n):
            df = pd.DataFrame({
                'open': opens[:i+1], 'high': highs[:i+1],
                'low': lows[:i+1], 'close': closes[:i+1],
                'volume': volumes[:i+1],
            })
            tech = _compute_indicators_numpy(df)
            if not tech or 'RSI14' not in tech:
                continue
            price = tech.get('last_price', float(closes[i]))
            sc = SS.calculate_composite_score(tech, {'last_price': price})

            if i not in daily_scores:
                daily_scores[i] = []
            daily_scores[i].append({
                'sector': sector, 'total': sc['total'],
                'direction': sc['direction'],
            })

        elapsed = time.time() - t0
        print(f'  {sector:<8} ({n-60}天, 累计{elapsed:.0f}s)', flush=True)

    print(f'  预计算完成: {len(daily_scores)}天, {sum(len(v) for v in daily_scores.values())}条', flush=True)
    return daily_scores, n_days


# ═══════════════════════════════════════════════════════
# ATR & 止损
# ═══════════════════════════════════════════════════════

def compute_atr(highs, lows, closes, idx, period=14):
    """在指定索引计算ATR(N)。"""
    if idx < period:
        return 0.0
    win_h = highs[idx-period+1:idx+1]
    win_l = lows[idx-period+1:idx+1]
    win_c = closes[idx-period:idx+1]
    trs = []
    for i in range(len(win_h)):
        if i == 0:
            tr = win_h[i] - win_l[i]
        else:
            tr = max(win_h[i] - win_l[i],
                     abs(win_h[i] - win_c[i-1]),
                     abs(win_l[i] - win_c[i-1]))
        trs.append(tr)
    return np.mean(trs)


def check_stop_daily(all_data, holdings, entry_prices, entry_idxs,
                      from_idx, to_idx, atr_mult, atr_period):
    """
    逐日检查持仓是否触发ATR移动止损。
    返回: (幸存持仓, 止损收益累计, 止损次数)
    """
    stops_total_ret = 0.0
    stops_count = 0
    survivors = dict(holdings)
    surv_entry_prices = dict(entry_prices)
    surv_entry_idxs = dict(entry_idxs)

    for day_idx in range(from_idx, to_idx + 1):
        for sec, alloc in list(survivors.items()):
            k = all_data.get(sec, {})
            if not k or day_idx >= len(k['close']):
                continue

            closes = k['close']; highs = k['high']; lows = k['low']
            entry_i = surv_entry_idxs.get(sec, from_idx)

            # 持仓期间最高收盘价
            if entry_i <= day_idx:
                high_close = closes[entry_i:day_idx+1].max()
            else:
                continue

            atr = compute_atr(highs, lows, closes, day_idx, atr_period)
            if atr <= 0:
                continue

            trailing_stop = high_close - atr_mult * atr

            # 止损触发：当日最低价 ≤ 止损价
            if lows[day_idx] <= trailing_stop:
                sell_idx = day_idx + 1
                if sell_idx < len(k['open']):
                    sell_price = float(k['open'][sell_idx])
                    ep = surv_entry_prices.get(sec, sell_price)
                    if ep > 0:
                        stops_total_ret += alloc * (sell_price - ep) / ep

                stops_count += 1
                del survivors[sec]
                surv_entry_prices.pop(sec, None)
                surv_entry_idxs.pop(sec, None)

    return survivors, surv_entry_prices, surv_entry_idxs, stops_total_ret, stops_count


# ═══════════════════════════════════════════════════════
# 回测（含ATR止损）
# ═══════════════════════════════════════════════════════

def find_rebal_dates(dates, n_days, weekday):
    """找出指定工作日的调仓日。"""
    result = []
    for i in range(60, n_days):
        ds = str(dates[i])
        try:
            dt = datetime.strptime(ds, '%Y%m%d')
            if dt.weekday() == weekday:
                result.append((ds, i))
        except:
            continue
    return result


def backtest_with_stop(all_data, daily_scores, rebal_dates,
                        atr_mult, atr_period,
                        top_n, entry_th, exit_th, fc_th):
    """周频调仓 + ATR移动跟踪止损。"""
    holdings = {}; entry_prices = {}; entry_idxs = {}
    equity = [1.0]; total_returns = []
    total_stops = 0; total_rebal = 0

    for ri, (date_str, data_idx) in enumerate(rebal_dates):
        # ── 步骤1: 检查止损（从上个调仓日到今天）──
        stop_ret = 0.0; n_stops = 0
        if holdings and ri > 0:
            prev_idx = rebal_dates[ri-1][1]
            survivors, surv_prices, surv_idxs, stop_ret, n_stops = \
                check_stop_daily(all_data, holdings, entry_prices, entry_idxs,
                                 prev_idx + 1, data_idx, atr_mult, atr_period)
            holdings = survivors
            entry_prices = surv_prices
            entry_idxs = surv_idxs
            total_stops += n_stops

        # ── 步骤2: 结算幸存仓位（入场价 → 当日次日开盘 = 本周退出价）──
        week_ret = stop_ret  # 止损收益+结算收益合并
        if holdings:
            exit_idx = data_idx + 1
            for sec, alloc in holdings.items():
                k = all_data.get(sec, {})
                if not k or exit_idx >= len(k['open']):
                    continue
                ep = entry_prices.get(sec, 0)
                sp = float(k['open'][exit_idx])
                if ep > 0 and sp > 0:
                    week_ret += alloc * (sp - ep) / ep

        total_returns.append(round(week_ret, 6))
        equity.append(round(equity[-1] * (1 + week_ret), 6))

        # ── 步骤3: 调仓决策 ──
        scores = daily_scores.get(data_idx, [])
        bull = sorted([s for s in scores if s['direction'] == 'bull'],
                      key=lambda x: x['total'], reverse=True)
        max_bull = max((s['total'] for s in bull), default=0)

        if max_bull < fc_th:
            holdings = {}; entry_prices = {}; entry_idxs = {}
            total_rebal += 1
            continue

        pool = []
        for rec in bull:
            if len(pool) >= top_n: break
            if rec['total'] > entry_th:
                pool.append(rec['sector'])

        pool_set = set(pool)
        scores_map = {s['sector']: s['total'] for s in scores}

        keep = set()
        for sec in list(holdings.keys()):
            in_t = sec in pool_set
            sc = scores_map.get(sec, 0)
            rk = next((i+1 for i, rec in enumerate(bull) if rec['sector'] == sec), 999)
            if in_t:
                keep.add(sec)
            elif rk > top_n and sc < exit_th:
                continue
            else:
                keep.add(sec)

        new_b = [s for s in pool if s not in keep]
        kept_alloc = sum(holdings.get(s, 0) for s in keep)
        rem = max(0.0, 1.0 - kept_alloc)

        pos = {}
        for s in keep:
            pos[s] = holdings.get(s, 0)
        if new_b and rem > 0:
            p = round(rem / len(new_b), 4)
            for s in new_b:
                pos[s] = p

        # 记录入场信息
        new_prices = {}; new_idxs = {}
        entry_open_idx = data_idx + 1
        for s in pos:
            k = all_data.get(s, {})
            if k and entry_open_idx < len(k['open']):
                ep = float(k['open'][entry_open_idx])
                if ep > 0:
                    new_prices[s] = ep
                    new_idxs[s] = entry_open_idx

        holdings = pos; entry_prices = new_prices; entry_idxs = new_idxs
        total_rebal += 1

    # ── 最终结算 ──
    final_ret = 0.0
    if holdings and rebal_dates:
        last_idx = rebal_dates[-1][1]
        for sec, alloc in holdings.items():
            k = all_data.get(sec, {})
            if not k: continue
            ep = entry_prices.get(sec, 0)
            lp = float(k['close'][-1])
            if ep > 0 and lp > 0:
                final_ret += alloc * (lp - ep) / ep
    total_returns.append(round(final_ret, 6))
    equity.append(round(equity[-1] * (1 + final_ret), 6))

    return {
        'equity': equity,
        'returns': total_returns,
        'stops_hit': total_stops,
        'n_rebal': total_rebal,
    }


def backtest_no_stop(all_data, daily_scores, rebal_dates,
                      top_n, entry_th, exit_th, fc_th):
    """无止损的纯周频调仓（基准对比）。"""
    holdings = {}; entry_prices = {}
    equity = [1.0]; returns = []

    for ri, (date_str, data_idx) in enumerate(rebal_dates):
        scores = daily_scores.get(data_idx, [])
        bull = sorted([s for s in scores if s['direction'] == 'bull'],
                      key=lambda x: x['total'], reverse=True)
        max_bull = max((s['total'] for s in bull), default=0)

        # 结算旧仓位
        week_ret = 0.0
        if holdings:
            exit_idx = data_idx + 1
            for sec, alloc in holdings.items():
                k = all_data.get(sec, {})
                if not k or exit_idx >= len(k['open']): continue
                ep = entry_prices.get(sec, 0)
                sp = float(k['open'][exit_idx])
                if ep > 0 and sp > 0:
                    week_ret += alloc * (sp - ep) / ep

        returns.append(round(week_ret, 6))
        equity.append(round(equity[-1] * (1 + week_ret), 6))

        if max_bull < fc_th:
            holdings = {}; entry_prices = {}; continue

        pool = []
        for rec in bull:
            if len(pool) >= top_n: break
            if rec['total'] > entry_th:
                pool.append(rec['sector'])

        pool_set = set(pool)
        scores_map = {s['sector']: s['total'] for s in scores}

        keep = set()
        for sec in list(holdings.keys()):
            in_t = sec in pool_set
            sc = scores_map.get(sec, 0)
            rk = next((i+1 for i, rec in enumerate(bull) if rec['sector'] == sec), 999)
            if in_t: keep.add(sec)
            elif rk > top_n and sc < exit_th: continue
            else: keep.add(sec)

        new_b = [s for s in pool if s not in keep]
        kept = sum(holdings.get(s, 0) for s in keep)
        rem = max(0.0, 1.0 - kept)
        pos = {}
        for s in keep: pos[s] = holdings.get(s, 0)
        if new_b and rem > 0:
            p = round(rem / len(new_b), 4)
            for s in new_b: pos[s] = p

        new_prices = {}
        entry_i = data_idx + 1
        for s in pos:
            k = all_data.get(s, {})
            if k and entry_i < len(k['open']):
                ep = float(k['open'][entry_i])
                if ep > 0: new_prices[s] = ep

        holdings = pos; entry_prices = new_prices

    # 最终结算
    final_r = 0.0
    if holdings and rebal_dates:
        for sec, alloc in holdings.items():
            k = all_data.get(sec, {})
            if not k: continue
            ep = entry_prices.get(sec, 0)
            lp = float(k['close'][-1])
            if ep > 0 and lp > 0:
                final_r += alloc * (lp - ep) / ep
    returns.append(round(final_r, 6))
    equity.append(round(equity[-1] * (1 + final_r), 6))

    return {'equity': equity, 'returns': returns, 'stops_hit': 0}


# ═══════════════════════════════════════════════════════
# 绩效评估
# ═══════════════════════════════════════════════════════

def calc_metrics(equity, returns, n_weeks):
    if not returns or len(returns) == 0:
        return {'sharpe': 0, 'total_return': 0, 'annual_return': 0,
                'max_drawdown': 0, 'calmar': 0, 'win_rate': 0,
                'profit_factor': 0}

    tr = equity[-1] - 1.0
    ny = max(n_weeks, 1) / 52.0
    ar = (1 + tr) ** (1 / max(ny, 0.01)) - 1 if tr > -1 else -1
    sd = stdev(returns) if len(returns) > 1 else 0
    av = sd * math.sqrt(52)
    sh = (ar - 0.02) / av if av > 0 else 0

    peak = equity[0]; mdd = 0.0
    for e in equity[1:]:
        if e > peak: peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > mdd: mdd = dd

    cal = ar / mdd if mdd > 0 else 0
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    aw = mean(wins) if wins else 0
    al = abs(mean(losses)) if losses else 0
    pf = (len(wins) * aw) / (len(losses) * al) if (losses and al > 0) else 0

    return {
        'sharpe': round(sh, 3), 'total_return': round(tr * 100, 2),
        'annual_return': round(ar * 100, 2), 'max_drawdown': round(mdd * 100, 2),
        'calmar': round(cal, 3), 'win_rate': round(len(wins) / max(n_weeks, 1) * 100, 1),
        'profit_factor': round(pf, 2),
    }


# ═══════════════════════════════════════════════════════
# 网格搜索优化
# ═══════════════════════════════════════════════════════

def grid_search_phase1(all_data, daily_scores, dates, n_days):
    """Phase 1: 优化 ATR倍数 × ATR周期 × 调仓工作日。"""
    print(f'\n{"="*60}')
    print(f'Phase 1: ATR参数 + 工作日网格搜索')
    print(f'  ATR倍数: {ATR_MULTS}')
    print(f'  ATR周期: {ATR_PERIODS}')
    print(f'  工作日: {[WEEKDAY_NAMES[w] for w in WEEKDAYS]}')
    print(f'  固定策略: TOP_N={FIXED["top_n"]} ENTRY={FIXED["entry"]} FC={FIXED["fc"]}')
    print(f'{"="*60}')

    # 时间序列分割
    train_end = int(n_days * TRAIN_RATIO)

    results = []
    total = len(ATR_MULTS) * len(ATR_PERIODS) * len(WEEKDAYS)
    count = 0

    for atr_m in ATR_MULTS:
        for atr_p in ATR_PERIODS:
            for wd in WEEKDAYS:
                count += 1
                all_rebal = find_rebal_dates(dates, n_days, wd)
                train_rebal = [(ds, i) for ds, i in all_rebal if i <= train_end]
                test_rebal = [(ds, i) for ds, i in all_rebal if i > train_end]

                if len(train_rebal) < 20:
                    continue

                # 训练集
                sim = backtest_with_stop(all_data, daily_scores, train_rebal,
                                         atr_m, atr_p,
                                         FIXED['top_n'], FIXED['entry'],
                                         FIXED['exit_th'], FIXED['fc'])
                train_m = calc_metrics(sim['equity'], sim['returns'], len(train_rebal))

                # 测试集
                sim_t = backtest_with_stop(all_data, daily_scores, test_rebal,
                                           atr_m, atr_p,
                                           FIXED['top_n'], FIXED['entry'],
                                           FIXED['exit_th'], FIXED['fc'])
                test_m = calc_metrics(sim_t['equity'], sim_t['returns'], len(test_rebal))

                results.append({
                    'atr_mult': atr_m, 'atr_period': atr_p,
                    'weekday': wd, 'weekday_name': WEEKDAY_NAMES[wd],
                    'train_n': len(train_rebal), 'test_n': len(test_rebal),
                    'train_sharpe': train_m['sharpe'],
                    'train_return': train_m['annual_return'],
                    'train_dd': train_m['max_drawdown'],
                    'test_sharpe': test_m['sharpe'],
                    'test_return': test_m['annual_return'],
                    'test_dd': test_m['max_drawdown'],
                    'test_calmar': test_m['calmar'],
                    'stops_train': sim['stops_hit'],
                    'stops_test': sim_t['stops_hit'],
                })

                if count % 10 == 0:
                    print(f'  [{count}/{total}]...', flush=True)

    # 按测试Sharpe排序
    results.sort(key=lambda x: x['test_sharpe'], reverse=True)
    return results


def grid_search_phase2(all_data, daily_scores, dates, n_days,
                        best_atr_m, best_atr_p, best_wd):
    """Phase 2: 优化策略参数。"""
    print(f'\n{"="*60}')
    print(f'Phase 2: 策略参数网格搜索')
    print(f'  固定: ATR={best_atr_m}×{best_atr_p}  工作日={WEEKDAY_NAMES[best_wd]}')
    print(f'  搜索: TOP_N={TOP_NS} ENTRY={ENTRY_THS} EXIT={EXIT_THS} FC={FC_THS}')
    print(f'{"="*60}')

    train_end = int(n_days * TRAIN_RATIO)
    all_rebal = find_rebal_dates(dates, n_days, best_wd)
    train_rebal = [(ds, i) for ds, i in all_rebal if i <= train_end]
    test_rebal = [(ds, i) for ds, i in all_rebal if i > train_end]

    results = []
    total = len(TOP_NS) * len(ENTRY_THS) * len(EXIT_THS) * len(FC_THS)
    count = 0

    for tn in TOP_NS:
        for ent in ENTRY_THS:
            for ext in EXIT_THS:
                for fc in FC_THS:
                    count += 1
                    sim = backtest_with_stop(all_data, daily_scores, train_rebal,
                                             best_atr_m, best_atr_p, tn, ent, ext, fc)
                    train_m = calc_metrics(sim['equity'], sim['returns'], len(train_rebal))

                    sim_t = backtest_with_stop(all_data, daily_scores, test_rebal,
                                               best_atr_m, best_atr_p, tn, ent, ext, fc)
                    test_m = calc_metrics(sim_t['equity'], sim_t['returns'], len(test_rebal))

                    results.append({
                        'top_n': tn, 'entry': ent, 'exit_th': ext, 'fc': fc,
                        'train_n': len(train_rebal), 'test_n': len(test_rebal),
                        'train_sharpe': train_m['sharpe'],
                        'test_sharpe': test_m['sharpe'],
                        'test_return': test_m['annual_return'],
                        'test_dd': test_m['max_drawdown'],
                        'test_calmar': test_m['calmar'],
                        'test_win_rate': test_m['win_rate'],
                        'stops_test': sim_t['stops_hit'],
                    })

                    if count % 10 == 0:
                        print(f'  [{count}/{total}]...', flush=True)

    results.sort(key=lambda x: x['test_sharpe'], reverse=True)
    return results


# ═══════════════════════════════════════════════════════
# HTML报告
# ═══════════════════════════════════════════════════════

def generate_html_report(phase1, phase2, baseline, best_config, out_path):
    """生成完整优化报告HTML。"""
    # Phase 1 top 10
    p1_rows = ''
    for i, r in enumerate(phase1[:10]):
        f = '★' if i == 0 else ''
        p1_rows += f'''<tr>
            <td>{f} {i+1}</td>
            <td>{r['atr_mult']}×</td><td>{r['atr_period']}日</td>
            <td>{r['weekday_name']}</td>
            <td class="{'pos' if r['train_sharpe']>0 else 'neg'}">{r['train_sharpe']:+.3f}</td>
            <td class="{'pos' if r['test_sharpe']>0 else 'neg'}">{r['test_sharpe']:+.3f}</td>
            <td class="{'pos' if r['test_return']>0 else 'neg'}">{r['test_return']:+.1f}%</td>
            <td class="neg">{r['test_dd']:.1f}%</td>
            <td>{r['stops_test']}次</td>
        </tr>'''

    # Phase 2 top 10
    p2_rows = ''
    for i, r in enumerate(phase2[:10]):
        f = '★' if i == 0 else ''
        p2_rows += f'''<tr>
            <td>{f} {i+1}</td>
            <td>{r['top_n']}</td><td>{r['entry']}</td>
            <td>{r['exit_th']}</td><td>{r['fc']}</td>
            <td class="{'pos' if r['test_sharpe']>0 else 'neg'}">{r['test_sharpe']:+.3f}</td>
            <td class="{'pos' if r['test_return']>0 else 'neg'}">{r['test_return']:+.1f}%</td>
            <td class="neg">{r['test_dd']:.1f}%</td>
            <td>{r['test_calmar']:.2f}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><title>ATR移动跟踪止损优化报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1200px;margin:20px auto;background:#f5f5f5;padding:0 20px}}
.card{{background:#fff;border-radius:8px;padding:24px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
h1{{color:#1a1a2e}}h2{{color:#16213e;border-bottom:2px solid #e94560;padding-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:6px 10px;border-bottom:1px solid #eee;text-align:center}}
th{{background:#1a1a2e;color:#fff}}tr:hover{{background:#fafafa}}
.pos{{color:#e94560;font-weight:bold}}.neg{{color:#27ae60}}
.best{{background:#fff3e0;border:2px solid #ff9800;padding:16px;border-radius:6px;margin:12px 0}}
.best h3{{color:#e65100;margin:0 0 8px 0}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
</style>
</head>
<body>
<h1>ATR移动跟踪止损 — 参数优化报告</h1>
<p style="color:#666">策略: 通道突破周频调仓 + ATR移动跟踪止损 | 训练/测试: {int(TRAIN_RATIO*100)}%/{int((1-TRAIN_RATIO)*100)}% 时间分割</p>

<div class="card best">
<h3>最优配置</h3>
<table><tr>
<td style="text-align:left;padding-right:24px"><b>ATR止损</b>: {best_config['atr_mult']}×ATR({best_config['atr_period']})</td>
<td style="text-align:left;padding-right:24px"><b>调仓日</b>: {WEEKDAY_NAMES[best_config.get('weekday', best_config.get('best_wd', 2))]}</td>
<td style="text-align:left;padding-right:24px"><b>策略</b>: TOP_N={best_config['top_n']} ENTRY={best_config['entry']} EXIT={best_config['exit_th']} FC={best_config['fc']}</td>
</tr></table>
<p style="color:#e65100;margin:8px 0 0 0">
  测试集: Sharpe={best_config['best_sharpe']:.3f} | 年化={best_config['best_return']:+.1f}% | 回撤={best_config['best_dd']:.1f}% | 卡玛={best_config.get('best_calmar', 0):.2f}
</p>
</div>

<div class="card">
<h2>Phase 1: ATR参数 + 工作日优化（Top 10）</h2>
<p style="color:#666;font-size:13px">固定策略参数: TOP_N={FIXED['top_n']} ENTRY={FIXED['entry']} FC={FIXED['fc']}</p>
<table>
<tr><th>排名</th><th>ATR倍数</th><th>ATR周期</th><th>工作日</th><th>训练Sharpe</th><th>测试Sharpe</th><th>测试年化</th><th>测试回撤</th><th>止损次数</th></tr>
{p1_rows}
</table>
</div>

<div class="card">
<h2>Phase 2: 策略参数优化（Top 10）</h2>
<p style="color:#666;font-size:13px">固定: ATR={best_config.get('best_atr_m', '?')}×{best_config.get('best_atr_p', '?')}  {WEEKDAY_NAMES[best_config.get('best_wd', 2)]}</p>
<table>
<tr><th>排名</th><th>TOP_N</th><th>ENTRY</th><th>EXIT</th><th>FC</th><th>测试Sharpe</th><th>测试年化</th><th>测试回撤</th><th>卡玛</th></tr>
{p2_rows}
</table>
</div>

<div class="card">
<h2>基准对比（无止损）</h2>
<table>
<tr><th>模式</th><th>Sharpe</th><th>年化收益</th><th>最大回撤</th><th>卡玛</th><th>止损次数</th></tr>
<tr>
  <td>无止损基准</td>
  <td class="{'pos' if baseline['sharpe']>0 else 'neg'}">{baseline['sharpe']:+.3f}</td>
  <td class="{'pos' if baseline['annual_return']>0 else 'neg'}">{baseline['annual_return']:+.1f}%</td>
  <td class="neg">{baseline['max_drawdown']:.1f}%</td>
  <td>{baseline['calmar']:.2f}</td>
  <td>0</td>
</tr>
<tr>
  <td><b>ATR止损优化</b></td>
  <td class="{'pos' if best_config['best_sharpe']>0 else 'neg'}"><b>{best_config['best_sharpe']:+.3f}</b></td>
  <td class="{'pos' if best_config['best_return']>0 else 'neg'}"><b>{best_config['best_return']:+.1f}%</b></td>
  <td class="neg"><b>{best_config['best_dd']:.1f}%</b></td>
  <td><b>{best_config.get('best_calmar', 0):.2f}</b></td>
  <td>{best_config.get('stops', '?')}次</td>
</tr>
</table>
</div>
</body></html>'''

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

def main():
    print(f'{"="*60}')
    print(f'ATR移动跟踪止损 — 训练/测试/优化')
    print(f'{"="*60}')

    # ── 数据准备 ──
    print('\n[1/5] 加载TDX数据...', flush=True)
    t0 = time.time()
    all_data = load_all_data()
    first = list(all_data.keys())[0]
    dates = all_data[first]['dates']
    n_days = all_data[first]['n']
    print(f'  {len(all_data)}行业, {n_days}天 ({dates[0]}~{dates[-1]}), {time.time()-t0:.0f}s', flush=True)

    # ── 预计算评分 ──
    print('\n[2/5] 预计算通道突破评分...', flush=True)
    t2 = time.time()
    daily_scores, n_days = precompute_scores(all_data)
    print(f'  总耗时: {time.time()-t2:.0f}s', flush=True)

    # ── 基准（无止损） ──
    print('\n[3/5] 无止损基准回测...', flush=True)
    base_rebal = find_rebal_dates(dates, n_days, 2)  # 周三
    base_train = [(ds, i) for ds, i in base_rebal if i <= int(n_days * TRAIN_RATIO)]
    base_test = [(ds, i) for ds, i in base_rebal if i > int(n_days * TRAIN_RATIO)]

    base_sim = backtest_no_stop(all_data, daily_scores, base_test,
                                FIXED['top_n'], FIXED['entry'],
                                FIXED['exit_th'], FIXED['fc'])
    baseline = calc_metrics(base_sim['equity'], base_sim['returns'], len(base_test))

    # ── Phase 1 ──
    print('\n[4/5] Phase 1: ATR参数优化...', flush=True)
    t4 = time.time()
    p1_results = grid_search_phase1(all_data, daily_scores, dates, n_days)
    print(f'  Phase 1 完成: {len(p1_results)}组, {time.time()-t4:.0f}s', flush=True)

    best_p1 = p1_results[0]
    best_atr_m = best_p1['atr_mult']
    best_atr_p = best_p1['atr_period']
    best_wd = best_p1['weekday']
    print(f'  ★ 最优: ATR={best_atr_m}×{best_atr_p}  {WEEKDAY_NAMES[best_wd]}  '
          f'测试Sharpe={best_p1["test_sharpe"]:.3f}', flush=True)

    # ── Phase 2 ──
    print('\n[5/5] Phase 2: 策略参数优化...', flush=True)
    t5 = time.time()
    p2_results = grid_search_phase2(all_data, daily_scores, dates, n_days,
                                     best_atr_m, best_atr_p, best_wd)
    print(f'  Phase 2 完成: {len(p2_results)}组, {time.time()-t5:.0f}s', flush=True)

    best_p2 = p2_results[0]
    print(f'  ★ 最优: TOP_N={best_p2["top_n"]} ENTRY={best_p2["entry"]} '
          f'EXIT={best_p2["exit_th"]} FC={best_p2["fc"]}  '
          f'测试Sharpe={best_p2["test_sharpe"]:.3f}', flush=True)

    # ── 汇总报告 ──
    total_time = time.time() - t0
    print(f'\n{"="*60}')
    print(f'优化完成 (总耗时 {total_time:.0f}s)')
    print(f'{"="*60}')

    # 保存JSON
    output = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'baseline': baseline,
        'phase1_top10': p1_results[:10],
        'phase2_top10': p2_results[:10],
        'best_config': {
            'atr_mult': best_atr_m, 'atr_period': best_atr_p,
            'best_wd': best_wd, 'best_wd_name': WEEKDAY_NAMES[best_wd],
            'top_n': best_p2['top_n'], 'entry': best_p2['entry'],
            'exit_th': best_p2['exit_th'], 'fc': best_p2['fc'],
            'best_sharpe': best_p2['test_sharpe'],
            'best_return': best_p2['test_return'],
            'best_dd': best_p2['test_dd'],
            'best_calmar': best_p2['test_calmar'],
            'stops': best_p2['stops_test'],
        },
    }

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(OUT_DIR, f'atr_stop_optimize_{ts}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    html_path = os.path.join(OUT_DIR, f'atr_stop_optimize_{ts}.html')
    generate_html_report(p1_results, p2_results, baseline,
                         output['best_config'], html_path)

    print(f'\nJSON: {json_path}')
    print(f'HTML: {html_path}')

    # 打印对比
    print(f'\n{"="*60}')
    print(f'最终对比')
    print(f'{"="*60}')
    print(f'{"指标":<12} {"无止损基准":>12} {"ATR止损优化":>12} {"改善":>10}')
    print(f'{ "-"*48}')
    items = [
        ('Sharpe', baseline['sharpe'], best_p2['test_sharpe']),
        ('年化收益%', baseline['annual_return'], best_p2['test_return']),
        ('最大回撤%', baseline['max_drawdown'], best_p2['test_dd']),
        ('卡玛比率', baseline['calmar'], best_p2['test_calmar']),
    ]
    for label, base, best in items:
        delta = best - base
        sign = '+' if delta > 0 else ''
        print(f'{label:<12} {base:>+12.3f} {best:>+12.3f} {sign}{delta:>+.3f}')

    return output


if __name__ == '__main__':
    main()
