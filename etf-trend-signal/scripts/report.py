# -*- coding: utf-8 -*-
"""报告生成（ETF版）：Markdown + HTML。"""

import time
from typing import List, Dict


def generate_markdown_report(results: List[dict], etf_data: dict = None,
                              data_source: str = 'akshare') -> str:
    """生成Markdown报告（ETF行业轮动版）。"""
    date_str = time.strftime('%Y-%m-%d')
    bull = [r for r in results if r.get('direction') == 'bull']
    bear = [r for r in results if r.get('direction') == 'bear']

    lines = [
        f'# 行业ETF趋势信号报告（行业轮动）',
        '',
        f'**日期**：{date_str}',
        f'**数据来源**：{data_source}',
        f'**分析逻辑**：L1-L4四层打分(ETF版) + 行业轮动Rank',
        '',
    ]

    # 一、信号总览
    lines.extend(['## 一、信号总览', ''])
    lines.append(f'- 扫描行业ETF：{len(results)}个')
    lines.append(f'- 多头信号：{len(bull)}个')
    lines.append(f'- 空头信号：{len(bear)}个')
    lines.append('')

    # 二、Top信号
    lines.extend(['## 二、Top信号（按总分排序）', ''])
    if results:
        lines.append('| 排名 | 行业 | 方向 | 价格 | 总分 | L1 | L2 | L3 | L4 | 否决 | ADX | RSI | Z | 阶段 | 等级 |')
        lines.append('|:----:|------|:----:|-----:|:----:|:--:|:--:|:--:|:--:|:----:|:---:|:---:|:--:|:----:|:----:|')
        for i, r in enumerate(results[:15], 1):
            d = '📗多' if r.get('direction') == 'bull' else ('📕空' if r.get('direction') == 'bear' else '⚪中')
            lines.append(
                f"| {i} | {r.get('sector','?')} | {d} | {r.get('price',0):.2f} | "
                f"{r.get('total',0):+.0f} | {r.get('l1',0):+d} | {r.get('l2',0):+d} | "
                f"{r.get('l3',0):+d} | {r.get('l4',0):+d} | {r.get('veto',0):+d} | "
                f"{r.get('adx',0):.1f} | {r.get('rsi',0):.1f} | {r.get('z_score',0):.1f} | "
                f"{r.get('stage','?')} | {r.get('grade','NOISE')} |"
            )
    lines.append('')

    # 三、ETF专属信号
    lines.extend(['## 三、ETF专属信号摘要', ''])
    premium_sectors = []
    share_surge_sectors = []
    nb_inflow_sectors = []

    for r in results:
        if r.get('iopv_premium', 0) > 1.0:
            premium_sectors.append(r['sector'])
    if premium_sectors:
        lines.append(f'- 🔥 IOPV溢价行业: {", ".join(premium_sectors)}')
    else:
        lines.append('- IOPV折溢价正常，无过热/恐慌')

    lines.append('')

    # 四、行业轮动建议
    lines.extend(['## 四、行业轮动建议', ''])
    lines.append('基于L1-L4综合评分 + β过滤(>1.1)排名。')
    lines.append('')
    lines.append('> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议。')
    lines.append('> T+1市场，建议尾盘决断入场，避免盘中追高。')

    return '\n'.join(lines)


def generate_html_report(results: List[dict], etf_data: dict = None,
                          data_source: str = 'akshare') -> str:
    """生成HTML可视化报告（ETF版）。"""
    import json as _json

    date_str = time.strftime('%Y-%m-%d')
    bull = [r for r in results if r.get('direction') == 'bull']
    bear = [r for r in results if r.get('direction') == 'bear']

    rows = ''
    for i, r in enumerate(results[:20], 1):
        cls = 'sell' if r.get('direction') == 'bear' else ('buy' if r.get('direction') == 'bull' else 'hold')
        d = '做空' if r.get('direction') == 'bear' else '做多'
        tc = '#22c55e' if r.get('total', 0) > 0 else ('#ef4444' if r.get('total', 0) < 0 else '#f59e0b')
        gc = '#22c55e' if r.get('grade') == 'STRONG' else ('#f59e0b' if r.get('grade') == 'WATCH' else ('#ef4444' if r.get('grade') == 'WEAK' else '#6b7280'))

        rows += (
            f'<div class="tp-card {cls}">'
            f'<div class="tp-header">'
            f'<span class="tp-rank">#{i}</span>'
            f'<strong>{r.get("sector","?")}</strong>'
            f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:{gc}30;color:{gc}">{r.get("grade","?")}</span>'
            f'<span class="tp-dir">{d}</span>'
            f'<span style="font-size:12px;color:#9ca3af">总分: <span style="font-weight:600;color:{tc}">{r.get("total",0):+.0f}</span></span>'
            f'</div>'
            f'<div class="tp-body">'
            f'<div class="tp-scores">'
            f'L1={r.get("l1",0):+d} L2={r.get("l2",0):+d} L3={r.get("l3",0):+d} L4={r.get("l4",0):+d} 否决={r.get("veto",0):+d}'
            f'</div>'
            f'<div class="tp-meta">'
            f'<span>价格: {r.get("price",0):.2f}</span>'
            f'<span>涨跌: {r.get("change_pct",0):+.1f}%</span>'
            f'<span>ADX: {r.get("adx",0):.1f}</span>'
            f'<span>RSI: {r.get("rsi",0):.1f}</span>'
            f'<span>β: {r.get("beta",1.0):.2f}</span>'
            f'<span>阶段: {r.get("stage","?")}</span>'
            f'</div></div></div>\n'
        )

    if not rows:
        rows = '<div class="tp-card hold"><strong>今日无有效信号</strong></div>'

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>行业ETF趋势信号报告 - {date_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:1200px;margin:0 auto;padding:24px;background:#0f172a;color:#e2e8f0}}
.header{{background:linear-gradient(135deg,#1e293b,#334155);padding:32px;border-radius:16px;margin-bottom:24px;border:1px solid #475569}}
.header h1{{font-size:28px;margin:0 0 8px;color:#f8fafc}}
.header p{{color:#94a3b8;margin:4px 0}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:16px}}
.stat{{background:rgba(255,255,255,0.05);padding:16px;border-radius:12px;text-align:center;border:1px solid #334155}}
.stat .num{{font-size:28px;font-weight:bold;color:#f8fafc}}
.stat .label{{font-size:13px;color:#94a3b8;margin-top:4px}}
.tp-card{{background:#1e293b;padding:16px;border-radius:12px;margin-bottom:12px;border:1px solid #334155}}
.tp-card.sell{{border-left:4px solid #ef4444}}.tp-card.buy{{border-left:4px solid #22c55e}}.tp-card.hold{{border-left:4px solid #f59e0b}}
.tp-header{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.tp-rank{{background:#475569;color:#f8fafc;padding:2px 10px;border-radius:8px;font-weight:bold;font-size:14px}}
.tp-dir{{font-weight:bold;font-size:15px}}
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
<h1>📊 行业ETF趋势信号报告（行业轮动）</h1>
<p>日期：{date_str} | 数据来源：{data_source}</p>
<p>L1-L4四层打分(ETF版) | 份额/IOPV/北向/融资 | 行业轮动Rank | 扫描：{len(results)}行业</p>
<div class="stats">
<div class="stat"><div class="num">{len(results)}</div><div class="label">扫描行业</div></div>
<div class="stat"><div class="num" style="color:#22c55e">{len(bull)}</div><div class="label">多头信号</div></div>
<div class="stat"><div class="num" style="color:#ef4444">{len(bear)}</div><div class="label">空头信号</div></div>
<div class="stat"><div class="num" style="color:#f59e0b">{len(results)-len(bull)-len(bear)}</div><div class="label">中性</div></div>
</div></div>

<div class="chart-row">
<div class="chart-card"><h2>📊 行业评分分布</h2>
<canvas id="scoreChart"></canvas></div>
<div class="chart-card"><h2>📈 多头/空头占比</h2>
<canvas id="pieChart"></canvas></div>
</div>

<h2 style="margin-top:32px">🎯 信号排名（Top20）</h2>
{rows}

<div class="disclaimer">⚠️ 以上内容由 AI 基于公开信息自动分析生成，仅供参考，不构成任何投资建议。<br>
T+1市场注意：尾盘决断入场，跌破MA20减半仓，尾盘确认后清仓。</div>
<script>
new Chart(document.getElementById('scoreChart').getContext('2d'),{{
  type:'bar',
  data:{{
    labels:{_json.dumps([r.get('sector','')[:4] for r in results], ensure_ascii=False)},
    datasets:[{{
      label:'总分',
      data:{_json.dumps([r.get('total',0) for r in results])},
      backgroundColor:function(ctx){{return ctx.raw>0?'#22c55e80':'#ef444480'}},
      borderColor:function(ctx){{return ctx.raw>0?'#22c55e':'#ef4444'}},
      borderWidth:1
    }}]
  }},
  options:{{
    responsive:true,
    maintainAspectRatio:false,
    scales:{{
      y:{{grid:{{color:'#334155'}},ticks:{{color:'#94a3b8'}}}},
      x:{{grid:{{color:'#334155'}},ticks:{{color:'#94a3b8',maxRotation:45}}}}
    }},
    plugins:{{legend:{{display:false}}}}
  }}
}});
new Chart(document.getElementById('pieChart').getContext('2d'),{{
  type:'doughnut',
  data:{{
    labels:['多头','空头','中性'],
    datasets:[{{
      data:[{len(bull)},{len(bear)},{len(results)-len(bull)-len(bear)}],
      backgroundColor:['#22c55e','#ef4444','#f59e0b']
    }}]
  }},
  options:{{
    plugins:{{legend:{{position:'bottom',labels:{{color:'#94a3b8'}}}}}}
  }}
}});
</script></body></html>'''
