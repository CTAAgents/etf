#!/usr/bin/env python3
"""
全行业ETF趋势信号扫描 v1.0.0
================================
独立调用：python scan_all.py [--output <dir>]

数据源：通达信TQ-Local（纯本地数据，无AKShare依赖）
指标：etf-trend-signal L1-L4 + scoring_system.py 统一评分
输出：JSON + HTML报表

覆盖：申万一级31行业ETF
"""
import sys, os, json, numpy as np, pandas as pd
from datetime import date, datetime

# ── 路径自举 ──
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_ROOT = os.path.dirname(SKILL_DIR)

for p in [SKILL_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from scripts.indicators import _compute_indicators_numpy, assess_trend_maturity
    from scripts.scoring_system import calculate_composite_score
    from scripts.config import SECTOR_ETF_MAPPING, SECTOR_NAMES
    from scripts.collect_data import EtfDataCollector
    from scripts.early_signal import inject_etf_early_signals_to_tech
    from scripts.sector_rotation import compute_sector_relative_strength, rank_sectors
except ImportError:
    from indicators import _compute_indicators_numpy, assess_trend_maturity
    from scoring_system import calculate_composite_score
    from config import SECTOR_ETF_MAPPING, SECTOR_NAMES
    from collect_data import EtfDataCollector
    from early_signal import inject_etf_early_signals_to_tech
    from sector_rotation import compute_sector_relative_strength, rank_sectors


def collect_all_etf_klines(collector: EtfDataCollector):
    """采集所有ETF的K线数据（纯TDX）。"""
    print("\n[1] ETF数据采集...")
    etf_data = {}
    for i, (sector_name, _, etf_code, etf_name, _) in enumerate(SECTOR_ETF_MAPPING):
        klines = collector.get_etf_klines(sector_name, etf_code, days=180)
        if klines and len(klines) >= 50:
            premium = collector.get_etf_premium(etf_code)
            northbound = collector.get_northbound_signal(sector_name)
            md = collector.get_market_data()

            etf_data[sector_name] = {
                'etf_code': etf_code,
                'etf_name': etf_name,
                'klines': klines,
                'premium_data': premium,
                'northbound': northbound,
                'margin': md.get('margin', {}),
                'scale': md.get('scale', {}),
                'last_price': klines[-1]['close'],
                'change_pct': round((klines[-1]['close'] / klines[-2]['close'] - 1) * 100, 2) if len(klines) > 1 else 0,
            }
        else:
            print(f"  [SKIP] {sector_name} ({etf_code}) K线数据不足")

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(SECTOR_ETF_MAPPING)}] {len(etf_data)} OK")

    print(f"  完成: {len(etf_data)}/{len(SECTOR_ETF_MAPPING)} 个ETF")
    return etf_data



def run_scan(output_dir: str = None, output_prefix: str = "etf_scan") -> dict:
    """执行全行业ETF扫描。"""
    today = date.today()
    today_str = today.strftime('%Y%m%d')

    print(f"{'='*60}")
    print(f"行业ETF趋势信号扫描 v1.1.0 — {today}")
    print(f"{'='*60}")

    # Step 1: 数据采集（纯通达信TQ-Local）
    collector = EtfDataCollector()
    etf_data = collect_all_etf_klines(collector)

    if not etf_data:
        print("[ERROR] 无有效数据")
        return {'_meta': {'date': today_str, 'total': 0, 'bull': 0, 'bear': 0}, 'bull_signals': [], 'bear_signals': [], 'all_ranked': []}

    # Step 2: 指标计算 + L1-L4评分
    print('\n[2] 指标计算 + L1-L4评分...')

    # 沪深300收益率（通达信）
    bench_return = collector.get_benchmark_return()
    bench_closes = collector.get_benchmark_closes()
    bench_closes = [1.0, 1.0]

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

            # 注入ETF专属早期信号（纯TDX）
            etf_extra = {
                'premium_data': data.get('premium_data', {}),
                'northbound': data.get('northbound', {}),
                'margin': data.get('margin', {}),
                'scale': data.get('scale', {}),
            }
            tech = inject_etf_early_signals_to_tech(etf_extra, tech)

            # 行业相对强度（用TDX benchmark closes）
            closes_list = df['close'].tolist()
            rel_strength = compute_sector_relative_strength(closes_list,
                bench_closes[-len(closes_list):] if len(bench_closes) >= len(closes_list) else bench_closes)
            tech['SECTOR_RELATIVE_STRENGTH'] = rel_strength.get('relative_strength', 1.0)
            tech['SECTOR_BETA'] = rel_strength.get('beta_20d', 1.0)

            # 完整版评分
            sym_scoring = {'last_price': price}
            kline_closes = df['close'].tolist()
            sc = calculate_composite_score(tech, sym_scoring, 0, kline_closes, None,
                                            etf_data=etf_extra)

            direction = 'bull' if sc['direction'] == 'BUY' else ('bear' if sc['direction'] == 'SELL' else 'neutral')
            s = 1 if direction == 'bull' else (-1 if direction == 'bear' else 0)
            stage = sc['maturity']['stage']

            results.append(dict(
                sector=sector_name,
                etf_code=data['etf_code'],
                etf_name=data.get('etf_name', ''),
                price=round(price, 3),
                change_pct=data.get('change_pct', 0),
                total=sc['total'] * s,
                abs=sc['total'],
                l1=sc['L1_score'] * s,
                l2=sc['L2_score'] * s,
                l3=sc['L3_score'] * s,
                l4=sc['L4_score'] * s,
                veto=sc['veto_score'],
                direction=direction,
                grade=sc['grade'],
                adx=round(tech.get('ADX', 0), 1),
                rsi=round(tech.get('RSI14', 0), 1),
                cci=round(tech.get('CCI20', 0), 1),
                beta=round(rel_strength.get('beta_20d', 1.0), 2),
                share_change=round(tech.get('SHARE_CHANGE_PCT', 0), 2),
                iopv_premium=round(tech.get('IOPV_PREMIUM', 0), 2),
                northbound_5d=round(tech.get('NORTHBOUND_5D', 0), 0),
                stage=stage,
            ))
        except Exception as e:
            pass

        if (len(results)) % 10 == 0 and len(results) > 0:
            print(f'  [{len(results)}] 完成')

    # 排名
    all_ranked = sorted(results, key=lambda x: x['abs'], reverse=True)
    bull = [r for r in all_ranked if r['direction'] == 'bull']
    bear = [r for r in all_ranked if r['direction'] == 'bear']

    # 方向感知Z-score
    from statistics import mean, stdev
    bear_totals = [r['total'] for r in results if r['total'] < 0]
    bull_totals = [r['total'] for r in results if r['total'] > 0]
    mu_bear, sigma_bear = (mean(bear_totals), stdev(bear_totals)) if len(bear_totals) > 1 else (None, None)
    mu_bull, sigma_bull = (mean(bull_totals), stdev(bull_totals)) if len(bull_totals) > 1 else (None, None)
    for r in all_ranked:
        if r['direction'] == 'bear' and sigma_bear and sigma_bear > 0:
            r['z_score'] = round((r['total'] - mu_bear) / sigma_bear, 2)
        elif r['direction'] == 'bull' and sigma_bull and sigma_bull > 0:
            r['z_score'] = round((r['total'] - mu_bull) / sigma_bull, 2)
        else:
            r['z_score'] = 0.0
        layers = [r['l1'], r['l2'], r['l3'], r['l4']]
        cons = sum(1 for l in layers if (l > 0 and r['total'] > 0) or (l < 0 and r['total'] < 0))
        r['cons'] = cons

    summary = {
        '_meta': {'date': today_str, 'total': len(results), 'bull': len(bull), 'bear': len(bear),
                  'source': 'AKShare ETF数据', 'indicators': 'numpy v1.0.0',
                  'z_mode': 'directional'},
        'bull_signals': bull,
        'bear_signals': bear,
        'all_ranked': all_ranked,
    }

    print(f'\n完成: {len(results)}行业ETF | 多头{len(bull)} 空头{len(bear)}')

    # 终端表格
    print(f'\n{"#":>3} {"行业":<8} {"方向":<4} {"价格":>8} {"涨跌":>6} {"总分":>5} {"L1":>4} {"L2":>4} {"L3":>4} {"L4":>4} {"否决":>4} {"ADX":>5} {"RSI":>5} {"Z":>5} {"CONS":>4} {"β":>4} {"阶段":>8} {"等级":>6}')
    print('-' * 115)
    for i, r in enumerate(all_ranked[:20]):  # 只显示前20
        d = '多' if r['direction'] == 'bull' else ('空' if r['direction'] == 'bear' else '中')
        print(f'{i+1:>3} {r["sector"]:<8} {d:<4} {r["price"]:>8.2f} {r["change_pct"]:>+5.1f}% {r["total"]:>+4.0f} {r["l1"]:>+3} {r["l2"]:>+3} {r["l3"]:>+3} {r["l4"]:>+3} {r["veto"]:>+3} {r["adx"]:>5.1f} {r["rsi"]:>5.1f} {r["z_score"]:>5.1f} {r["cons"]:>3.0f}/4 {r.get("beta",0):>4.2f} {r.get("stage","?"):>8} {r["grade"]:>6}')

    # 写入文件
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, f'{output_prefix}_{today_str}.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n📊 JSON: {json_path}')

        # HTML报表
        import json as _json
        rows_json = _json.dumps([{
            'i': i+1, 'sector': r['sector'], 'code': r.get('etf_code',''),
            'dir': r['direction'], 'price': r['price'], 'chg': r['change_pct'],
            'total': r['total'], 'l1': r['l1'], 'l2': r['l2'], 'l3': r['l3'], 'l4': r['l4'],
            'veto': r['veto'], 'adx': r['adx'], 'rsi': r['rsi'], 'z': r['z_score'],
            'cons': r['cons'], 'beta': r.get('beta', 1.0),
            'stage': r.get('stage','?'), 'grade': r['grade'],
        } for r in all_ranked], ensure_ascii=False)

        b, bl_sig = len(bear), len(bull)
        n_neutral = len(results) - b - bl_sig

        html = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>行业ETF趋势信号 — {today} (v1.0.0)</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0f1117;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif;padding:24px}}
.hd{{background:linear-gradient(135deg,#1a1d28,#252940);border-radius:12px;padding:24px 28px;margin-bottom:20px;border:1px solid #2a2d3a}}
.hd h1{{font-size:22px;color:#f59e0b}} .hd .m{{color:#9ca3af;font-size:12px;margin-top:6px;display:flex;gap:14px;flex-wrap:wrap}}
.hd .m span{{background:#252940;padding:3px 10px;border-radius:5px}}
.st{{display:flex;gap:14px;margin-bottom:20px}}
.sc{{flex:1;background:#1a1d28;border-radius:10px;padding:14px 18px;border:1px solid #2a2d3a;text-align:center}}
.sc .n{{font-size:26px;font-weight:700}} .sc .l{{font-size:11px;color:#9ca3af;margin-top:3px}}
.sc.b .n{{color:#ef4444}} .sc.bl .n{{color:#22c55e}} .sc.n .n{{color:#9ca3af}}
table{{width:100%;border-collapse:collapse;background:#1a1d28;border-radius:10px;overflow:hidden;border:1px solid #2a2d3a;font-size:13px}}
thead{{background:#252940}}
th{{padding:9px 10px;text-align:left;font-weight:600;color:#9ca3af;font-size:11px;letter-spacing:.5px;white-space:nowrap;cursor:pointer;user-select:none;transition:color .15s}}
th:hover{{color:#f59e0b}} th.asc::after{{content:" \\25B2";font-size:10px}} th.dsc::after{{content:" \\25BC";font-size:10px}}
td{{padding:7px 10px;border-top:1px solid #2a2d3a20;white-space:nowrap}} tr:hover{{background:#f59e0b08!important}}
#si{{color:#6b7280;font-size:12px;margin-left:12px}}
</style>
</head><body>
<div class="hd"><h1>行业ETF趋势信号强度排序 (v1.0.0)</h1>
<div class="m"><span>{today}</span><span>{len(results)}行业ETF</span>
<span>AKShare数据源</span><span><span style="color:#f59e0b">申万31行业</span> | L1-L4四层打分(ETF版)</span></div></div>
<div class="st">
<div class="sc b"><div class="n">{b}</div><div class="l">空头</div></div>
<div class="sc bl"><div class="n">{bl_sig}</div><div class="l">多头</div></div>
<div class="sc n"><div class="n">{n_neutral}</div><div class="l">中性</div></div>
</div>

<table id="tbl"><thead><tr>
<th onclick="sortBy(0)" data-num="1">#</th>
<th onclick="sortBy(1)">行业</th>
<th onclick="sortBy(2)">方向</th>
<th onclick="sortBy(3)" data-num="1" style="text-align:right">价格</th>
<th onclick="sortBy(4)" data-num="1" style="text-align:right">涨跌</th>
<th onclick="sortBy(5)" data-num="1" style="text-align:center">总分</th>
<th onclick="sortBy(6)" data-num="1" style="text-align:center">L1</th>
<th onclick="sortBy(7)" data-num="1" style="text-align:center">L2</th>
<th onclick="sortBy(8)" data-num="1" style="text-align:center">L3</th>
<th onclick="sortBy(9)" data-num="1" style="text-align:center">L4</th>
<th onclick="sortBy(10)" data-num="1" style="text-align:center">否决</th>
<th onclick="sortBy(11)" data-num="1" style="text-align:center">ADX</th>
<th onclick="sortBy(12)" data-num="1" style="text-align:center">RSI</th>
<th onclick="sortBy(13)" data-num="1" style="text-align:center">Z</th>
<th onclick="sortBy(14)" data-num="1" style="text-align:center">CONS</th>
<th onclick="sortBy(15)" data-num="1" style="text-align:center">β</th>
<th onclick="sortBy(16)">阶段</th>
<th onclick="sortBy(17)">等级</th>
</tr></thead><tbody id="tb"></tbody></table>

<div style="margin-top:24px;display:flex;gap:14px">
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #f59e0b30">
<span style="color:#f59e0b;font-weight:600">ETF专属信号: </span>
<span style="color:#e5e7eb">份额-价格背离 / IOPV折溢价 / 北向资金 / 融资余额</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">L1从40→30降权, L2从25→30量价提权, L4从10→15资金确认升权</p></div>
<div style="flex:1;padding:14px 16px;background:#1a1d28;border-radius:8px;border:1px solid #2a2d3a">
<span style="color:#22c55e;font-weight:600">数据: </span><span style="color:#e5e7eb">通达信TQ-Local → AKShare降级</span>
<p style="color:#9ca3af;font-size:12px;margin-top:6px">etf-trend-signal v1.1.0 | {today} | 行业轮动Rank</p></div></div>

<script>
var DATA = {rows_json};

function _gc(g) {{
    if (g==='STRONG') return '#22c55e';
    if (g==='WATCH') return '#f59e0b';
    if (g==='WEAK') return '#ef4444';
    return '#6b7280';
}}

var _filter = 'all';
var _sortCol = -1;
var _sortAsc = true;

function render() {{
    var data = DATA.slice();
    if (_filter === 'bear') data = data.filter(function(d){{ return d.dir === 'bear'; }});
    else if (_filter === 'bull') data = data.filter(function(d){{ return d.dir === 'bull'; }});
    else if (_filter !== 'all') data = data.filter(function(d){{ return d.grade === _filter; }});

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
        var dt = d.dir==='bull' ? '<span style="color:#22c55e">多</span>' : (d.dir==='bear' ? '<span style="color:#ef4444">空</span>' : '<span style="color:#9ca3af">中</span>');
        var cc = d.chg>0?'#22c55e':(d.chg<0?'#ef4444':'#9ca3af');
        var tc = d.total>0?'#22c55e':(d.total<0?'#ef4444':'#9ca3af');
        var bg = _gc(d.grade) + '15';
        h += '<tr style="background:'+bg+'">';
        h += '<td style="text-align:center;color:#9ca3af">'+(i+1)+'</td>';
        h += '<td style="font-weight:700">'+d.sector+'</td><td>'+dt+'</td>';
        h += '<td style="text-align:right">'+d.price.toFixed(2)+'</td><td style="text-align:right;color:'+cc+'">'+(d.chg>0?'+':'')+d.chg.toFixed(1)+'%</td>';
        h += '<td style="text-align:center;font-weight:700;color:'+tc+'">'+(d.total>0?'+':'')+d.total+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l1>0?'+':'')+d.l1+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l2>0?'+':'')+d.l2+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l3>0?'+':'')+d.l3+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.l4>0?'+':'')+d.l4+'</td>';
        h += '<td style="text-align:center;color:#ef4444">'+(d.veto>0?'+':'')+d.veto+'</td>';
        h += '<td style="text-align:center">'+d.adx.toFixed(1)+'</td><td style="text-align:center">'+d.rsi.toFixed(1)+'</td>';
        h += '<td style="text-align:center;color:#9ca3af">'+(d.z>0?'+':'')+d.z.toFixed(1)+'</td>';
        h += '<td style="text-align:center;color:#f59e0b">'+d.cons+'/4</td>';
        h += '<td style="text-align:center">'+d.beta.toFixed(2)+'</td>';
        h += '<td style="text-align:center;color:#9ca3af;font-size:11px">'+d.stage+'</td>';
        h += '<td style="text-align:center"><span style="padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:'+_gc(d.grade)+'30;color:'+_gc(d.grade)+'">'+d.grade+'</span></td></tr>';
    }}
    document.getElementById('tb').innerHTML = h;
}}

function _val(d,col) {{
    var a = [d.i, d.sector, d.dir, d.price, d.chg, d.total, d.l1, d.l2, d.l3, d.l4,
             d.veto, d.adx, d.rsi, d.z, d.cons, d.beta, d.stage, d.grade];
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
</script>
</body></html>'''
        html_path = os.path.join(output_dir, f'{output_prefix}_ranking_{today_str}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'✅ HTML: {html_path}')

    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='行业ETF趋势信号扫描 v1.1.0（通达信TQ-Local优先）')
    parser.add_argument('--output', '-o', help='输出目录', default=None)
    parser.add_argument('--prefix', '-p', help='文件名前缀', default='etf_scan')
    args = parser.parse_args()

    OUT = args.output
    if not OUT:
        OUT = os.path.join(SKILL_DIR, '..', 'Reports',
                           date.today().strftime('%Y-%m-%d'))

    run_scan(output_dir=OUT, output_prefix=args.prefix)
