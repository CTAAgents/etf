# 行业ETF趋势信号发现系统 v2.1.0

**etf-trend-signal** — 基于 **通道突破策略（Channel Breakout Strategy）** 的ETF信号评分系统。
数据源：**纯通达信TQ-Local**（HTTP JSON-RPC，无第三方库依赖）。

## 📌 定位

v2.1 在通道突破策略基础上，新增**纯多头模式** + **参数优化**：
- **纯多头模式**：ETF只做多，scan_all输出自动过滤空头信号
- **参数优化**：基于6行业×250天历史数据的网格搜索，调整DC55/BB/Volume阈值
- 数据源不变：**纯通达信TQ-Local**（HTTP JSON-RPC，无第三方库依赖）

## 🎯 核心变更（vs v1.1.3）

| 维度 | v1.1.3 (旧) | v2.1.0 (新) |
|:----|:-----------|:-----------|
| 评分架构 | L1-L4四层(35/30/20/15) + 否决(-20) | 唐奇安通道(75%) + 布林带(25%) + 成交量 |
| 输出模式 | 多头+空头 | **纯多头**（ETF只做多，空头自动过滤） |
| 总分范围 | [0, 100] | [-76, +76] |
| STRONG阈值 | ≥75分 | ≥50分 |
| 信号类型 | 无分级 | channel_breakout / trend_confirmation / bb_squeeze_prebreakout / minor_signal |
| ETF专属信号 | IOPV/北向/融资/份额 | 不再计入评分（可辅助参考） |
| 否决项 | 13项(-20分) | 无否决（直接计入各层分值） |
| 参数 | 固定默认值 | **网格搜索优化**（DC55/BB/Volume共6参数） |
| 数据源 | 通达信TQ-Local | 通达信TQ-Local（不变） |

## 🔧 评分架构

```
tech_dict (指标引擎45+字段)
    │
    ├─ Layer A: 唐奇安通道 (75%权重)
    │   ├─ A1: DC20 短期突破 (占75%中的40% ≈ 总分30%)
    │   └─ A2: DC55 中期趋势 (占75%中的35% ≈ 总分26.25%)
    │
    ├─ Layer B: 布林带确认 (25%权重)
    │   ├─ B1: 带宽扩张/收缩 (占25%中的40% ≈ 10%)
    │   ├─ B2: 挤压检测 (占25%中的20% ≈ 5%)
    │   └─ B3: %b 位置 (占25%中的40% ≈ 10%)
    │
    ├─ 成交量确认 (独立加减分, -3 ~ ±10)
    │
    └─ total_score = dc20 + dc55 + bb + vol
         → direction → grade → signal_type
```

### ⚖️ 评分公式速查

```
total_score = dc20_score + dc55_score + bb_score + volume_score

方向:     bull  if total > 0
          bear  if total < 0
          neutral if total = 0

等级:     STRONG if |total| >= 50
          WATCH  if |total| >= 40
          WEAK   if |total| >= 20
          NOISE  if |total| < 20

信号类型: channel_breakout       if |dc20_score| >= 30 AND |dc_score| >= 20
          trend_confirmation     if |dc55_score| >= 15
          bb_squeeze_prebreakout if bb_squeeze == True
          minor_signal           (兜底)
```

### A1: DC20 短期突破（≈ 总分30%）

**前提**: 只对 `dc20_break == "up" / "down"` 的品种计算。

**向上突破逻辑**：
```
基础: dc20_score += 30.0

突破幅度确认:
  突破距离 = (price / dc20_upper - 1) × 100%
  如果距离 > 1.0% → dc20_score += 10.0  (strong)
  如果距离 > 0.3% → dc20_score += 5.0   (moderate)

DC20位置确认:
  如果 DC20_POS > 0.7 → dc20_score += 5.0  (upper_zone)

ADX趋势评估:
  如果 ADX > 60  → dc20_score -= 5.0  (exhaustion)
  否则如果 ADX ≥ 25 → dc20_score += 3.0  (trend_healthy)
```

**向下突破逻辑**（对称，分数取负）：基础-30，突破幅度-10/-5，位置-5，ADX+5(衰竭)/-3(健康)

### A2: DC55 中期趋势（≈ 总分26.25%）

**第一步：6级阶梯评分**

| 条件 | 得分 | 标签 |
|:----|:---:|:----|
| DC55_POS > 0.85 | +30.0 | extreme_upper |
| DC55_POS > 0.70 | +20.0 | upper |
| DC55_POS > 0.50 | +7.0 | mid_upper |
| DC55_POS < 0.15 | -25.0 | extreme_lower |
| DC55_POS < 0.30 | -15.0 | lower |
| DC55_POS < 0.50 | -5.0 | mid_lower |

**第二步：趋势方向确认**
- 趋势向上+位置看多 → +17.0 (方向一致, 含+7对齐奖励)
- 趋势向上+位置看空 → 0.0 (方向背离)
- 趋势向下+位置看空 → -17.0 (方向一致)
- 趋势向下+位置看多 → -20.0 (方向背离)

### B: 布林带确认

B1 带宽扩张/收缩（方向跟随DC总分）：>4%→±6, >2.5%→±3
B2 挤压检测：无方向，+2
B3 %b位置：极端±6, 上/下轨±4, 中上/中下±2
一致性加分：DC与BB方向一致→+2

### 成交量确认

| 条件 | 得分 |
|:----|:---:|
| vol_ratio > 1.3 | ±10 (跟随DC方向) |
| vol_ratio > 1.1 | ±5 (跟随DC方向) |
| vol_ratio > 0.8 | 0 (正常) |
| vol_ratio < 0.8 | -3 (缩量，固定惩罚) |

## 📦 模块结构

```
etf-trend-signal/
├── SKILL.md                  # 本文件——完整文档
├── scripts/
│   ├── __init__.py           # 模块导出（更新为v2.0接口）
│   ├── config.py             # 通道突破策略配置参数
│   ├── collect_data.py       # 通达信TQ-Local数据采集（不变）
│   ├── indicators.py         # 技术指标计算（不变，已含DC20/DC55/BB）
│   ├── scoring_system.py     # 🔴 核心：通道突破策略评分（完全重写）
│   ├── scan_all.py           # 全行业扫描CLI（适配新评分）
│   ├── report.py             # Markdown/HTML报告生成（适配新评分）
│   ├── signal_screener.py    # 信号筛选（适配通道突破策略）
│   ├── trade_plan.py         # T+1交易方案（适配新评分）
│   ├── sector_rotation.py    # 行业轮动分析（保留不变）
│   ├── early_signal.py       # ⚠️ 已弃用（保留仅供引用，不再注入评分）
│   └── lint_no_inline_scoring.py  # 合规检测（保留）
│   └── backtest/
│       ├── evaluate.py       # 回测评估（待适配）
│       └── optimize_weights.py # 权重优化（待适配）
```

### 依赖关系

```
scan_all.py (CLI入口)
    ├── collect_data.py → indicators.py → scoring_system.py (新的通道突破评分)
    ├── sector_rotation.py (行业相对强度，保持不变)
    
signal_screener.py
    └── (依赖 scoring_system 的评分结果)

trade_plan.py
    └── (依赖 scoring_system 的 composite_score)
```

## 🚀 使用方式

### 全行业批量扫描

```bash
cd ~/.workbuddy/skills/etf-trend-signal
python scripts/scan_all.py

# 指定输出目录
python scripts/scan_all.py --output /path/to/output --prefix my_scan

# 输出文件：
#   {output_dir}/{prefix}_{YYYYMMDD}.json       — 结构化信号数据
#   {output_dir}/{prefix}_ranking_{YYYYMMDD}.html — 交互式报表
```

### 编程调用

```python
from scripts.collect_data import EtfDataCollector
from scripts.indicators import _compute_indicators_numpy
from scripts.scoring_system import calculate_composite_score
from scripts.signal_screener import screen_signals
from scripts.trade_plan import generate_trade_plan

# 1. 采集数据
import pandas as pd
collector = EtfDataCollector()
klines = collector.get_etf_klines('半导体', '512480.SH')

# 2. 计算指标
df = pd.DataFrame(klines)
tech = _compute_indicators_numpy(df)

# 3. 通道突破评分
sym = {'last_price': klines[-1]['close']}
sc = calculate_composite_score(tech, sym)
print(f"{sc['grade']}: {sc['total']}分, 方向={sc['direction']}")
print(f"信号类型: {sc['signal_type']}")
print(f"子层: DC20={sc['sub_scores']['dc20']}, DC55={sc['sub_scores']['dc55']}, BB={sc['sub_scores']['bb']}, VOL={sc['sub_scores']['vol']}")
```

## 📊 信号等级说明

| 等级 | 分值范围 | 含义 | 与辩论流程衔接 |
|:----|:--------:|------|:------------:|
| **STRONG** | ≥50分 | 强通道突破信号 | 进入辩论流程 |
| **WATCH** | 40-49分 | 趋势信号明确 | 观察等待右侧确认 |
| **WEAK** | 20-39分 | 信号较弱 | 轻仓试探或观望 |
| **NOISE** | <20分 | 噪音 | 不操作 |

## 🏆 辩论流程衔接

```
scan_all.py → calculate_composite_score() → summary
    │
    ├─ all_ranked[]     (按abs降序)
    ├─ bull_signals[]
    ├─ bear_signals[]
    └─ _meta            (统计 + generated_at)
          │
          ▼ 信号检查闸门
    grade=="STRONG" (abs≥50) 的品种 ≥ 1个?
          │
    是 → 链证源产业链分析 → 闫判官选辩论品种 → P2~P5辩论
    否 → "当天无通道突破信号" 提前终止

注意: 所有STRONG品种必须辩论，无直接推荐通道。
```

## 🔴 评分单源真理原则

所有评分逻辑必须且只能通过 `scoring_system.py` 实现。任何脚本文件不得内联通道突破打分逻辑。

### 架构分层

```
scripts/
├── scoring_system.py         ← 唯一评分来源（不可分叉）
│   ├── score_dc20()           DC20短期突破
│   ├── score_dc55()           DC55中期趋势
│   ├── score_bb()             布林带确认
│   ├── score_volume()         成交量确认
│   ├── determine_grade()      等级判定
│   ├── determine_direction()  方向判定
│   ├── determine_signal_type() 信号类型判定
│   └── calculate_composite_score()  ← 唯一入口
├── indicators.py             ← 唯一指标计算来源
├── collect_data.py           ← 唯一数据采集来源
├── scan_all.py               ← CLI入口：必须 import scoring_system
└── ...
```

## 🔒 Signal Quality Circuit Breaker

| 防呆机制 | 规则 |
|:---------|:----|
| DC20评分范围 | 无硬约束（自然范围[0, ±53]） |
| DC55评分范围 | 6级阶梯，无硬约束 |
| BB评分范围 | 无硬约束（自然范围[-16, +16]） |
| 方向一致性 | 纯符号判定 |
| 信号等级映射 | ≥50=STRONG, 40-49=WATCH, 20-39=WEAK, <20=NOISE |
| Z分数范围 | 方向感知Z-score -3~+3 |

## 📝 版本历史

### v2.1.0 (2026-07-08)
**核心改动：纯多头模式 + 参数网格搜索优化**

1. **纯多头模式**：scan_all/report/signal_screener/trade_plan 全面改为bull_only，空头信号自动过滤
2. **参数优化**：基于6行业×250天历史数据的网格搜索（36组参数），优化6项阈值
3. **优化参数**：DC55 extreme_upper_score 25→30, upper_score 15→20, mid_upper_score 5→7, trend_alignment_bonus 5→7, volume explosive_ratio 1.5→1.3, elevated_ratio 1.2→1.1
4. **优化效果**：样本外avg_bull 39.1→45.8(+17%), STRONG比例 20.0%→23.3%
5. **新增回测管线**：`backtest/run_optimization.py` 支持可复现的参数网格搜索
6. **注入机制修复**：scoring_system 的 CHANNEL_BREAKOUT_CONFIG 原地修改注入验证通过
7. **sync脚本**：`sync_etf_skill.sh` 一键同步+提交GitHub

### v2.0.0 (2026-07-08)
**核心改动：全面替换L1-L4四层打分架构为通道突破策略**

1. **评分架构重写**：移除L1-L4(35/30/20/15)+否决(-20)，改为Layer A唐奇安通道(75%)+Layer B布林带(25%)+成交量
2. **新评分函数**：`score_dc20()`, `score_dc55()`, `score_bb()`, `score_volume()`
3. **信号类型体系**：新增4级信号类型（channel_breakout/trend_confirmation/bb_squeeze_prebreakout/minor_signal）
4. **阈值调整**：STRONG从75→50，WATCH从60→40，WEAK从40→20
5. **方向判定简化**：纯符号判定（total > 0 = bull, < 0 = bear）
6. **删除否决维度**：ADX调整并入DC20评分，不再独立否决
7. **删除ETF专属信号**：IOPV/北向/融资/份额不再注入评分（collect_data保留采集）

### v1.1.3 (2026-07-03)
纯TDX数据源 + RSI分段映射 + 否决项扩充

### v1.1.0 (2026-07-03)
数据源切换为通达信TQ-Local + 权重重调

### v1.0.0 (2026-07-03)
初始版本：从 commodity-trend-signal v2.18.0 迁移改造
