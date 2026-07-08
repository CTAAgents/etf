# -*- coding: utf-8 -*-
"""报告生成（通道突破策略 v2.1 · 纯多头模式）：Markdown + HTML。"""

import time
from typing import List, Dict


def generate_markdown_report(results: List[dict], etf_data: dict = None,
                              data_source: str = 'tdx') -> str:
    """生成Markdown报告（纯多头模式）。"""
    date_str = time.strftime('%Y-%m-%d')

    lines = [
        f'# ETF多头信号报告（通道突破策略）',
        '',
        f'**日期**：{date_str}',
        f'**数据来源**：{data_source}',
        f'**分析逻辑**：Layer A唐奇安通道(75%) + Layer B布林带(25%) + 成交量确认 | 纯多头模式',
        '',
    ]

    # 一、信号总览
    lines.extend(['## 一、信号总览', ''])
    lines.append(f'- 扫描行业ETF：{len(results)}个')
    lines.append(f'- 多头信号：{len(results)}个')
    lines.append(f'- 注：ETF只做多，空头信号已过滤')
    lines.append('')

    if not results:
        lines.append('⚠️ **今日无任何多头信号**')
        lines.append('')
        return '\n'.join(lines)

    # 二、Top信号
    lines.extend(['## 二、Top信号（按总分降序）', ''])
    lines.append('| 排名 | 行业 | 价格 | 总分 | DC20 | DC55 | BB | VOL | ADX | RSI | Z | DC趋势 | 信号类型 | 等级 |')
    lines.append('|:----:|------|-----:|:----:|:----:|:----:|:---:|:---:|:---:|:---:|:--:|:------:|:--------:|:----:|')
    for i, r in enumerate(results[:15], 1):
        lines.append(
            f"| {i} | {r.get('sector','?')} | {r.get('price',0):.2f} | "
            f"{r.get('total',0):+.0f} | {r.get('dc20',0):+.0f} | {r.get('dc55',0):+.0f} | "
            f"{r.get('bb',0):+.0f} | {r.get('vol_score',0):+.0f} | "
            f"{r.get('adx',0):.1f} | {r.get('rsi',0):.1f} | {r.get('z_score',0):.1f} | "
            f"{r.get('dc55_trend','?')} | {r.get('signal_type','?')} | {r.get('grade','NOISE')} |"
        )
    lines.append('')

    # 三、通道指标摘要
    lines.extend(['## 三、通道指标摘要', ''])
    dc20_up = sum(1 for r in results if r.get('dc20_break') == 'up')
    dc55_up = sum(1 for r in results if r.get('dc55_trend') == 'up')
    bb_squeeze_cnt = sum(1 for r in results if r.get('bb_squeeze'))
    lines.append(f'- DC20突破向上：{dc20_up}个')
    lines.append(f'- DC55趋势向上：{dc55_up}个')
    lines.append(f'- 布林带挤压：{bb_squeeze_cnt}个')
    lines.append('')

    # 四、操作建议
    lines.extend(['## 四、操作建议', ''])
    strong_signals = [r for r in results if r.get('grade') == 'STRONG']
    if strong_signals:
        lines.append(f'**STRONG信号（{len(strong_signals)}个）** — 建议进入辩论流程确认：')
        for r in strong_signals[:5]:
            lines.append(f'  - {r.get("sector","?")} ({r.get("etf_code","")}) 总分{r.get("total",0):+.0f} 信号类型={r.get("signal_type","?")}')
        lines.append('')
    lines.append('> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议。')
    lines.append('> T+1市场，建议尾盘决断入场，避免盘中追高。')
    lines.append(f'> 通道突破策略 v2.1 | 纯多头模式 | 通达信TQ-Local | STRONG≥50进入辩论')

    return '\n'.join(lines)


def generate_html_report(results: List[dict], etf_data: dict = None,
                          data_source: str = 'tdx') -> str:
    """生成HTML可视化报告（纯多头模式）。"""
    import json as _json

    date_str = time.strftime('%Y-%m-%d')

    rows = ''
    for i, r in enumerate(results[:20], 1):
        gc = '#22c55e' if r.get('grade') == 'STRONG' else ('#f59e0b' if r.get('grade') == 'WATCH' else ('#ef4444' if r.get('grade') == 'WEAK' else '#6b7280'))
        st = r.get('signal_type', '?')
        st_cls = 'st-bo' if st == 'channel_breakout' else ('st-tc' if st == 'trend_confirmation' else ('st-sq' if st == 'bb_squeeze_prebreakout' else 'st-ms'))

        rows += (
            f'<div class="tp-card">'
            f'<div class="tp-header">'
            f'<span class="tp-rank">#{i}</span>'
            f'<strong>{r.get("sector","?")}</strong>'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:{gc}30;color:{gc}">{r.get("grade","?")}</span>'
            f'<span class="{st_cls}">{st}</span>'
            f'<span style="font-size:12px;color:#9ca3af">总分: <span style="font-weight:600;color:#22c55e">+{r.get("total",0):.0f}</span></span>'
            f'</div>'
            f'<div class="tp-body">'
            f'<div class="tp-scores">'
            f'DC20={r.get("dc20",0):+.0f} DC55={r.get("dc55",0):+.0f} BB={r.get("bb",0):+.0f} VOL={r.get("vol_score",0):+.0f}'
            f'</div>'
            f'<div class="tp-meta">'
            f'<span>价格: {r.get("price",0):.2f}</span>'
            f'<span>涨跌: {r.get("change_pct",0):+.1f}%</span>'
            f'<span>ADX: {r.get("adx",0):.1f}</span>'
            f'<span>RSI: {r.get("rsi",0):.1f}</span>'
            f'<span>β: {r.get("beta",1.0):.2f}</span>'
            f'<span>DC55趋势: {r.get("dc55_trend","?")}</span>'
            f'</div></div></div>\n'
        )

    if not rows:
        rows = '<div class="tp-card"><strong>⚠️ 今日无任何多头信号</strong></div>'

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>ETF多头信号报告 - {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:1200px;margin:0 auto;padding:24px;background:#0f172a;color:#e2e8f0}}
.header{{background:linear-gradient(135deg,#1e293b,#334155);padding:32px;border-radius:16px;margin-bottom:24px;border:1px solid #475569}}
.header h1{{font-size:28px;margin:0 0 8px;color:#22c55e}}
.header p{{color:#94a3b8;margin:4px 0}}
.stat{{background:rgba(255,255,255,0.05);padding:16px;border-radius:12px;text-align:center;border:1px solid #334155}}
.stat .num{{font-size:28px;font-weight:bold;color:#22c55e}}
.stat .label{{font-size:13px;color:#94a3b8;margin-top:4px}}
.tp-card{{background:#1e293b;padding:16px;border-radius:12px;margin-bottom:12px;border:1px solid #334155;border-left:4px solid #22c55e}}
.tp-header{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.tp-rank{{background:#475569;color:#f8fafc;padding:2px 10px;border-radius:8px;font-weight:bold;font-size:14px}}
.st-bo{{font-size:10px;padding:2px 6px;border-radius:4px;background:#22c55e30;color:#22c55e;font-weight:600}}
.st-tc{{font-size:10px;padding:2px 6px;border-radius:4px;background:#f59e0b30;color:#f59e0b;font-weight:600}}
.st-sq{{font-size:10px;padding:2px 6px;border-radius:4px;background:#3b82f630;color:#3b82f6;font-weight:600}}
.st-ms{{font-size:10px;padding:2px 6px;border-radius:4px;background:#6b728030;color:#6b7280;font-weight:600}}
.tp-body{{margin-top:10px}}
.tp-scores{{display:flex;gap:16px;font-size:14px;color:#cbd5e1;font-family:monospace}}
.tp-meta{{display:flex;gap:16px;font-size:12px;color:#94a3b8;margin-top:6px;flex-wrap:wrap}}
.disclaimer{{color:#64748b;font-size:13px;padding:16px;border-top:1px solid #334155;margin-top:24px}}
.chart-row{{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px}}
.chart-card{{background:#1e293b;padding:24px;border-radius:12px;border:1px solid #334155}}
.chart-card h2{{margin:0 0 16px;font-size:18px;color:#f8fafc}}
.canvas-container{{position:relative;width:100%;height:300px}}
canvas{{max-height:300px}}
</style></head><body>
<div class="header">
<h1>📈 ETF多头信号报告（通道突破策略）</h1>
<p>日期：{date_str} | 数据来源：{data_source}</p>
<p>纯多头模式 | Layer A唐奇安通道(75%) + Layer B布林带(25%) + 成交量确认 | 空头已过滤</p>
<div class="stat"><div class="num">{len(results)}</div><div class="label">多头信号</div></div>
</div>

<h2>🎯 多头信号排名</h2>
{rows}

<div class="disclaimer">⚠️ 以上内容由 AI 基于公开信息自动分析生成，仅供参考，不构成任何投资建议。<br>
通道突破策略 v2.1 · 纯多头模式 | T+1尾盘决断 | STRONG≥50进入辩论流程 | 空头信号不纳入输出</div>
</body></html>'''
