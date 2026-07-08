#!/usr/bin/env python3
"""
调仓频率优化 + TOP_N 网格搜索 v1.0
=====================================
固定参数：ENTRY=55, EXIT=30, FC=35（之前900组搜索最优）
优化维度：调仓频率（日/周/双周/月）× TOP_N

流程：
1. 预计算所有交易日的评分数据（一次计算，≈20分钟）
2. 对每种频率选择对应的调仓日期
3. 对每种频率网格搜索最优 TOP_N
4. 报告每种频率的最佳绩效及对比
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
from config import SECTOR_ETF_MAPPING
import pandas as pd
import numpy as np
import scoring_system as SS

# 固定参数（之前优化结果）
ENTRY_TH = 55
EXIT_TH = 30
FC_TH = 35

# TOP_N 搜索范围（适配不同频率）
TOP_N_GRID = [1, 2, 3, 4, 5, 7, 10, 13, 15]

# 频率定义
FREQUENCIES = {
    'daily':   {'label': '日频',    'weekday': None},    # 每交易日
    'weekly':  {'label': '周频',    'weekday': 2},       # 每周三
    'biweekly':{'label': '双周频',  'weekday': 2},       # 每隔一个周三
    'monthly': {'label': '月频',    'weekday': None},    # 每月最后一个周三
}


# ══════════════════════════════════════════════════════════════
# 数据加载 + 评分预计算
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


def get_all_dates(all_data):
    """获取所有交易日的日期列表和索引。"""
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


def precompute_all_scores(all_data, dates):
    """预计算所有交易日的评分。

    耗时约10-15分钟（750天×31行业）。
    """
    n = len(dates)
    cached = {}

    for idx, (date_str, data_idx, wkday) in enumerate(dates):
        if idx < 60:  # need at least 60 bars
            continue
        if idx % 100 == 0:
            print(f'    评分预计算 [{idx}/{n}] ({(idx/n)*100:.0f}%)...')

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
                'sector': sector,
                'etf_code': dinfo['code'],
                'total': sc['total'],
                'direction': sc['direction'],
                'grade': sc['grade'],
                'price': price,
            })

        cached[idx] = week_scores

    return cached


# ══════════════════════════════════════════════════════════════
# 调仓日期选择
# ══════════════════════════════════════════════════════════════

def select_rebalance_dates(dates, freq):
    """根据频率选择调仓日期索引。"""
    selected = []

    if freq == 'daily':
        # 每交易日（从第60天起）
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60:
                selected.append((ds, idx, i))

    elif freq == 'weekly':
        # 每���三
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60 and wkday == 2:
                selected.append((ds, idx, i))

    elif freq == 'biweekly':
        # 每隔一个周三
        count = 0
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60 and wkday == 2:
                if count % 2 == 0:
                    selected.append((ds, idx, i))
                count += 1

    elif freq == 'monthly':
        # 每月最后一个周三
        from collections import defaultdict
        month_candidates = defaultdict(list)
        for i, (ds, idx, wkday) in enumerate(dates):
            if i >= 60 and wkday == 2:
                # 使用日期字符串的前6位 (YYYYMM)
                ym = ds[:6]
                month_candidates[ym].append((ds, idx, i))
        # 取每个月的最后一条（最后一个周三）
        for ym, entries in sorted(month_candidates.items()):
            selected.append(entries[-1])

    return selected


# ══════════════════════════════════════════════════════════════
# 组合模拟
# ══════════════════════════════════════════════════════════════

def simulate(cached_scores, all_data, all_dates, rebalance_dates, top_n):
    """用指定频率和TOP_N运行组合模拟。

    rebalance_dates: [(date_str, data_idx, cache_idx), ...]
    """
    current_holdings = {}
    entry_prices = {}  # {sector: float} — 每个仓位实际入场时的次日开盘价
    equity_curve = [1.0]
    returns = []

    for r_idx in range(len(rebalance_dates)):
        date_str, data_idx, cache_idx = rebalance_dates[r_idx]
        scores = cached_scores.get(cache_idx, [])
        if not scores:
            continue

        # ---- 调仓计算 ----
        bull_sorted = sorted(
            [s for s in scores if s['direction'] == 'bull'],
            key=lambda x: x['total'], reverse=True
        )

        # force_cash
        max_bull = max((s['total'] for s in bull_sorted), default=0)
        if max_bull < FC_TH:
            week_ret = _calc_return(current_holdings, entry_prices, all_data, data_idx)
            returns.append(week_ret)
            equity_curve.append(equity_curve[-1] * (1 + week_ret))
            current_holdings = {}
            entry_prices = {}
            continue

        # 候选池
        target_pool = []
        for r in bull_sorted:
            if len(target_pool) >= top_n:
                break
            if r['total'] > ENTRY_TH:
                target_pool.append(r['sector'])

        target_set = set(target_pool)
        all_scores_map = {s['sector']: s['total'] for s in scores}

        # 持仓判定
        to_keep = set()
        for sector in list(current_holdings.keys()):
            in_target = sector in target_set
            score = all_scores_map.get(sector, 0)
            rank = next((i+1 for i, r in enumerate(bull_sorted) if r['sector'] == sector), 999)

            if in_target:
                to_keep.add(sector)
            elif rank > top_n and score < EXIT_TH:
                continue
            else:
                to_keep.add(sector)

        # 新开仓
        new_buys = [s for s in target_pool if s not in to_keep]

        # 仓位
        kept_alloc = sum(current_holdings.get(s, 0) for s in to_keep)
        remaining = max(0.0, 1.0 - kept_alloc)

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

        # 收益（旧仓位：实际入场价 → 当前调仓日次日开盘退出）
        week_ret = _calc_return(current_holdings, entry_prices, all_data, data_idx)
        returns.append(week_ret)
        equity_curve.append(equity_curve[-1] * (1 + week_ret))

        # 记录新仓位的入场价（当前调仓日次日开盘）
        new_entry_prices = {}
        for s in new_positions:
            klines = all_data.get(s, {}).get('klines', [])
            if klines and data_idx + 1 < len(klines):
                ep = float(klines[data_idx + 1].get('open', 0))
                if ep > 0:
                    new_entry_prices[s] = ep

        current_holdings = new_positions
        entry_prices = new_entry_prices

    return _calc_metrics(returns, equity_curve)


def _calc_return(holdings, entry_prices, all_data, data_idx):
    """计算旧持仓从实际入场价到当前调仓日次日开盘的收益。"""
    if not holdings:
        return 0.0

    week_ret = 0.0
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
        sp = float(klines[sell_idx].get('open', 0))
        if sp == 0:
            continue

        sector_ret = (sp - bp) / bp
        week_ret += alloc * sector_ret

    return week_ret


def _calc_metrics(returns, equity):
    n = len(returns)
    if n == 0:
        return {'sharpe': 0, 'total_return': 0, 'max_drawdown': 0,
                'calmar': 0, 'win_rate': 0, 'n_trades': 0, 'n_weeks': 0}

    total_ret = equity[-1] - 1.0
    n_years = n / 252.0  # 按交易日年化
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
    win_rate = len(wins) / max(n, 1)
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
        'avg_return': round(mean(returns) * 100, 3),
        'profit_factor': round(pf, 2),
        'n_periods': n,
    }


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main():
    print(f'{"="*60}')
    print(f'调仓频率 × TOP_N 网格优化 v1.0')
    print(f'固定参数: ENTRY={ENTRY_TH}  EXIT={EXIT_TH}  FC={FC_TH}')
    print(f'优化维度: 日频/周频/双周频/月频 × TOP_N={TOP_N_GRID}')
    print(f'日期: {date.today()}')
    print(f'{"="*60}')

    # Step 1: 加载数据
    print('\n[1] 加载3年日线数据...')
    all_data = load_data(days=750)
    print(f'  共 {len(all_data)} 个行业')

    all_dates = get_all_dates(all_data)
    print(f'  共 {len(all_dates)} 个交易日')

    # Step 2: 预计算评分
    print(f'\n[2] 预计算所有交易日评分...')
    cached = precompute_all_scores(all_data, all_dates)
    n_scored = len(cached)
    print(f'  完成: {n_scored} 个交易日 × {len(all_data)} 行业')

    # Step 3: 对每种频率做 TOP_N 网格搜索
    print(f'\n[3] 运行网格搜索...')
    all_freq_results = {}

    for freq_key, freq_info in FREQUENCIES.items():
        label = freq_info['label']

        # 选择调仓日期
        rebal_dates = select_rebalance_dates(all_dates, freq_key)
        print(f'\n  ── {label} ({len(rebal_dates)}次调仓) ──')

        freq_results = []
        for top_n in TOP_N_GRID:
            metrics = simulate(cached, all_data, all_dates, rebal_dates, top_n)

            freq_results.append({
                'top_n': top_n,
                'sharpe': metrics['sharpe'],
                'total_return': metrics['total_return'],
                'annual_return': metrics['annual_return'],
                'max_drawdown': metrics['max_drawdown'],
                'calmar': metrics['calmar'],
                'win_rate': metrics['win_rate'],
                'profit_factor': metrics['profit_factor'],
                'n_periods': metrics['n_periods'],
            })

            print(f'    TOP_N={top_n:>2}: Sharpe={metrics["sharpe"]:.3f}  '
                  f'年化={metrics["annual_return"]:+.1f}%  '
                  f'回撤={metrics["max_drawdown"]:.1f}%  '
                  f'卡玛={metrics["calmar"]:.3f}')

        # 排序
        freq_results.sort(key=lambda x: x['sharpe'], reverse=True)
        all_freq_results[freq_key] = {
            'label': label,
            'n_rebalances': len(rebal_dates),
            'results': freq_results,
            'best': freq_results[0],
        }

    # Step 4: 输出对比
    print(f'\n{"="*60}')
    print(f'📊 各频率最优对比')
    print(f'{"="*60}')
    print(f'\n{"频率":<8} {"TOP_N":>5} {"Sharpe":>7} {"年化%":>7} {"回撤%":>7} {"卡玛":>6} {"胜率":>5} {"调仓":>5}')
    print('-' * 52)

    summary = []
    for freq_key in ['daily', 'weekly', 'biweekly', 'monthly']:
        info = all_freq_results[freq_key]
        b = info['best']
        print(f'{info["label"]:<8} {b["top_n"]:>5} {b["sharpe"]:>7.3f} '
              f'{b["annual_return"]:>+6.1f} {b["max_drawdown"]:>6.1f} '
              f'{b["calmar"]:>6.3f} {b["win_rate"]:>5.1f} {info["n_rebalances"]:>5}')
        summary.append({
            'freq': freq_key,
            'label': info['label'],
            'best_top_n': b['top_n'],
            'sharpe': b['sharpe'],
            'annual_return': b['annual_return'],
            'max_drawdown': b['max_drawdown'],
            'calmar': b['calmar'],
            'win_rate': b['win_rate'],
            'n_rebalances': info['n_rebalances'],
        })

    # 推荐
    print(f'\n🏆 综合推荐:')
    best_freq = max(summary, key=lambda x: x['sharpe'])
    print(f'  {best_freq["label"]}调仓 (TOP_N={best_freq["best_top_n"]}): '
          f'Sharpe={best_freq["sharpe"]:.3f}, 年化={best_freq["annual_return"]:+.1f}%, '
          f'回撤={best_freq["max_drawdown"]:.1f}%')

    # 保存
    output = {
        'date': str(date.today()),
        'fixed_params': {'entry': ENTRY_TH, 'exit': EXIT_TH, 'force_cash': FC_TH},
        'top_n_grid': TOP_N_GRID,
        'frequencies': summary,
        'freq_details': all_freq_results,
    }

    out_path = os.path.join(BACKTEST_DIR, 'results',
                            f'optimize_freq_{date.today().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n📊 结果已保存: {out_path}')


if __name__ == '__main__':
    main()
