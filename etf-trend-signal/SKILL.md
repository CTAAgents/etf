# 行业ETF趋势信号发现系统 v2.5.0

**etf-trend-signal** — 基于趋势跟踪的行业轮动ETF周频调仓策略技能。
数据源：**腾讯自选股 westock-mcp**（默认，前复权日线）| 通达信TQ-Local（--source tdx）。

## 📌 定位

v2.3 在 v2.2 基础上进行**数据源架构重构**：
- **默认腾讯自选股**：westock-mcp 前复权日线，数据质量稳定，无本地客户端依赖
- **通达信备用**：`--source tdx` 切回通达信，自动前复权对齐
- **缓存机制**：MCP预取 → JSON缓存文件 → scan_all.py，解决Python脚本无法直接调MCP的局限
- **零胶水代码**：所有能力均为 skill 内置模块，无需 workspace 桥接脚本
- **数据源切换**：默认腾讯自选股（westock-mcp 前复权日线），`--source tdx` 切回通达信

## 🎯 核心变更（vs v2.2.x）

| 维度 | v2.2.x (旧) | v2.3.0 (新) |
|:----|:-----------|:-----------|
| 默认数据源 | 通达信TQ-Local | **腾讯自选股 westock-mcp** |
| TDX复权 | dividend_type='none' (不复权) | **dividend_type='qfq' (前复权)** |
| 数据架构 | 单一HTTP直连 | **双源调度** + JSON缓存 |
| CLI接口 | scan_all.py (无参数) | 新增 `--source` / `--cache` |
| 缓存机制 | 无 | `~/.workbuddy/cache/etf_westock_data.json` |
| ETF→股票 | 无 | **stock_mapper.py**：31行业ETF→前3大持仓股票映射 |
| 架构 | 部分能力在workspace胶水脚本 | **零胶水代码**：全部内置为skill模块 |

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
├── SKILL.md                      # 本文件——完整文档
├── sync_etf_skill.sh             # 一键同步→GitHub
├── scripts/
│   │
│   ├── 📡 Part 1: 信号计算排序（可独立调用）
│   │   ├── collect_data.py       # 通达信TQ-Local数据采集
│   │   ├── indicators.py         # 技术指标计算（60+字段）
│   │   ├── scoring_system.py     # 🔴 核心：通道突破策略评分
│   │   ├── scan_all.py           # CLI：全行业扫描评分排序
│   │   └── report.py             # Markdown/HTML报告生成
│   │
│   ├── 🎯 Part 2: 调仓决策 + 执行（可独立/整合调用）
│   │   ├── weekly_rebalance.py   # 周频调仓总入口 v2.2
│   │   │   ├── 默认模式: 扫描→调仓→股票映射→交易执行
│   │   │   ├── --calc-only: 仅计算信号（保存计划）
│   │   │   ├── --execute:   仅执行交易（读取计划）
│   │   │   └── 编程API: compute_rebalance(scan, holdings)
│   │   ├── stock_mapper.py       # ETF→A股股票映射（31行业）
│   │   └── mx_moni_client.py     # 妙想模拟交易 REST API 客户端
│   │
│   ├── 🛠️ 辅助模块
│   │   ├── config.py             # 通道突破策略配置参数
│   │   ├── sector_rotation.py    # 行业轮动分析
│   │   ├── signal_screener.py    # 信号筛选
│   │   ├── trade_plan.py         # T+1交易方案
│   │   ├── early_signal.py       # ⚠️ 已弃用
│   │   └── lint_no_inline_scoring.py  # 合规检测
│   │
│   └── 📈 回测
│       ├── evaluate.py           # 回测评估
│       ├── run_optimization.py   # 参数优化网格搜索
│       ├── optimize_rebalance_params.py  # 调仓参数优化（900组）
│       └── backtest_rebalance.py # 周频调仓3年回测
```

### 三部分调用方式

```
┌─────────────────────────────────────────────────┐
│            Part 1: 信号计算排序                    │
│                                                 │
│  scan_all.py (CLI)                               │
│      ↓                                           │
│  collect_data.py → indicators.py → scoring      │
│      ↓                                           │
│  31行业ETF评分 + 排序 + Z-score                   │
│  ↓ 输出: JSON + HTML                             │
└──────────────────────┬──────────────────────────┘
                       │ scan_results (dict)
                       ▼
┌─────────────────────────────────────────────────┐
│          Part 2: 调仓决策                         │
│                                                 │
│  weekly_rebalance.py                             │
│      ↓                                           │
│  compute_rebalance(scan_results, holdings)      │
│      ↓                                           │
│  候选池 → 持仓判定 → 新开仓 → 仓位分配            │
│  ↓ 输出: 调仓方案JSON + 更新持仓文件               │
└──────────────────────┬──────────────────────────┘
                       │ rebalance plan (dict)
                       ▼
┌─────────────────────────────────────────────────┐
│        Part 3: 执行（v2.2 新增）                   │
│                                                 │
│  stock_mapper.py                                 │
│      ↓ ETF→A股股票映射（前3大持仓）                │
│  mx_moni_client.py                               │
│      ↓ 撤旧委托 → 市价买入/卖出 → 发帖总结          │
│  ↓ 输出: 交易结果 + mx-moni经验帖                  │
└─────────────────────────────────────────────────┘
```

### 三种运行模式

```bash
# 模式一：完整管道（周四盘前使用）—— 扫描+调仓+执行
python scripts/weekly_rebalance.py

# 模式二：仅计算信号（手动预览）
python scripts/weekly_rebalance.py --calc-only

# 模式三：仅执行交易（读取上次保存的计划）
python scripts/weekly_rebalance.py --execute
```

### 快速入门

```python
# 方式一：一键全流程（Part 1 + Part 2）
from weekly_rebalance import compute_rebalance, load_holdings, save_holdings
from scan_all import run_scan

scan = run_scan()                              # Part 1: 信号计算
current = load_holdings()                       # 加载上周持仓
plan = compute_rebalance(scan, current)         # Part 2: 调仓决策
save_holdings(plan['final_positions'])           # 保存新持仓
print(plan['summary'])

# 方式二：仅看信号排序（Part 1 独立调用）
python scripts/scan_all.py --output /path/to/output

# 方式三：仅看调仓方案（Part 2 独立调用，自动触发 Part 1）
python scripts/weekly_rebalance.py --dry-run
```

### 调仓参数（优化后）

| 参数 | 值 | 含义 |
|:----|:--:|:-----|
| TOP_N | **3** | 候选池最多3个行业 |
| SCORE_ENTRY_THRESHOLD | **55** | 总分>55才进入候选池 |
| SCORE_EXIT_THRESHOLD | **30** | 掉出候选池+总分<30才清仓 |
| FORCE_CASH_THRESHOLD | **35** | 全市场最高分<35→强制空仓 |

## 🚀 使用方式

### Part 1: 全行业信号扫描（独立）

```bash
cd ~/.workbuddy/skills/etf-trend-signal
python scripts/scan_all.py --output Reports

# 快速模式：只扫前5个行业
python scripts/scan_all.py --quick 5
```

### Part 2: 周频调仓（独立运行，自动触发 Part 1）

```bash
# 首次运行（无持仓文件）
python scripts/weekly_rebalance.py

# 预览不更新持仓
python scripts/weekly_rebalance.py --dry-run

# 指定持仓文件
python scripts/weekly_rebalance.py --holdings /path/to/holdings.json
```

### 编程调用：整合 Part 1 + Part 2

```python
from weekly_rebalance import compute_rebalance, load_holdings, save_holdings,
    TOP_N, SCORE_ENTRY_THRESHOLD, SCORE_EXIT_THRESHOLD, FORCE_CASH_THRESHOLD
from scan_all import run_scan

# Part 1: 信号计算
scan = run_scan(output_dir='Reports', output_prefix='weekly')

# Part 2: 调仓决策
current = load_holdings()
plan = compute_rebalance(scan, current)

print(f'候选池: {len(plan["target_pool"])}个行业')
print(f'调仓动作:')
for a in plan['actions']:
    print(f'  {a["action"]} {a["sector"]} ({a["new_pct"]:.1%})')
print(f'最终仓位: {plan["final_positions"]}')
save_holdings(plan['final_positions'])
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

### v2.5.0 (2026-07-08)
**核心改动：HS300相对动量过滤 + ATR 1.0× 最紧止损**

1. **沪深300 120日相对动量过滤**：指数120日回报≤0时强制空仓，全周期回测Sharpe 0.258→0.567(+120%)
2. **ATR倍数从1.5下调到1.0**：精细网格搜索(1.0-1.9步长0.1)确认1.0×最优，回撤从23.7%降至20.2%
3. **综合最优参数**：ATR 1.0× + HS300动量 = Sharpe 0.567 | 年化 9.5% | 回撤 16.1%
4. **config.py**：ATR_STOP_CONFIG 新增 hs300_momentum / hs300_momentum_period / hs300_etf_code 参数
5. **weekly_rebalance.py**：新增 `_check_hs300_momentum()` 函数，`compute_rebalance()` 增加 Step 1.6 动量过滤决策

### v2.4.0 (2026-07-08)
**核心改动：ATR移动跟踪止损 + 两阶段参数优化**

1. **ATR移动跟踪止损**：入场后每日更新止损价 = 持仓最高收盘价 − ATR倍数×ATR，触发后次日开盘退出
2. **两阶段网格搜索优化**：Phase1(ATR倍数×周期×工作日=60组) + Phase2(策略参数=81组)，前60%训练/后40%测试
3. **优化结果**：Sharpe 0.291→1.168(+301%)，年化8.1%→26.1%(+222%)，卡玛0.57→1.22(+114%)
4. **最优参数**：ATR 1.5×20 + 周五调仓 + TOP_N=2/ENTRY=55/EXIT=25/FC=30，止损触发18次
5. **新增脚本**：`backtest/atr_stop_optimize.py` — 含止损的回测引擎+网格搜索+HTML报告
6. **config.py**：新增 `ATR_STOP_CONFIG` 和 `CHANNEL_BREAKOUT_NO_STOP` 参数组

### v2.3.1 (2026-07-08)
**核心改动：回测收益核算修复 — 消除收益偏移一周的bug**

1. **根因**：5个回测文件的收益核算均使用"当前周次日开盘当买入价"，而非"上周实际入场价"，导致收益数据向前偏移一整周
2. **修复方案**：引入 `entry_prices` 字典追踪每个仓位实际入场价（上次调仓日次日开盘），收益 = (当前调仓次日开盘 − 实际入场价) / 实际入场价
3. **修复文件**：`backtest_rebalance.py` / `test_weekday.py` / `optimize_rebalance_params.py` / `optimize_frequency.py` / `optimize_full_5d.py`
4. **副作用清理**：删除 `backtest_rebalance.py` 中不再使用的 `next_thursday_open()` 函数

### v2.3.0 (2026-07-08)
**核心改动：数据源架构重构 — 默认腾讯自选股 + 通达信前复权修复**

1. **默认数据源切换**：westock-mcp 前复权日线 → 主数据源，通达信 → `--source tdx` 备用
2. **双源调度架构**：`EtfDataCollector` 统一入口，`WestockCollector`(新) + `TdxCollector`(保留)
3. **JSON缓存机制**：MCP预取 → `~/.workbuddy/cache/etf_westock_data.json` → `scan_all.py` 加载
4. **TDX复权修复**：`collect_data.py` 硬编码 `dividend_type='none'` → `TDX_CONFIG['dividend_type']` ('qfq')
5. **CLI新增**：`scan_all.py --source westock|tdx --cache <path>`
6. **根因修复**：TDX不复权导致与westock评分方向翻转（半导体 +55 vs 空头），已通过复权对齐解决

### v2.2.0 (2026-07-08)
**核心改动：完整调仓执行管道 + 妙想模拟交易集成 + 零胶水代码**

1. **完整管道**：`weekly_rebalance.py` 默认模式一条命令完成扫描→调仓→股票映射→交易执行
2. **三种CLI模式**：`--calc-only`（仅计算）、`--execute`（仅执行）、默认（全流程）
3. **新增 `mx_moni_client.py`**：妙想模拟交易 REST API 客户端（持仓查询/市价买卖/撤单/发帖）
4. **新增 `stock_mapper.py`**：ETF→A股股票映射模块，31行业ETF→前3大持仓股票
5. **新增 `etf_stock_mapping.json`**：映射配置文件，存放于 scripts/ 目录
6. **零胶水代码**：删除 workspace 中 3 个桥接脚本（1855行），全部能力上移到 skill 模块

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
