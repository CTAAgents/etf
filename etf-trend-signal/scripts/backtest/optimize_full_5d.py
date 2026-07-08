#!/usr/bin/env python3
"""
五维全参数网格优化 v1.0
==========================
频率(日/周/双周/月) × TOP_N × ENTRY × EXIT × FORCE_CASH
总计 4×9×6×5×5 = 5,400 组

先用缓存加速：预计算评分一次（~10分钟），后续5400组参数模拟仅数秒。
结果保存在 results/cached_scores.json，后续运行自动跳过评分预计算。
"""
import sys, os, json, math, copy, time
from datetime import date, datetime
from statistics import mean, stdev
from collections import defaultdict

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(BACKTEST_DIR)
SKILL_ROOT = os.path.dirname(SKILL_DIR)
for p in [SKILL_ROOT, SKILL_DIR, BACKTEST_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from collect_data import EtfDataCollector
from indicators import _compute_indicators_numpy
from config import SECTOR_ETF_MAPPING
import pandas as pd
import numpy as np
import scoring_system as SS

# ══════════════════════════════════════════════════════════════
# 参数网格
# ══════════════════════════════════════════════════════════════
FREQ_KEYS = ['daily', 'weekly', 'biweekly', 'monthly']
FREQ_LABELS = {'daily': '日频', 'weekly': '周频', 'biweekly': '双周频', 'monthly': '月频'}
TOP_N_GRID = [1, 2, 3, 4, 5, 7, 10, 13, 15]
ENTRY_GRID = [30, 35, 40, 45, 50, 55]
EXIT_GRID = [25, 30, 35, 40, 45]
FC_GRID = [30, 35, 40, 45, 50]

CACHE_PATH = os.path.join(BACKTEST_DIR, 'results', 'cached_scores.json')

# ══════════════════════════════════════════════════════════════
# 数据加载 + 评分缓存
# ══════════════════════════════════════════════════════════════

def load_data(days=750):
    collector = EtfDataCollector()
    all_data = {}
    for s in SECTOR_ETF_MAPPING:
        sector, code = s[0], s[2]
        klines = collector.get_etf_klines(sector, code, days=days)
        if klines and len(klines) >= 100:
            all_data[sector] = {'code': code, 'klines': klines}
    return all_data


def get_dates_from_data(all_data):
    first = list(all_data.keys())[0]
    klines = all_data[first]['klines']
    dates = []
    for i in range(len(klines)):
        ds = str(klines[i].get('date', ''))
        try:
            dt = datetime.strptime(ds, '%Y%m%d')
            dates.append((ds, i, dt.weekday()))
        except:
            continue
    return dates


def compute_and_cache(all_data, dates):
    """计算所有交易日评分并写入缓存文件。"""
    n = len(dates)
    cache = {}
    t0 = time.time()

    for idx, (date_str, data_idx, wkday) in enumerate(dates):
        if idx < 60:
            continue
        if idx % 100 == 0:
            elapsed = time.time() - t0
            eta = (elapsed / max(idx - 59, 1)) * (n - idx)
            print(f'    评分 [{idx}/{n}] {(idx/n)*100:.0f}%  ETA: {eta:.0f}s')

        week_scores = []
        for sector, dinfo in all_data.items():
            klines = dinfo['klines']
            if data_idx >= len(klines):
                continue
            window = klines[:data_idx + 1]
            if len(window) < 60:
                continue

            df = pd.DataFrame({
                'open': [float(r['open']) for r in window],
                'high': [float(r['high']) for r in window],
                'low': [float(r['low']) for r in window],
                'close': [float(r['close']) for r in window],
                'volume': [float(r.get('volume', 0)) for r in window],
            })

            tech = _compute_indicators_numpy(df)
            if not tech or 'RSI14' not in tech:
                continue

            price = tech.get('last_price', float(df['close'].iloc[-1]))
            sym = {'last_price': price}
            sc = SS.calculate_composite_score(tech, sym)

            week_scores.append({
                's': sector,
                'c': dinfo['code'],
                't': sc['total'],
                'd': sc['direction'],
            })

        cache[str(idx)] = week_scores

    # 保存
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    cache_meta = {
        'n_dates': len(cache),
        'n_sectors': len(all_data),
        'first_date': dates[60][0],
        'last_date': dates[-1][0],
    }
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump({'meta': cache_meta, 'scores': cache}, f, ensure_ascii=False)
    print(f'  缓存已保存: {CACHE_PATH}')
    return cache  # 只返回评分数据


def load_or_compute(all_data=None, dates=None):
    """优先从缓存加载，否则计算。"""
    if os.path.exists(CACHE_PATH):
        print(f'  加载缓存: {CACHE_PATH}')
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data['meta']
        print(f'  {meta["n_dates"]} 天 × {meta["n_sectors"]} 行业 ({meta["first_date"]} ~ {meta["last_date"]})')
        return data['scores']
    else:
        print('  缓存不存在，开始评分预计算...')
        if all_data is None or dates is None:
            all_data = load_data()
            dates = get_dates_from_data(all_data)
        return compute_and_cache(all_data, dates)


# ══════════════════════════════════════════════════════════════
# 调仓日期选择
# ══════════════════════════════════════════════════════════════

def select_rebalance_dates(dates, freq):
    """根据频率从全部交易日中选择调仓日期。"""
    selected = []
    if freq == 'daily':
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60:
                selected.append((ds, idx, i))
    elif freq == 'weekly':
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60 and wkday == 2:
                selected.append((ds, idx, i))
    elif freq == 'biweekly':
        count = 0
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60 and wkday == 2:
                if count % 2 == 0:
                    selected.append((ds, idx, i))
                count += 1
    elif freq == 'monthly':
        month_candidates = defaultdict(list)
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60 and wkday == 2:
                month_candidates[ds[:6]].append((ds, idx, i))
        for ym, entries in sorted(month_candidates.items()):
            selected.append(entries[-1])
    return selected


# ══════════════════════════════════════════════════════════════
# 组合模拟（纯内存操作，极快）
# ══════════════════════════════════════════════════════════════

def simulate(cached_scores, all_data, rebalance_dates, top_n, entry_th, exit_th, fc_th):
    """用指定的频率和参数运行组合模拟。"""
    current_holdings = {}
    equity_curve = [1.0]
    returns = []

    for r_idx in range(len(rebalance_dates)):
        date_str, data_idx, cache_idx = rebalance_dates[r_idx]
        scores = cached_scores.get(str(cache_idx), [])
        if not scores:
            continue

        bull_sorted = sorted(
            [s for s in scores if s['d'] == 'bull'],
            key=lambda x: x['t'], reverse=True
        )

        max_bull = max((s['t'] for s in bull_sorted), default=0)
        if max_bull < fc_th:
            ret = _calc_return(current_holdings, all_data, data_idx, rebalance_dates, r_idx)
            returns.append(ret)
            equity_curve.append(equity_curve[-1] * (1 + ret))
            current_holdings = {}
            continue

        target_pool = []
        for r in bull_sorted:
            if len(target_pool) >= top_n:
                break
            if r['t'] > entry_th:
                target_pool.append(r['s'])

        target_set = set(target_pool)
        scores_map = {s['s']: s['t'] for s in scores}

        to_keep = set()
        for sector in list(current_holdings.keys()):
            in_target = sector in target_set
            score = scores_map.get(sector, 0)
            rank = next((i+1 for i, r in enumerate(bull_sorted) if r['s'] == sector), 999)
            if in_target:
                to_keep.add(sector)
            elif rank > top_n and score < exit_th:
                continue
            else:
                to_keep.add(sector)

        new_buys = [s for s in target_pool if s not in to_keep]
        kept = sum(current_holdings.get(s, 0) for s in to_keep)
        remain = max(0.0, 1.0 - kept)

        new_positions = {}
        for s in to_keep:
            new_positions[s] = current_holdings.get(s, 0)
        if new_buys and remain > 0:
            per = round(remain / len(new_buys), 4)
            for s in new_buys:
                new_positions[s] = per

        total = sum(new_positions.values())
        if abs(total - 1.0) > 0.001 and new_positions:
            last = list(new_positions.keys())[-1]
            new_positions[last] = round(new_positions[last] + (1.0 - total), 4)

        ret = _calc_return(current_holdings, all_data, data_idx, rebalance_dates, r_idx)
        returns.append(ret)
        equity_curve.append(equity_curve[-1] * (1 + ret))
        current_holdings = new_positions

    return _metrics(returns, equity_curve)


def _calc_return(holdings, all_data, data_idx, rebalance_dates, r_idx):
    if not holdings:
        return 0.0
    next_idx = rebalance_dates[r_idx + 1][1] if r_idx + 1 < len(rebalance_dates) else data_idx + 5

    ret = 0.0
    for sector, alloc in holdings.items():
        klines = all_data.get(sector, {}).get('klines', [])
        if not klines:
            continue
        buy_idx = data_idx + 1
        if buy_idx >= len(klines):
            continue
        bp = float(klines[buy_idx].get('open', 0))
        if bp == 0:
            continue
        sell_idx = next_idx + 1
        if sell_idx >= len(klines):
            sell_idx = len(klines) - 1
        sp = float(klines[sell_idx].get('open', 0))
        if sp == 0:
            sp = bp
        ret += alloc * (sp - bp) / bp
    return ret


def _metrics(returns, equity):
    n = len(returns)
    if n == 0:
        return {'sharpe': 0, 'total_return': 0, 'max_drawdown': 0, 'calmar': 0}

    total_ret = equity[-1] - 1.0
    n_years = n / 252.0
    ann_ret = (1 + total_ret) ** (1 / max(n_years, 0.01)) - 1
    std_w = stdev(returns) if len(returns) > 1 else 0
    ann_vol = std_w * math.sqrt(252)
    rf = 0.02
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0

    peak = equity[0]
    max_dd = 0.0
    for e in equity[1:]:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    calmar = ann_ret / max_dd if max_dd > 0 else 0

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    pf = (len(wins) * mean(wins)) / (len(losses) * abs(mean(losses))) if losses and abs(mean(losses)) > 0 else 0

    return {
        'sharpe': round(sharpe, 3),
        'total_return': round(total_ret * 100, 2),
        'annual_return': round(ann_ret * 100, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'calmar': round(calmar, 3),
        'win_rate': round(len(wins) / max(n, 1) * 100, 1),
        'profit_factor': round(pf, 2),
        'n_periods': n,
    }


# ══════════════════════════════════════════════════════════════
# 平原分析
# ══════════════════════════════════════════════════════════════

def analyze_plateau(all_results, metric='sharpe', tol=0.10):
    """分析参数平原。

    对每个参数维度，找出哪些值与最优值差距<tol。
    返回每个维度的"平原范围"和"推荐值"。
    """
    if not all_results:
        return None

    best = max(all_results, key=lambda x: x.get(metric, -999))
    best_val = best[metric]
    threshold = best_val - tol
    good = [r for r in all_results if r.get(metric, -999) >= threshold]

    def _range(vals):
        sv = sorted(set(vals))
        return (sv[0], sv[-1]) if sv else None

    return {
        'best': best,
        'best_val': best_val,
        'threshold': threshold,
        'n_good': len(good),
        'n_total': len(all_results),
        'good_pct': round(len(good) / max(len(all_results), 1) * 100, 1),
        'plateau': {
            'top_n': _range([r['top_n'] for r in good]),
            'entry': _range([r['entry'] for r in good]),
            'exit': _range([r['exit'] for r in good]),
            'fc': _range([r['force_cash'] for r in good]),
        },
        'suggested': {
            'top_n': best['top_n'],
            'entry': best['entry'],
            'exit': best['exit'],
            'force_cash': best['force_cash'],
        },
    }


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main():
    print(f'{"="*65}')
    print(f'五维全参数网格优化 v1.0')
    print(f'维度: 频率[4] × TOP_N[9] × ENTRY[6] × EXIT[5] × FC[5] = {4*9*6*5*5}组')
    print(f'日期: {date.today()}')
    print(f'{"="*65}')

    # Step 1: 数据 + 评分缓存
    print('\n[1] 准备数据...')
    all_data = load_data()
    dates = get_dates_from_data(all_data)
    print(f'  行业: {len(all_data)}, 交易日: {len(dates)}')
    cached_scores = load_or_compute(all_data, dates)

    # Step 2: 为每种频率选择调仓日期
    print('\n[2] 选择调仓日期...')
    rebal_dates = {}
    for freq in FREQ_KEYS:
        rd = select_rebalance_dates(dates, freq)
        rebal_dates[freq] = rd
        print(f'  {FREQ_LABELS[freq]:>6}: {len(rd):>3} 次调仓')

    # Step 3: 全网格搜索
    total = len(FREQ_KEYS) * len(TOP_N_GRID) * len(ENTRY_GRID) * len(EXIT_GRID) * len(FC_GRID)
    print(f'\n[3] 运行 {total} 组网格搜索...')

    freq_best = {}
    all_results = []
    done = 0
    t0 = time.time()

    for freq in FREQ_KEYS:
        freq_results = []
        rd = rebal_dates[freq]

        for top_n in TOP_N_GRID:
            for entry in ENTRY_GRID:
                for exit_th in EXIT_GRID:
                    for fc in FC_GRID:
                        metrics = simulate(cached_scores, all_data, rd, top_n, entry, exit_th, fc)
                        r = {
                            'freq': freq,
                            'top_n': top_n,
                            'entry': entry,
                            'exit': exit_th,
                            'force_cash': fc,
                            'sharpe': metrics['sharpe'],
                            'total_return': metrics['total_return'],
                            'annual_return': metrics['annual_return'],
                            'max_drawdown': metrics['max_drawdown'],
                            'calmar': metrics['calmar'],
                            'win_rate': metrics['win_rate'],
                        }
                        freq_results.append(r)
                        all_results.append(r)
                        done += 1

        # 排序 + 平原分析
        freq_results.sort(key=lambda x: x['sharpe'], reverse=True)
        pa = analyze_plateau(freq_results, tol=0.10)
        freq_best[freq] = {
            'label': FREQ_LABELS[freq],
            'n_rebalances': len(rd),
            'best': freq_results[0],
            'top5': freq_results[:5],
            'plateau': pa,
        }

        elapsed = time.time() - t0
        eta = (elapsed / max(done, 1)) * (total - done) if done < total else 0
        best_s = freq_results[0]['sharpe']
        print(f'  [{done:>4}/{total}] {FREQ_LABELS[freq]:>6}: best Sharpe={best_s:.3f}  '
              f'elapsed={elapsed:.0f}s  ETA={eta:.0f}s')

    # Step 4: 输出
    print(f'\n{"="*65}')
    print(f'📊 各频率最优对比')
    print(f'{"="*65}')
    print(f'\n{"频率":<6} {"Sharpe":>7} {"年化%":>7} {"回撤%":>7} {"卡玛":>6} {"TOP_N":>5} {"ENTRY":>5} {"EXIT":>5} {"FC":>5} {"调仓":>5}')
    print('-' * 62)

    global_best = sorted(all_results, key=lambda x: x['sharpe'], reverse=True)

    for freq in FREQ_KEYS:
        fb = freq_best[freq]
        b = fb['best']
        print(f'{FREQ_LABELS[freq]:<6} {b["sharpe"]:>7.3f} {b["annual_return"]:>+6.1f} '
              f'{b["max_drawdown"]:>6.1f} {b["calmar"]:>6.3f} '
              f'{b["top_n"]:>5} {b["entry"]:>5} {b["exit"]:>5} {b["force_cash"]:>5} '
              f'{fb["n_rebalances"]:>5}')

    print(f'\n🏆 全局最优:')
    gb = global_best[0]
    print(f'  频率={FREQ_LABELS[gb["freq"]]}, TOP_N={gb["top_n"]}, ENTRY={gb["entry"]}, '
          f'EXIT={gb["exit"]}, FC={gb["force_cash"]}')
    print(f'  Sharpe={gb["sharpe"]:.3f}, 年化={gb["annual_return"]:+.1f}%, '
          f'回撤={gb["max_drawdown"]:.1f}%, 卡玛={gb["calmar"]:.3f}')

    # 平原分析
    print(f'\n📐 平原分析 (tol=0.10, 即Sharpe≥{global_best[0]["sharpe"]-0.10:.3f}):')
    for freq in FREQ_KEYS:
        fb = freq_best[freq]
        pa = fb['plateau']
        print(f'  {FREQ_LABELS[freq]:>6}: 平原命中 {pa["n_good"]}/{pa["n_total"]} ({pa["good_pct"]}%)')
        for pk, pv in pa['plateau'].items():
            if pv:
                # 键名映射: top_n/entry/exit/fc → suggested中的top_n/entry/exit/force_cash
                sk = 'force_cash' if pk == 'fc' else pk
                print(f'      {pk:<10}: {pv[0]} ~ {pv[1]} (推荐={pa["suggested"][sk]})')

    # 保存
    output = {
        'date': str(date.today()),
        'grid_sizes': {'freq': 4, 'top_n': len(TOP_N_GRID), 'entry': len(ENTRY_GRID),
                        'exit': len(EXIT_GRID), 'force_cash': len(FC_GRID),
                        'total': total},
        'global_best': global_best[0],
        'global_top10': global_best[:10],
        'frequencies': {f: {
            'label': freq_best[f]['label'],
            'n_rebalances': freq_best[f]['n_rebalances'],
            'best': freq_best[f]['best'],
            'top5': freq_best[f]['top5'],
            'plateau': freq_best[f]['plateau'],
        } for f in FREQ_KEYS},
    }

    out_path = os.path.join(BACKTEST_DIR, 'results',
                            f'optimize_full_5d_{date.today().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n📊 结果已保存: {out_path}')
    print(f'📊 评分缓存: {CACHE_PATH}')


if __name__ == '__main__':
    main()
