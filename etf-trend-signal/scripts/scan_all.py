#!/usr/bin/env python3
"""
ETF通道突破策略全行业扫描 v2.3 — 纯多头模式
===================================================
独立调用：python scan_all.py [--output <dir>] [--source westock|tdx]

数据源：腾讯自选股 westock-mcp（默认，前复权日线）| 通达信TQ-Local（--source tdx）
评分：Layer A唐奇安通道(75%) + Layer B布林带(25%) + 成交量确认
输出：JSON + HTML报表（仅多头信号）

ETF只能做多，空头信号仅用于降级参考，不纳入输出。
"""
import sys, os, json, numpy as np, pandas as pd
from datetime import date, datetime

# ── 路径自举 ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))

for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts.indicators import _compute_indicators_numpy, assess_trend_maturity
    from scripts.scoring_system import calculate_composite_score
    from scripts.config import SECTOR_ETF_MAPPING, SECTOR_NAMES
    from scripts.collect_data import EtfDataCollector
    from scripts.sector_rotation import compute_sector_relative_strength
except ImportError:
    from indicators import _compute_indicators_numpy, assess_trend_maturity
    from scoring_system import calculate_composite_score
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES
    from collect_data import EtfDataCollector
    from sector_rotation import compute_sector_relative_strength


def collect_all_etf_klines(collector: EtfDataCollector, symbols: list = None):
    """采集所有ETF的K线数据。"""
    mapping = symbols if symbols is not None else SECTOR_ETF_MAPPING
    print("\n[1] ETF数据采集...")
    etf_data = {}
    for i, (sector_name, _, etf_code, etf_name, _) in enumerate(mapping):
        klines = collector.get_etf_klines(sector_name, etf_code, days=180)
        if klines and len(klines) >= 50:
            etf_data[sector_name] = {
                'etf_code': etf_code,
                'etf_name': etf_name,
                'klines': klines,
                'last_price': klines[-1]['close'],
                'change_pct': round((klines[-1]['close'] / klines[-2]['close'] - 1) * 100, 2) if len(klines) > 1 else 0,
                'volume': klines[-1].get('volume', 0),
            }
        else:
            print(f"  [SKIP] {sector_name} ({etf_code}) K线数据不足")

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(SECTOR_ETF_MAPPING)}] {len(etf_data)} OK")

    print(f"  完成: {len(etf_data)}/{len(SECTOR_ETF_MAPPING)} 个ETF")
    return etf_data


def run_scan(output_dir: str = None, output_prefix: str = "etf_scan", symbols: list = None,
             source: str = 'westock', cache_path: str = None) -> dict:
    """执行全行业ETF扫描（纯多头模式·通道突破策略 v2.3）。"""
    today = date.today()
    today_str = today.strftime('%Y%m%d')

    source_label = '腾讯自选股 westock-mcp' if source == 'westock' else '通达信TQ-Local'

    if symbols:
        quick_names = [s[0] for s in symbols]
        print(f"{'='*60}")
        print(f"ETF通道突破策略扫描 v2.3 — {today} (快速模式: {len(symbols)}/{len(SECTOR_ETF_MAPPING)}个)")
        print(f"数据源: {source_label}")
    else:
        print(f"{'='*60}")
        print(f"ETF通道突破策略扫描 v2.3 — {today} (全{len(SECTOR_ETF_MAPPING)}行业)")
        print(f"数据源: {source_label}")
        print(f"{'='*60}")

    # Step 1: 数据采集
    collector = EtfDataCollector(source=source, cache_path=cache_path)
    etf_data = collect_all_etf_klines(collector, symbols=symbols)

    if not etf_data:
        print("[ERROR] 无有效数据")
        return {'_meta': {'date': today_str, 'total': 0, 'bull': 0},
                'bull_signals': [], 'all_ranked': []}

    # Step 2: 指标计算 + 通道突破评分
    print('\n[2] 指标计算 + 通道突破评分...')

    # 沪深300收益率（通达信）
    bench_closes = collector.get_benchmark_closes()

    results = []
    for sector_name, data in etf_data.items():
        try:
            klines = data['klines']
            df = pd.DataFrame({k: [float(r[k]) for r in klines] for k in ['open', 'high', 'low', 'close']})
            df['volume'] = [float(r.get('volume', 0)) for r in klines]

            tech = _compute_indicators_numpy(df, sector_name)
            if not tech or 'RSI14' not in tech:
                continue

            price = tech.get('last_price', float(df['close'].iloc[-1]))
            tech['price'] = price

            # 行业相对强度
            closes_list = df['close'].tolist()
            rel_strength = compute_sector_relative_strength(closes_list,
                bench_closes[-len(closes_list):] if len(bench_closes) >= len(closes_list) else bench_closes)
            tech['SECTOR_RELATIVE_STRENGTH'] = rel_strength.get('relative_strength', 1.0)
            tech['SECTOR_BETA'] = rel_strength.get('beta_20d', 1.0)

            # 通道突破评分
            sym_scoring = {'last_price': price}
            sc = calculate_composite_score(tech, sym_scoring)

            direction = sc['direction']

            # 纯多头模式：只保留bull信号，其余全部跳过
            if direction != 'bull':
                continue

            results.append(dict(
                sector=sector_name,
                etf_code=data['etf_code'],
                etf_name=data.get('etf_name', ''),
                price=round(price, 3),
                change_pct=data.get('change_pct', 0),
                volume=data.get('volume', 0),
                total=sc['total'],
                abs=abs(sc['total']),
                direction=direction,
                grade=sc['grade'],
                signal_type=sc['signal_type'],
                # 子层分数
                dc20=sc['sub_scores']['dc20'],
                dc55=sc['sub_scores']['dc55'],
                bb=sc['sub_scores']['bb'],
                vol_score=sc['sub_scores']['vol'],
                # 技术指标
                adx=round(tech.get('ADX', 0), 1),
                atr=round(tech.get('ATR14', 0), 2),
                rsi=round(tech.get('RSI14', 0), 1),
                cci=round(tech.get('CCI20', 0), 1),
                z_score=sc['z_score'],
                # 通道指标
                dc20_break=sc['dc20_break'],
                dc55_pos=round(sc['dc55_pos'], 3) if sc['dc55_pos'] else 0,
                dc55_trend=sc['dc55_trend'],
                bb_width_pct=sc['bb_width_pct'],
                bb_squeeze=sc['bb_squeeze'],
                bb_pos=sc['bb_pos'],
                vol_ratio=sc['vol_ratio'],
                ma_slope=tech.get('MA20_SLOPE', 0),
                # 行业指标
                beta=round(rel_strength.get('beta_20d', 1.0), 2),
                # 评分原因
                reasons=sc['reasons'],
            ))
        except Exception as e:
            pass

        if (len(results)) % 10 == 0 and len(results) > 0:
            print(f'  [{len(results)}] 完成')

    # ===== Phase 3: 多头信号排名 =====
    print(f'\n[3] 多头信号排序...')
    all_ranked = sorted(results, key=lambda x: x['total'], reverse=True)

    # 多头方向Z-score（基于同向信号）
    from statistics import mean, stdev
    bull_totals = [r['total'] for r in results if r['total'] > 0]
    mu_bull, sigma_bull = (mean(bull_totals), stdev(bull_totals)) if len(bull_totals) > 1 else (None, None)
    for r in all_ranked:
        if sigma_bull and sigma_bull > 0:
            r['z_score'] = round((r['total'] - mu_bull) / sigma_bull, 2)
        else:
            r['z_score'] = 0.0

    summary = {
        '_meta': {
            'date': today_str, 'total': len(results), 'bull': len(results),
            'source': source_label, 'strategy': 'channel_breakout_v2.3',
            'version': '2.3.0',
            'mode': 'bull_only',
        },
        'bull_signals': all_ranked,
        'all_ranked': all_ranked,
    }

    print(f'\n完成: 扫描{len(etf_data)}行业ETF | 多头信号{len(results)}个')

    if len(results) == 0:
        print(f'\n⚠️ 今日无任何多头信号，全市场为空头/中性')
    else:
        # 终端表格
        print(f'\n{"#":>3} {"行业":<8} {"价格":>8} {"涨跌":>6} {"总分":>5} {"DC55":>5} {"BB":>4} {"VOL":>4} {"ADX":>5} {"RSI":>5} {"Z":>5} {"DC趋势":>4} {"信号类型":>18} {"等级":>6}')
        print('-' * 100)
        for i, r in enumerate(all_ranked):
            st = r.get('signal_type', '?')
            print(f'{i+1:>3} {r["sector"]:<8} {r["price"]:>8.2f} {r["change_pct"]:>+5.1f}% {r["total"]:>+4.0f} {r["dc55"]:>+4.0f} {r["bb"]:>+3.0f} {r["vol_score"]:>+3.0f} {r["adx"]:>5.1f} {r["rsi"]:>5.1f} {r["z_score"]:>5.1f} {r.get("dc55_trend","?"):>4} {st:>18} {r["grade"]:>6}')

    # 写入文件
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, f'{output_prefix}_{today_str}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n📊 JSON: {json_path}')

        # HTML报表（纯多头）
        import json as _json
        rows_json = _json.dumps([{
            'i': i+1, 'sector': r['sector'], 'code': r.get('etf_code',''),
            'price': r['price'], 'chg': r['change_pct'],
            'total': r['total'],
            'dc20': r['dc20'], 'dc55': r['dc55'], 'bb': r['bb'], 'vol': r['vol_score'],
            'adx': r['adx'], 'rsi': r['rsi'], 'z': r['z_score'],
            'dc55_t': r.get('dc55_trend','?'), 'stype': r.get('signal_type','?'),
            'beta': r.get('beta', 1.0), 'grade': r['grade'],
            'bb_w': round(r.get('bb_width_pct',0) or 0, 2),
            'dc55_p': r.get('dc55_pos',0),
            'vr': round(r.get('vol_ratio',1.0), 2),
        } for r in all_ranked], ensure_ascii=False)

        has_signals = len(all_ranked) > 0

        html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>ETF多头信号 — {today} (v2.3)</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0f1117;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px}}
.hd{{background:linear-gradient(135deg,#1a1d28,#252940);border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid #2a2d3a}}
.hd h1{{font-size:22px;color:#22c55e}} .hd .m{{color:#9ca3af;font-size:12px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
.hd .m span{{background:#252940;padding:3px 10px;border-radius:5px}}
.st{{display:flex;gap:14px;margin-bottom:20px}}
.sc{{flex:1;background:#1a1d28;border-radius:10px;padding:14px 18px;border:1px solid #2a2d3a;text-align:center}}
.sc .n{{font-size:26px;font-weight:700;color:#22c55e}} .sc .l{{font-size:11px;color:#9ca3af;margin-top:3px}}
table{{width:100%;border-collapse:collapse;background:#1a1d28;border-radius:10px;overflow:hidden;border:1px solid #2a2d3a;font-size:13px}}
thead{{background:#252940}}
th{{padding:9px 10px;text-align:left;font-weight:600;color:#9ca3af;font-size:11px;letter-spacing:.5px;white-space:nowrap;cursor:pointer;user-select:none;transition:color .15s}}
th:hover{{color:#22c55e}} th.asc::after{{content:" \\25B2";font-size:10px}} th.dsc::after{{content:" \\25BC";font-size:10px}}
td{{padding:7px 10px;border-top:1px solid #2a2d3a20;white-space:nowrap}} tr:hover{{background:#22c55e08!important}}
.no-sig{{text-align:center;padding:40px;color:#6b7280;font-size:16px}}
</style>
</head><body>
<div class="hd"><h1>📈 ETF多头信号 (v2.1 · 纯多头模式)</h1>
<div class="m"><span>{today}</span><span>{len(results)}个多头</span>
<span>通达信TQ-Local</span><span>唐奇安通道(75%) + 布林带(25%) + 成交量确认</span></div></div>
<div class="st"><div class="sc"><div class="n">{len(results)}</div><div class="l">多头信号</div></div></div>

''' + (f'''
<table id="tbl"><thead><tr>
<th onclick="sortBy(0)" data-num="1">#</th>
<th onclick="sortBy(1)">行业</th>
<th onclick="sortBy(2)" data-num="1" style="text-align:right">价格</th>
<th onclick="sortBy(3)" data-num="1" style="text-align:right">涨跌</th>
<th onclick="sortBy(4)" data-num="1" style="text-align:center">总分</th>
<th onclick="sortBy(5)" data-num="1" style="text-align:center">DC20</th>
<th onclick="sortBy(6)" data-num="1" style="text-align:center">DC55</th>
<th onclick="sortBy(7)" data-num="1" style="text-align:center">BB</th>
<th onclick="sortBy(8)" data-num="1" style="text-align:center">VOL</th>
<th onclick="sortBy(9)" data-num="1" style="text-align:center">ADX</th>
<th onclick="sortBy(10)" data-num="1" style="text-align:center">RSI</th>
<th onclick="sortBy(11)" data-num="1" style="text-align:center">Z</th>
<th onclick="sortBy(12)">DC趋势</th>
<th onclick="sortBy(13)">信号类型</th>
<th onclick="sortBy(14)">等级</th>
</tr></thead><tbody id="tb"></tbody></table>

<script>
var DATA = {rows_json};
var _filter = 'all';
var _sortCol = -1;
var _sortAsc = true;

function _gc(g) {{
    if (g==='STRONG') return '#22c55e';
    if (g==='WATCH') return '#f59e0b';
    if (g==='WEAK') return '#ef4444';
    return '#6b7280';
}}

function render() {{
    var data = DATA.slice();
    if (_sortCol >= 0) {{
        var asc = _sortAsc;
        data.sort(function(a,b){{
            var va = _val(a,_sortCol), vb = _val(b,_sortCol);
            if (typeof va === 'string') return asc ? va.localeCompare(vb) : vb.localeCompare(va);
            return asc ? (va - vb) : (vb - va);
        }});
    }}
    var h = '';
    for (var i=0;i<data.length;i++) {{
        var d = data[i];
        var cc = d.chg>0?'#22c55e':(d.chg<0?'#ef4444':'#9ca3af');
        var tc = '#22c55e';
        var bg = _gc(d.grade) + '15';
        var st_clr = d.stype==='channel_breakout'?'#22c55e':(d.stype==='trend_confirmation'?'#f59e0b':(d.stype==='bb_squeeze_prebreakout'?'#3b82f6':'#6b7280'));
        h += '<tr style="background:'+bg+'">';
        h += '<td style="text-align:center;color:#9ca3af">'+(i+1)+'</td>';
        h += '<td style="font-weight:700">'+d.sector+'</td>';
        h += '<td style="text-align:right">'+d.price.toFixed(2)+'</td><td style="text-align:right;color:'+cc+'">'+(d.chg>0?'+':'')+d.chg.toFixed(1)+'%</td>';
        h += '<td style="text-align:center;font-weight:700;color:'+tc+'">+'+d.total+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.dc20>0?'+':'')+d.dc20+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.dc55>0?'+':'')+d.dc55+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.bb>0?'+':'')+d.bb+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.vol>0?'+':'')+d.vol+'</td>';
        h += '<td style="text-align:center">'+d.adx.toFixed(1)+'</td><td style="text-align:center">'+d.rsi.toFixed(1)+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.z>0?'+':'')+d.z.toFixed(1)+'</td>';
        var dc_t = '<span style="color:'+(d.dc55_t==='up'?'#22c55e':(d.dc55_t==='down'?'#ef4444':'#6b7280'))+'">'+d.dc55_t+'</span>';
        h += '<td style="text-align:center">'+dc_t+'</td>';
        h += '<td style="text-align:center"><span style="padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;background:'+st_clr+'30;color:'+st_clr+'">'+d.stype+'</span></td>';
        h += '<td style="text-align:center"><span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:'+_gc(d.grade)+'30;color:'+_gc(d.grade)+'">'+d.grade+'</span></td></tr>';
    }}
    document.getElementById('tb').innerHTML = h;
}}

function _val(d,col) {{
    var a = [d.i, d.sector, d.price, d.chg, d.total, d.dc20, d.dc55, d.bb, d.vol,
             d.adx, d.rsi, d.z, d.dc55_t, d.stype, d.grade];
    return a[col];
}}

function sortBy(col) {{
    if (_sortCol === col) {{ _sortAsc = !_sortAsc; }}
    else {{ _sortCol = col; _sortAsc = col===0 ? true : false; }}
    var ths = document.querySelectorAll('#tbl th');
    for (var i=0;i<ths.length;i++) ths[i].className = '';
    var el = ths[col];
    if (el) el.className = _sortAsc ? 'asc' : 'dsc';
    render();
}}

render();
</script>''' if has_signals else '''
<div class="no-sig">⚠️ 今日无任何多头信号，全市场为空头/中性</div>''') + '''
<div style="margin-top:24px;display:flex;gap:14px">
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #22c55e30">
<span style="color:#22c55e;font-weight:600">纯多头模式: </span>
<span style="color:#e5e7eb">ETF只做多，空头信号自动过滤。Layer A唐奇安通道(75%) → Layer B布林带(25%) → 成交量确认</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">DC20短期突破(30%) + DC55中期趋势(26.25%) + BB确认(25%) + 成交量(独立) | STRONG≥50进入辩论</p></div>
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #2a2d3a">
<span style="color:#22c55e;font-weight:600">数据: </span><span style="color:#e5e7eb">通达信TQ-Local（纯本地数据）</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">etf-trend-signal v2.1.0 | {today} | 纯多头模式 | 纯TDX | 空头信号不纳入输出</p></div></div>
</body></html>'''
        html_path = os.path.join(output_dir, f'{output_prefix}_bull_{today_str}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'✅ HTML: {html_path}')

    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='ETF通道突破策略扫描 v2.2 — 纯多头模式（默认腾讯自选股）')
    parser.add_argument('--output', '-o', help='输出目录', default=None)
    parser.add_argument('--prefix', '-p', help='文件名前缀', default='etf_bull')
    parser.add_argument('--quick', '-q', type=int, default=0,
                        help='快速模式：只扫描前N个行业')
    parser.add_argument('--source', '-s', default='westock', choices=['westock', 'tdx'],
                       help='数据源（默认westock）')
    parser.add_argument('--cache', help='westock缓存文件路径')
    args = parser.parse_args()

    OUT = args.output
    if not OUT:
        OUT = os.path.join(SKILL_DIR, '..', 'Reports',
                           date.today().strftime('%Y-%m-%d'))

    target_symbols = None
    if args.quick > 0:
        q = min(args.quick, len(SECTOR_ETF_MAPPING))
        target_symbols = SECTOR_ETF_MAPPING[:q]
        print(f"\n⚡ 快速模式: 仅扫描前{q}个行业 ({[s[0] for s in target_symbols]})")

    run_scan(output_dir=OUT, output_prefix=args.prefix, symbols=target_symbols,
             source=args.source, cache_path=args.cache)
