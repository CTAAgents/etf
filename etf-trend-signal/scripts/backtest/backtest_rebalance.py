#!/usr/bin/env python3
"""
周频调仓策略3年回测 v1.0
=============================
基于通道突破策略信号，模拟每周三收盘计算→周四开盘执行的全流程。

回测周期：2023-06 ~ 2026-07（约3年，750个交易日）
数据源：通达信TQ-Local

策略规则已在 weekly_rebalance.py 中定义，本脚本直接复用其 compute_rebalance 逻辑。
"""
import sys, os, json, math, copy
from datetime import date, datetime, timedelta
from statistics import mean, stdev

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
from weekly_rebalance import compute_rebalance, TOP_N, SCORE_ENTRY_THRESHOLD, SCORE_EXIT_THRESHOLD


# ══════════════════════════════════════════════════════════════
# 数据准备
# ══════════════════════════════════════════════════════════════

def load_all_data(days: int = 750) -> dict:
    """加载所有行业的OHLCV日线数据。"""
    collector = EtfDataCollector()
    all_data = {}
    for s in SECTOR_ETF_MAPPING:
        sector = s[0]
        etf_code = s[2]
        klines = collector.get_etf_klines(sector, etf_code, days=days)
        if klines and len(klines) >= 100:
            all_data[sector] = {
                'code': etf_code,
                'klines': klines,
                'n': len(klines),
            }
            sys.stdout.write(f'  ✅ {sector:<8} ({etf_code:>10}): {len(klines):>3} bars\n')
        else:
            sys.stdout.write(f'  ⚠️ {sector:<8} ({etf_code:>10}): {len(klines) if klines else 0} bars (跳过)\n')
    return all_data


# ══════════════════════════════════════════════════════════════
# 日期工具
# ══════════════════════════════════════════════════════════════

def find_wednesdays(all_data: dict) -> list:
    """从数据中找出所有周三的日期索引。

    返回: [(日期字符串, 数据索引), ...]
    """
    # 取第一个有数据的行业的K线日期列表
    first_sector = list(all_data.keys())[0]
    first_klines = all_data[first_sector]['klines']

    wednesdays = []
    # 需要至少60根K线才能计算指标
    for i in range(60, len(first_klines)):
        date_str = first_klines[i].get('date', '')
        if not date_str:
            continue
        try:
            dt = datetime.strptime(str(date_str), '%Y%m%d')
            # Wednesday = 2 (Monday=0, Tuesday=1, Wednesday=2, ..., Sunday=6)
            if dt.weekday() == 2:
                wednesdays.append((date_str, i))
        except ValueError:
            continue

    return wednesdays


def thursday_open(klines: list, wed_idx: int) -> float:
    """获取周三后下一个交易日（周四）的开盘价。"""
    for j in range(wed_idx + 1, min(wed_idx + 5, len(klines))):
        return float(klines[j].get('open', 0))
    return float(klines[wed_idx].get('close', 0))  # fallback


# ══════════════════════════════════════════════════════════════
# 评分管线（单时间点）
# ══════════════════════════════════════════════════════════════

def score_at_date(all_data: dict, date_idx: int) -> list:
    """在指定日期索引对所有行业做评分。

    返回: [{'sector','total','direction','grade','etf_code','price','change_pct'}, ...]
    """
    results = []
    for sector, dinfo in all_data.items():
        klines = dinfo['klines']
        if date_idx >= len(klines):
            continue

        window = klines[:date_idx + 1]
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

        results.append({
            'sector': sector,
            'etf_code': dinfo['code'],
            'total': sc['total'],
            'direction': sc['direction'],
            'grade': sc['grade'],
            'signal_type': sc['signal_type'],
            'price': price,
            'change_pct': change_pct,
        })

    return results


# ══════════════════════════════════════════════════════════════
# 组合模拟
# ══════════════════════════════════════════════════════════════

def simulate_portfolio(all_data: dict, wednesdays: list) -> dict:
    """模拟3年周频调仓的全流程。

    Returns:
        {
            'weekly_returns': [{'week_start','return','positions'}, ...],
            'equity_curve': [1.0, 1.01, ...],
            'metrics': {...},
            'trades': [...],
        }
    """
    n_weeks = len(wednesdays)

    # 当前持仓 {sector: allocation_pct}
    current_holdings = {}
    # 入场价追踪 {sector: float} — 记录每个仓位实际入场时的次日开盘价
    entry_prices = {}
    equity_curve = [1.0]
    weekly_returns = []
    all_trades = []

    for w_idx, (date_str, data_idx) in enumerate(wednesdays):
        if w_idx % 20 == 0:
            print(f'  回放 [{w_idx}/{n_weeks}] {date_str}...')

        # Step 1: 评分
        scores = score_at_date(all_data, data_idx)

        # 组装成 scan_all 返回格式
        scan_result = {
            '_meta': {'date': date_str, 'total': len(scores), 'bull': sum(1 for s in scores if s['direction'] == 'bull')},
            'bull_signals': [s for s in scores if s['direction'] == 'bull'],
            'all_ranked': sorted(scores, key=lambda x: abs(x.get('total', 0)), reverse=True),
        }

        # Step 2: 调仓计算
        plan = compute_rebalance(scan_result, current_holdings)

        # Step 3: 计算本周收益（旧仓位：实际入场价 → 本周四开盘退出价）
        week_return = 0.0
        for sector, alloc in current_holdings.items():
            bp = entry_prices.get(sector, 0)  # 上周四开盘买入价
            if bp == 0:
                continue
            klines = all_data.get(sector, {}).get('klines', [])
            sp = thursday_open(klines, data_idx)  # 本周四开盘 = 退出价
            if sp == 0:
                continue
            sector_return = (sp - bp) / bp
            week_return += alloc * sector_return

        # 记录
        current_codes = {s: all_data.get(s, {}).get('code', '') for s in current_holdings}
        new_codes = {s: all_data.get(s, {}).get('code', '') for s in plan.get('final_positions', {})}
        weekly_returns.append({
            'week': date_str,
            'return': round(week_return, 6),
            'positions': dict(current_holdings),
            'position_codes': current_codes,
            'new_plan': {s: round(p, 4) for s, p in plan.get('final_positions', {}).items()},
            'new_plan_codes': new_codes,
        })

        # 更新净值
        new_equity = equity_curve[-1] * (1 + week_return)
        equity_curve.append(new_equity)

        # 记录交易
        for a in plan['actions']:
            sector_code = all_data.get(a['sector'], {}).get('code', '')
            all_trades.append({
                'week': date_str,
                'sector': a['sector'],
                'etf_code': sector_code,
                'action': a['action'],
                'old_pct': round(a.get('old_pct', 0), 4),
                'new_pct': round(a.get('new_pct', 0), 4),
                'reason': a['reason'],
            })

        # 记录新仓位的入场价（本周四开盘）
        entry_prices = {}
        for sector in plan.get('final_positions', {}).keys():
            klines = all_data.get(sector, {}).get('klines', [])
            ep = thursday_open(klines, data_idx)
            if ep > 0:
                entry_prices[sector] = ep

        # 更新持仓
        current_holdings = plan.get('final_positions', {})

    return {
        'weekly_returns': weekly_returns,
        'equity_curve': equity_curve,
        'trades': all_trades,
        'final_holdings': current_holdings,
    }


# ══════════════════════════════════════════════════════════════
# 绩效评估
# ══════════════════════════════════════════════════════════════

def compute_metrics(result: dict) -> dict:
    """计算绩效指标。"""
    first_week = result["weekly_returns"][0]["week"] if result["weekly_returns"] else "?"
    last_week = result["weekly_returns"][-1]["week"] if result["weekly_returns"] else "?"
    returns = [r['return'] for r in result['weekly_returns']]
    equity = result['equity_curve']
    trades = result['trades']

    n_weeks = len(returns)

    total_return = equity[-1] - 1.0
    n_years = n_weeks / 52.0
    annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

    # 年化波动率（周收益率的年化）
    weekly_std = stdev(returns) if len(returns) > 1 else 0
    annual_vol = weekly_std * math.sqrt(52)

    # Sharpe（无风险利率2%）
    rf_annual = 0.02
    excess_return = annual_return - rf_annual
    sharpe = excess_return / annual_vol if annual_vol > 0 else 0

    # 最大回撤
    peak = equity[0]
    max_drawdown = 0.0
    max_dd_start = 0
    max_dd_end = 0
    for i, e in enumerate(equity[1:], 1):
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_drawdown:
            max_drawdown = dd
            max_dd_start = i
            max_dd_end = i

    # 胜率
    win_weeks = sum(1 for r in returns if r > 0)
    loss_weeks = sum(1 for r in returns if r < 0)
    win_rate = win_weeks / n_weeks if n_weeks > 0 else 0

    avg_win = mean([r for r in returns if r > 0]) if win_weeks > 0 else 0
    avg_loss = abs(mean([r for r in returns if r < 0])) if loss_weeks > 0 else 0
    profit_factor = (win_weeks * avg_win) / (loss_weeks * avg_loss) if (loss_weeks > 0 and avg_loss > 0) else float('inf')

    # Calmar
    calmar = annual_return / max_drawdown if max_drawdown > 0 else 0

    # 交易统计
    buys = [t for t in trades if t['action'] == 'BUY']
    sells = [t for t in trades if t['action'] == 'SELL']
    holds = [t for t in trades if t['action'] == 'HOLD']

    return {
        'period': first_week + ' ~ ' + last_week,
        'n_weeks': n_weeks,
        'total_return': round(total_return * 100, 2),
        'annual_return': round(annual_return * 100, 2),
        'annual_volatility': round(annual_vol * 100, 2),
        'sharpe_ratio': round(sharpe, 3),
        'calmar_ratio': round(calmar, 3),
        'max_drawdown': round(max_drawdown * 100, 2),
        'win_rate': round(win_rate * 100, 1),
        'avg_weekly_return': round(mean(returns) * 100, 3),
        'avg_win_weekly': round(avg_win * 100, 2),
        'avg_loss_weekly': round(avg_loss * 100, 2),
        'profit_factor': round(profit_factor, 2),
        'n_trades': len(trades),
        'n_buys': len(buys),
        'n_sells': len(sells),
        'n_holds': len(holds),
        'final_cash_pct': round(1.0 - sum(result.get('final_holdings', {}).values()), 4),
    }


# ══════════════════════════════════════════════════════════════
# HTML 报告
# ══════════════════════════════════════════════════════════════

def generate_html_report(result: dict, metrics: dict, report_date: str, out_path: str):
    """生成完整的回测 HTML 报告，包含 ETF 代码。"""
    trades = result.get('trades', [])
    equity = result.get('equity_curve', [1.0])
    weekly = result.get('weekly_returns', [])

    # 交易表格行
    trade_rows = ''
    for t in trades[-50:]:  # 最近50笔
        etf_code = t.get('etf_code', '')
        trade_rows += f'''<tr>
            <td>{t['week']}</td>
            <td>{t['sector']}</td>
            <td><code>{etf_code}</code></td>
            <td class="action-{t['action']}">{t['action']}</td>
            <td>{t.get('old_pct', 0):.1%}</td>
            <td>{t.get('new_pct', 0):.1%}</td>
            <td style="font-size:12px;color:#888">{t.get('reason', '')}</td>
        </tr>'''

    # 持仓记录表格
    position_rows = ''
    for w in weekly[-20:]:  # 最近20周
        pos_items = []
        for s, a in w.get('positions', {}).items():
            code = w.get('position_codes', {}).get(s, '')
            pos_items.append(f'{s}<code style="font-size:11px">({code})</code> {a:.0%}')
        position_rows += f'''<tr>
            <td>{w['week']}</td>
            <td>{w['return']:+.3%}</td>
            <td>{'<br>'.join(pos_items) if pos_items else '<span style="color:#999">空仓</span>'}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>ETF周频调仓策略回测报告</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:1200px;margin:20px auto;padding:0 20px;background:#f5f5f5}}
.card{{background:#fff;border-radius:8px;padding:24px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,0.1)}}
h1{{color:#1a1a2e;margin:0}} h2{{color:#16213e;border-bottom:2px solid #e94560;padding-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#1a1a2e;color:#fff;font-weight:600}}
tr:hover{{background:#fafafa}}
.metrics-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.metric{{text-align:center;padding:12px;background:#f8f9fa;border-radius:6px}}
.metric .value{{font-size:24px;font-weight:bold;margin:4px 0}}
.metric .label{{font-size:12px;color:#666}}
.positive{{color:#e94560}} .negative{{color:#27ae60}}
.action-BUY{{color:#e94560;font-weight:bold}} .action-SELL{{color:#27ae60;font-weight:bold}} .action-HOLD{{color:#888}}
code{{background:#e8e8e8;padding:1px 6px;border-radius:3px;font-size:13px}}
.summary{{color:#666;font-size:13px;margin-top:16px}}
</style>
</head>
<body>
<h1>ETF周频调仓策略回测报告</h1>
<p class="summary">回测周期: {metrics['period']} | 生成时间: {report_date}</p>

<div class="card">
<h2>绩效指标</h2>
<div class="metrics-grid">
<div class="metric"><div class="label">累计收益</div><div class="value {'positive' if metrics['total_return'] > 0 else 'negative'}">{metrics['total_return']:+.2f}%</div></div>
<div class="metric"><div class="label">年化收益</div><div class="value {'positive' if metrics['annual_return'] > 0 else 'negative'}">{metrics['annual_return']:+.2f}%</div></div>
<div class="metric"><div class="label">夏普比率</div><div class="value">{metrics['sharpe_ratio']:.3f}</div></div>
<div class="metric"><div class="label">卡玛比率</div><div class="value">{metrics['calmar_ratio']:.3f}</div></div>
<div class="metric"><div class="label">最大回撤</div><div class="value negative">{metrics['max_drawdown']:.2f}%</div></div>
<div class="metric"><div class="label">年化波动</div><div class="value">{metrics['annual_volatility']:.2f}%</div></div>
<div class="metric"><div class="label">周胜率</div><div class="value">{metrics['win_rate']:.1f}%</div></div>
<div class="metric"><div class="label">盈亏比</div><div class="value">{metrics['profit_factor']:.2f}</div></div>
</div>
<div class="metrics-grid" style="margin-top:12px">
<div class="metric"><div class="label">交易次数</div><div class="value">{metrics['n_trades']}</div></div>
<div class="metric"><div class="label">BUY/SELL/HOLD</div><div class="value" style="font-size:16px">{metrics['n_buys']}/{metrics['n_sells']}/{metrics['n_holds']}</div></div>
<div class="metric"><div class="label">平均盈利周</div><div class="value positive" style="font-size:16px">{metrics['avg_win_weekly']:+.2f}%</div></div>
<div class="metric"><div class="label">平均亏损周</div><div class="value negative" style="font-size:16px">{metrics['avg_loss_weekly']:+.2f}%</div></div>
</div>
</div>

<div class="card">
<h2>调仓记录（最近50笔）</h2>
<table>
<tr><th>日期</th><th>行业</th><th>ETF代码</th><th>动作</th><th>旧仓位</th><th>新仓位</th><th>原因</th></tr>
{trade_rows or '<tr><td colspan="7" style="color:#999">无交易记录</td></tr>'}
</table>
</div>

<div class="card">
<h2>周持仓变化（最近20周）</h2>
<table>
<tr><th>日期</th><th>周收益</th><th>持仓（ETF代码）</th></tr>
{position_rows or '<tr><td colspan="3" style="color:#999">无持仓记录</td></tr>'}
</table>
</div>

<div class="card">
<h2>净值曲线</h2>
<div style="color:#666;font-size:13px">起始净值: {equity[0]:.3f} → 最终净值: {equity[-1]:.3f}</div>
<pre style="background:#1a1a2e;color:#0f0;padding:12px;border-radius:4px;overflow:auto;max-height:300px">
{chr(10).join(f'{i:4d}: {v:.4f}  {chr(9608)*max(1,int(v*40))}' for i, v in enumerate(equity) if i % 10 == 0)}
</pre>
</div>
</body>
</html>'''

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════

def main():
    print(f'{"="*60}')
    print(f'周频调仓策略3年回测 v1.0')
    print(f'日期: {date.today()}')
    print(f'{"="*60}')

    # Step 1: 加载数据
    print('\n[1] 加载3年日线数据...')
    all_data = load_all_data(days=750)
    if len(all_data) < 5:
        print('[ERROR] 有效数据不足')
        return
    print(f'  共 {len(all_data)} 个行业可用')

    # Step 2: 确定周三日期
    print('\n[2] 确定回测时间点...')
    wednesdays = find_wednesdays(all_data)
    print(f'  找到 {len(wednesdays)} 个周三 (约{len(wednesdays)/52:.1f}年)')
    if wednesdays:
        print(f'  范围: {wednesdays[0][0]} ~ {wednesdays[-1][0]}')

    # Step 3: 回测
    print(f'\n[3] 回放 {len(wednesdays)} 个周频调仓周期...')
    result = simulate_portfolio(all_data, wednesdays)

    # Step 4: 计算指标
    print(f'\n[4] 计算绩效指标...')
    metrics = compute_metrics(result)

    # Step 5: 输出
    print(f'\n{"="*60}')
    print(f'📊 周频调仓策略 3年回测绩效')
    print(f'{"="*60}')
    print(f'  回测周期: {metrics["period"]}')
    print(f'  调仓次数: {metrics["n_weeks"]}周')
    print(f'')
    print(f'  🔵 累计收益率:       {metrics["total_return"]:+.2f}%')
    print(f'  🔵 年化收益率:       {metrics["annual_return"]:+.2f}%')
    print(f'  🟠 年化波动率:       {metrics["annual_volatility"]:.2f}%')
    print(f'  🟢 夏普比率:         {metrics["sharpe_ratio"]:.3f}')
    print(f'  🟢 卡玛比率:         {metrics["calmar_ratio"]:.3f}')
    print(f'  🔴 最大回撤:         {metrics["max_drawdown"]:.2f}%')
    print(f'  🟢 胜率(周):         {metrics["win_rate"]:.1f}%')
    print(f'')
    print(f'  平均周收益:          {metrics["avg_weekly_return"]:+.3f}%')
    print(f'  平均盈利周:          {metrics["avg_win_weekly"]:+.2f}%')
    print(f'  平均亏损周:          {metrics["avg_loss_weekly"]:.2f}%')
    print(f'  盈亏比:              {metrics["profit_factor"]:.2f}')
    print(f'')
    print(f'  总交易次数:          {metrics["n_trades"]}次')
    print(f'  BUY/HOLD/SELL:       {metrics["n_buys"]}/{metrics["n_holds"]}/{metrics["n_sells"]}')
    print(f'  最终现金比例:        {metrics["final_cash_pct"]:.1%}')

    # 保存结果
    output = {
        'date': str(date.today()),
        'metrics': metrics,
        'equity_curve': result['equity_curve'],
        'weekly_returns': result['weekly_returns'],
        'trades': result['trades'],
    }

    out_path = os.path.join(BACKTEST_DIR, 'results',
                            f'backtest_rebalance_{date.today().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n  结果已保存: {out_path}')

    # 生成 HTML 报告
    html_path = os.path.join(BACKTEST_DIR, 'results',
                             f'backtest_rebalance_{date.today().strftime("%Y%m%d_%H%M%S")}.html')
    generate_html_report(result, metrics, str(date.today()), html_path)
    print(f'  HTML报告: {html_path}')
    print(f'\n📊 回测结果已保存: {out_path}')


if __name__ == '__main__':
    main()
