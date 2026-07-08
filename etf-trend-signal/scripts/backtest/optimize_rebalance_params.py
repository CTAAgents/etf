#!/usr/bin/env python3
"""
周频调仓参数网格优化 v1.0
=============================
预计算所有周评分数据，然后对 TOP_N / ENTRY / EXIT / FORCE_CASH 四参数
做全组合网格搜索，找到表现最优且参数平原最广的配置。

优化指标：夏普比率优先，兼顾最大回撤和收益。
"参数平原"定义：相邻参数组合的夏普变化<0.05的区域。
"""
import sys, os, json, math, copy
from datetime import date, datetime, timedelta
from statistics import mean, stdev
import itertools

BACKTEST_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(BACKTEST_DIR)
SKILL_ROOT = os.path.dirname(SKILL_DIR)
for p in [SKILL_ROOT, SKILL_DIR, BACKTEST_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from collect_data import EtfDataCollector
from indicators import _compute_indicators_numpy
from config import SECTOR_ETF_MAPPING, CHANNEL_BREAKOUT_CONFIG
import pandas as pd
import numpy as np
import scoring_system as SS
from weekly_rebalance import SECTOR_TO_ETF


# ══════════════════════════════════════════════════════════════
# 参数网格
# ══════════════════════════════════════════════════════════════
PARAM_GRID_TOP_N = [3, 5, 7, 10, 13, 15]
PARAM_GRID_ENTRY = [30, 35, 40, 45, 50, 55]
PARAM_GRID_EXIT = [25, 30, 35, 40, 45]
PARAM_GRID_FORCE_CASH = [30, 35, 40, 45, 50]


# ══════════════════════════════════════════════════════════════
# Step 1: 加载数据 + 预计算所有周三的评分
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


def find_wednesdays(all_data):
    first = list(all_data.keys())[0]
    klines = all_data[first]['klines']
    wednesdays = []
    for i in range(60, len(klines)):
        ds = str(klines[i].get('date', ''))
        try:
            dt = datetime.strptime(ds, '%Y%m%d')
            if dt.weekday() == 2:
                wednesdays.append((ds, i))
        except:
            continue
    return wednesdays


def precompute_scores(all_data, wednesdays):
    """预计算所有周三所有行业的评分结果。

    Returns:
        cached: {week_idx: [{'sector','total','direction','grade','etf_code','price'}, ...]}
        price_data: {sector: [close_prices]}
    """
    cached = {}
    price_data = {s: [] for s in all_data}

    n = len(wednesdays)
    for w_idx, (date_str, data_idx) in enumerate(wednesdays):
        if w_idx % 30 == 0:
            print(f'    评分预计算 [{w_idx}/{n}]...')

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
            prev_close = float(df['close'].iloc[-2]) if len(df) > 1 else price
            change_pct = round((price / prev_close - 1) * 100, 2)

            sym = {'last_price': price}
            sc = SS.calculate_composite_score(tech, sym)

            week_scores.append({
                'sector': sector,
                'etf_code': dinfo['code'],
                'total': sc['total'],
                'direction': sc['direction'],
                'grade': sc['grade'],
                'price': price,
                'change_pct': change_pct,
            })

        cached[w_idx] = week_scores

        # 收集价格数据
        for sector in all_data:
            klines = all_data[sector]['klines']
            if data_idx < len(klines):
                price_data[sector].append(float(klines[data_idx]['close']))

    return cached, price_data


# ══════════════════════════════════════════════════════════════
# Step 2: 用缓存评分模拟调仓 + 计算绩效
# ══════════════════════════════════════════════════════════════

def simulate_with_params(cached_scores, wednesdays, all_data,
                          top_n, entry_th, exit_th, force_cash_th):
    """用指定参数运行完整回测，返回绩效指标。"""
    current_holdings = {}
    entry_prices = {}  # {sector: float} — 每个仓位实际入场时的次日开盘价
    equity_curve = [1.0]
    returns = []

    for w_idx, (date_str, data_idx) in enumerate(wednesdays):
        scores = cached_scores.get(w_idx, [])

        # ---- 调仓计算 ----
        bull_sorted = sorted(
            [s for s in scores if s['direction'] == 'bull'],
            key=lambda x: x['total'], reverse=True
        )

        # force_cash 检测
        max_bull = max((s['total'] for s in bull_sorted), default=0)
        if max_bull < force_cash_th:
            # 强制空仓 — 先结算旧仓位收益再清仓
            week_return = _calc_week_return(current_holdings, entry_prices, all_data, data_idx)
            returns.append(week_return)
            equity_curve.append(equity_curve[-1] * (1 + week_return))
            current_holdings = {}
            entry_prices = {}
            continue

        # 候选池
        target_pool = []
        for r in bull_sorted:
            if len(target_pool) >= top_n:
                break
            if r['total'] > entry_th:
                target_pool.append(r['sector'])

        target_set = set(target_pool)
        all_scores_map = {s['sector']: s['total'] for s in scores}

        # 判定持仓
        to_keep = set()
        for sector in list(current_holdings.keys()):
            in_target = sector in target_set
            score = all_scores_map.get(sector, 0)
            rank = next((i+1 for i, r in enumerate(bull_sorted) if r['sector'] == sector), 999)

            if in_target:
                to_keep.add(sector)
            elif rank > top_n and score < exit_th:
                continue  # sell
            else:
                to_keep.add(sector)  # hold (only one condition met)

        # 新开仓
        new_buys = [s for s in target_pool if s not in to_keep]

        # 仓位计算
        kept_allocation = sum(current_holdings.get(s, 0) for s in to_keep)
        remaining = max(0.0, 1.0 - kept_allocation)

        new_positions = {}
        for s in to_keep:
            new_positions[s] = current_holdings.get(s, 0)
        if new_buys and remaining > 0:
            per = round(remaining / len(new_buys), 4)
            for s in new_buys:
                new_positions[s] = per

        # 微调至100%
        total = sum(new_positions.values())
        if abs(total - 1.0) > 0.001 and new_positions:
            last = list(new_positions.keys())[-1]
            new_positions[last] = round(new_positions[last] + (1.0 - total), 4)

        # ---- 收益计算（旧仓位：实际入场价 → 本周四开盘退出） ----
        week_return = _calc_week_return(current_holdings, entry_prices, all_data, data_idx)
        returns.append(week_return)
        equity_curve.append(equity_curve[-1] * (1 + week_return))

        # 记录新仓位的入场价（本周四开盘）
        new_entry_prices = {}
        for s in new_positions:
            klines = all_data.get(s, {}).get('klines', [])
            if klines and data_idx + 1 < len(klines):
                ep = float(klines[data_idx + 1].get('open', 0))
                if ep > 0:
                    new_entry_prices[s] = ep

        # 更新持仓
        current_holdings = new_positions
        entry_prices = new_entry_prices

    return _calc_metrics(returns, equity_curve)


def _calc_week_return(holdings, entry_prices, all_data, data_idx):
    """计算旧持仓从实际入场价到当前调仓日次日开盘的收益。"""
    if not holdings:
        return 0.0

    week_return = 0.0
    for sector, alloc in holdings.items():
        bp = entry_prices.get(sector, 0)  # 上次调仓日次日开盘 = 实际入场价
        if bp == 0:
            continue

        klines = all_data.get(sector, {}).get('klines', [])
        if not klines:
            continue

        # 退出价 = 当前调仓日次日开盘
        sell_idx = data_idx + 1
        if sell_idx >= len(klines):
            continue
        sell_price = float(klines[sell_idx].get('open', 0))
        if sell_price == 0:
            continue

        sector_return = (sell_price - bp) / bp
        week_return += alloc * sector_return

    return week_return


def _calc_metrics(returns, equity):
    """计算绩效指标。"""
    n = len(returns)
    if n == 0:
        return {'sharpe': 0, 'total_return': 0, 'max_drawdown': 0,
                'calmar': 0, 'win_rate': 0, 'profit_factor': 0}

    total_ret = equity[-1] - 1.0
    n_years = n / 52.0
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    std_weekly = stdev(returns) if len(returns) > 1 else 0
    ann_vol = std_weekly * math.sqrt(52)

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
    win_rate = len(wins) / n if n > 0 else 0
    avg_win = mean(wins) if wins else 0
    avg_loss = abs(mean(losses)) if losses else 0
    pf = (len(wins) * avg_win) / (len(losses) * avg_loss) if (losses and avg_loss > 0) else 0

    return {
        'sharpe': round(sharpe, 3),
        'total_return': round(total_ret * 100, 2),
        'annual_return': round(ann_ret * 100, 2),
        'annual_vol': round(ann_vol * 100, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'calmar': round(calmar, 3),
        'win_rate': round(win_rate * 100, 1),
        'avg_weekly_return': round(mean(returns) * 100, 3),
        'profit_factor': round(pf, 2),
        'n_weeks': n,
    }


# ══════════════════════════════════════════════════════════════
# Step 3: 网格搜索 + 平原分析
# ══════════════════════════════════════════════════════════════

def find_plateau(all_results, metric='sharpe', tol=0.05):
    """分析参数平原：找出夏普/卡玛变化<tol的连续参数区域。

    all_results: [{'top_n':..., 'entry':..., 'exit':..., 'force_cash':..., 'sharpe':..., ...}, ...]

    Returns:
        {
            'best': best_result,
            'plateau_top_n': (low, high) or None,
            'plateau_entry': (low, high) or None,
            'plateau_exit': (low, high) or None,
            'plateau_force_cash': (low, high) or None,
        }
    """
    if not all_results:
        return {'best': None}

    best = max(all_results, key=lambda x: x.get(metric, 0))
    best_val = best.get(metric, 0)
    threshold = best_val - tol

    # 找出所有与最佳值差距<tol的参数组合
    good = [r for r in all_results if r.get(metric, 0) >= threshold]

    def _find_range(values, good_set):
        """找出连续值范围。"""
        sorted_vals = sorted(set(values))
        good_vals = [v for v in sorted_vals if v in good_set]
        if not good_vals:
            return None
        # 找连续区间
        ranges = []
        start = good_vals[0]
        end = good_vals[0]
        for v in good_vals[1:]:
            if v == end + 1 or abs(v - end) <= 2:  # 允许2的间隔
                end = v
            else:
                ranges.append((start, end))
                start = v
                end = v
        ranges.append((start, end))
        # 返回最长范围
        return max(ranges, key=lambda x: x[1] - x[0])

    good_top_n = set(r['top_n'] for r in good)
    good_entry = set(r['entry'] for r in good)
    good_exit = set(r['exit'] for r in good)
    good_force = set(r['force_cash'] for r in good)

    return {
        'best': best,
        'best_val': best_val,
        'threshold': best_val - tol,
        'n_good': len(good),
        'n_total': len(all_results),
        'plateau_top_n': _find_range(PARAM_GRID_TOP_N, good_top_n),
        'plateau_entry': _find_range(PARAM_GRID_ENTRY, good_entry),
        'plateau_exit': _find_range(PARAM_GRID_EXIT, good_exit),
        'plateau_force_cash': _find_range(PARAM_GRID_FORCE_CASH, good_force),
        'best_single_param': {
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
    print(f'{"="*60}')
    print(f'周频调仓参数网格优化 v1.0')
    print(f'日期: {date.today()}')
    print(f'{"="*60}')

    # Step 1: 加载数据
    print('\n[1] 加载3年日线数据...')
    all_data = load_data(days=750)
    print(f'  共 {len(all_data)} 个行业')

    # Step 2: 确定周三日期
    wednesdays = find_wednesdays(all_data)
    print(f'  找到 {len(wednesdays)} 个周三')

    # Step 3: 预计算评分（耗时约2-3分钟，只做一次）
    print(f'\n[2] 预计算所有周三评分...')
    cached_scores, _ = precompute_scores(all_data, wednesdays)
    print(f'  完成: {len(cached_scores)} 周 × {len(all_data)} 行业')

    # Step 4: 网格搜索
    print(f'\n[3] 网格搜索...')
    param_names = ['top_n', 'entry', 'exit', 'force_cash']
    grid_values = [PARAM_GRID_TOP_N, PARAM_GRID_ENTRY, PARAM_GRID_EXIT, PARAM_GRID_FORCE_CASH]
    total_combos = len(PARAM_GRID_TOP_N) * len(PARAM_GRID_ENTRY) * len(PARAM_GRID_EXIT) * len(PARAM_GRID_FORCE_CASH)
    print(f'  总组合数: {total_combos}')

    all_results = []
    idx = 0
    for top_n in PARAM_GRID_TOP_N:
        for entry in PARAM_GRID_ENTRY:
            for exit_th in PARAM_GRID_EXIT:
                for force in PARAM_GRID_FORCE_CASH:
                    idx += 1
                    metrics = simulate_with_params(
                        cached_scores, wednesdays, all_data,
                        top_n, entry, exit_th, force
                    )

                    r = {
                        'top_n': top_n,
                        'entry': entry,
                        'exit': exit_th,
                        'force_cash': force,
                        'sharpe': metrics['sharpe'],
                        'total_return': metrics['total_return'],
                        'annual_return': metrics['annual_return'],
                        'max_drawdown': metrics['max_drawdown'],
                        'calmar': metrics['calmar'],
                        'win_rate': metrics['win_rate'],
                        'profit_factor': metrics['profit_factor'],
                    }
                    all_results.append(r)

                    if idx % 60 == 0 or idx == total_combos:
                        print(f'    [{idx}/{total_combos}] TOP_N={top_n} ENTRY={entry} '
                              f'EXIT={exit_th} FC={force} → Sharpe={metrics["sharpe"]:.3f} '
                              f'Ret={metrics["total_return"]:+.1f}% DD={metrics["max_drawdown"]:.1f}%')

    # Step 5: 平原分析
    print(f'\n[4] 平原分析 (夏普差距<0.05)...')
    plateau = find_plateau(all_results, metric='sharpe', tol=0.05)

    best = plateau['best']

    print(f'\n{"="*60}')
    print(f'📊 优化结果')
    print(f'{"="*60}')
    print(f'\n🏆 最优参数组合:')
    print(f'  TOP_N = {best["top_n"]}')
    print(f'  SCORE_ENTRY_THRESHOLD = {best["entry"]}')
    print(f'  SCORE_EXIT_THRESHOLD = {best["exit"]}')
    print(f'  FORCE_CASH_THRESHOLD = {best["force_cash"]}')
    print(f'')
    print(f'  夏普比率:     {best["sharpe"]:.3f}')
    print(f'  年化收益:     {best["annual_return"]:+.2f}%')
    print(f'  最大回撤:     {best["max_drawdown"]:.2f}%')
    print(f'  卡玛比率:     {best["calmar"]:.3f}')
    print(f'  胜率:         {best["win_rate"]:.1f}%')

    # 平原范围
    print(f'\n📐 参数平原 (夏普≥{plateau["threshold"]:.3f}):')
    for name, key in [('TOP_N', 'plateau_top_n'), ('ENTRY', 'plateau_entry'),
                       ('EXIT', 'plateau_exit'), ('FORCE_CASH', 'plateau_force_cash')]:
        pr = plateau.get(key)
        if pr:
            print(f'  {name:<15}: {pr[0]} ~ {pr[1]} (推荐区间)')
        else:
            print(f'  {name:<15}: 无宽平原')
    print(f'  候选组合: {plateau["n_good"]}/{plateau["n_total"]} 组在平原内')

    # Top 10
    sorted_results = sorted(all_results, key=lambda x: x['sharpe'], reverse=True)
    print(f'\n🏅 Top 10 参数组合:')
    print(f'{"#":>3} {"TOP_N":>5} {"ENTRY":>6} {"EXIT":>5} {"FC":>5} {"Sharpe":>7} {"年化%":>7} {"回撤%":>7} {"卡玛":>6} {"胜率":>5}')
    print('-' * 58)
    for i, r in enumerate(sorted_results[:10], 1):
        print(f'{i:>3} {r["top_n"]:>5} {r["entry"]:>6} {r["exit"]:>5} {r["force_cash"]:>5} '
              f'{r["sharpe"]:>7.3f} {r["annual_return"]:>+6.1f} {r["max_drawdown"]:>6.1f} '
              f'{r["calmar"]:>6.3f} {r["win_rate"]:>5.1f}')

    # 按参数维度汇总
    print(f'\n📈 按参数维度汇总 (平均夏普):')
    for param_name, values, key in [
        ('TOP_N', PARAM_GRID_TOP_N, 'top_n'),
        ('ENTRY', PARAM_GRID_ENTRY, 'entry'),
        ('EXIT', PARAM_GRID_EXIT, 'exit'),
        ('FORCE_CASH', PARAM_GRID_FORCE_CASH, 'force_cash'),
    ]:
        print(f'  {param_name}:', end='')
        for v in values:
            vals = [r['sharpe'] for r in all_results if r[key] == v]
            avg_s = mean(vals) if vals else 0
            print(f' {v}={avg_s:.3f}', end='')
        print()

    # 保存
    output = {
        'date': str(date.today()),
        'grid_params': {
            'top_n': PARAM_GRID_TOP_N,
            'entry': PARAM_GRID_ENTRY,
            'exit': PARAM_GRID_EXIT,
            'force_cash': PARAM_GRID_FORCE_CASH,
        },
        'plateau': plateau,
        'top10': sorted_results[:10],
        'n_total': len(all_results),
    }

    out_path = os.path.join(BACKTEST_DIR, 'results',
                            f'optimize_params_{date.today().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n📊 结果已保存: {out_path}')


if __name__ == '__main__':
    main()
