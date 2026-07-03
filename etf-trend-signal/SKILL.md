# 行业ETF趋势信号发现系统 v1.1.0

**etf-trend-signal** — 基于commodity-trend-signal期货L1-L4四层打分架构的**行业ETF改造版**。
数据源：**通达信TQ-Local**（HTTP JSON-RPC）优先 + **AKShare** 降级备用。

## 📌 定位

将 commodity-trend-signal 的期货语境（OI/基差/期限结构）整体迁移至 行业ETF语境（份额/IOPV折溢价/北向资金/融资余额）。

| 维度 | 商品期货 (原版) | 行业ETF (本版) |
|------|----------------|----------------|
| 持仓兴趣 | OI持仓量 | **基金份额 + 融资余额** |
| 基差 | 现货-期货 | **IOPV折溢价** |
| 期限结构 | 近远月曲线 | **行业相对强度（ETF vs 沪深300）** |
| 换月 | 主力移仓 | **行业轮动切换（Rank掉出前5移仓）** |
| 资金面 | 席位龙虎 | **北向资金/融资/行业轮动** |
| 产业链 | 上游→下游 | **行业景气/宏观时钟** |

## 🎯 核心能力

- **L1-L4四层打分（ETF优化权重 v1.1）**：L1萌芽(40分) + L2量价(30分) + L3结构(20分) + L4确认(10分) + 否决(-20分)
- **ETF专属早期信号**：份额-价格背离、IOPV折溢价走阔、北向资金5日累计、融资余额斜率
- **行业轮动Rank**：申万一级31行业赛马排序
- **行业β过滤**：20日滚动β > 1.1 才进入赛马
- **宏观时钟过滤**：复苏/过热/滞胀/衰退各阶段行业映射
- **T+1适配**：尾盘决断策略、跌破关键均线减仓
- **方向感知Z-score**：多头/空头各自独立计算统计显著性

## 🔧 L1-L4四层打分架构（ETF优化版）

| 层级 | 分值 | 信号含义 | 比传统指标早 |
|------|:----:|---------|:-----------:|
| **L1 萌芽/资金结构** | 40分 | 份额背离 / IOPV溢价 / 北向流入 / 融资杠杆 / 通达信专业数据 | 10-30根K |
| **L2 量价领先** | 30分 | Vortex / CCI / Supertrend / HMA 交叉 | 3-10根K |
| **L3 价格结构** | 20分 | RSI健康区 / DMI方向 / 前高突破 / 行业β | 2-5根K |
| **L4 确认** | 10分 | 通道突破 / 均线排列 / MACD / 行业Rank | 0根K |
| **否决** | -20分 | ADX震荡 / RSI极端 / 折价过深 / 份额流失 | — |

### ⚖️ 权重调整说明

期货→ETF权重变动：**L1 40→40**（保留，通达信专业数据增强L1），**L2 25→30**（升权，量价在ETF更可靠），**L3 25→20**（降权），**L4 10→10**（保留）。

**否决项扩充**：折价>2%且扩大（-4）、份额连续5日流失（-3）、IOPV溢价过热（-3）。

### 🔴 内部分数等比例缩放铁律

**原则**：各层内部所有子信号的理论满分之和必须精确等于分层分数。当分层权重改变时，所有内部分数按相同比例缩放。

**当前内部满分构成**：
| 层级 | 内部满分 | 子信号分配 | 缩放比例 |
|:----:|:--------:|-----------|:--------:|
| L1 | 40 | ETF专属26(份额6+IOPV5+RS5+北向5+融资3) + 通用14(ROC3+%b3+ATR2+MA斜率4+HL2) | 原35→40 (×40/35) |
| L2 | 30 | Vortex8 + CCI7 + Supertrend8 + HMA7 | 不变 |
| L3 | 20 | RSI8 + DMI6 + 新高6 | 原25→20 (×0.8) |
| L4 | 10 | 通道3 + 均线3 + MACD1 + DC55共振2 + 行业Rank1 | 原14→10 (×10/14) |
| 否决 | -20 | ADX-6/-3 + RSI-6 + CCI-5 + 偏离-4/-2 + 缩量-4 + 折价-4 + 溢价过热-3 + 份额流失-3 | — |

## 📦 模块结构

```
etf-trend-signal/
├── SKILL.md                  # 本文件——完整文档
├── scripts/
│   ├── __init__.py
│   ├── config.py             # 申万31行业ETF映射表 + L1-L4权重 + 阈值
│   ├── collect_data.py       # AKShare ETF数据采集（行情/份额/IOPV/北向/融资）
│   ├── indicators.py         # 技术指标计算（均线/RSI/MACD/ATR/Donchian/Bollinger等）
│   ├── early_signal.py       # ETF早期信号检测（份额背离/IOPV溢价/北向/融资）
│   ├── scoring_system.py     # L1-L4四层打分(ETF版)
│   ├── sector_rotation.py    # 行业轮动Rank + β过滤 + 宏观时钟
│   ├── signal_screener.py    # 信号筛选 + 共振度 + β过滤
│   ├── trade_plan.py         # T+1交易方案 + 行业轮动切换
│   ├── scan_all.py           # 全行业扫描CLI（31行业ETF）
│   └── report.py             # Markdown/HTML报告生成
```

## 📡 数据源

由 `EtfDataCollector` 双源自动路由：**通达信TQ-Local**（HTTP JSON-RPC `http://127.0.0.1:17709/`）→ **AKShare** 降级。

### 通达信 TQ-Local 接口（优先）

| 数据类型 | 接口 | 参数 | 说明 |
|---------|------|------|------|
| ETF日K线 | `get_market_data` | `period="1d"`, `dividend_type="qfq"` | OHLCV行情（手→股自动转换） |
| ETF实时快照 | `get_market_snapshot` | `stock_code` | 含`Jjjz`基金净值=IOPV |
| ETF溢价率 | `get_more_info` | `field_list=["More_YJL"]` | 'ETF,LOF溢价率'字段 |
| 市场份额 | `get_scjy_value` | `field_list=["SC08"]` | ETF基金规模(亿份) + 净申赎(亿份) |
| 融资融券 | `get_scjy_value` | `field_list=["SC01"]` | 沪深京融资余额 |
| 陆股通 | `get_scjy_value` | `field_list=["SC02"]` | 沪股通+深股通流入金额 |

### AKShare 降级备用

| 数据类型 | 接口 | 说明 |
|---------|------|------|
| ETF日K线 | `fund_etf_hist_em` | 东方财富数据 |
| 基金份额 | `fund_etf_scale_open_sina` | 新浪份额日报 |
| IOPV折溢价 | `fund_etf_iopv_em` | 东方财富数据 |

## 🚀 使用方式

### 全行业批量扫描（CLI）

```bash
# 从skill目录运行
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
from scripts.collect_data import fetch_etf_daily_klines, fetch_etf_share_history
from scripts.indicators import _compute_indicators_numpy, assess_trend_maturity
from scripts.scoring_system import calculate_composite_score
from scripts.early_signal import inject_etf_early_signals_to_tech
from scripts.sector_rotation import rank_sectors, compute_beta_filter
from scripts.signal_screener import screen_signals
from scripts.trade_plan import generate_trade_plan

# 1. 采集数据
klines = fetch_etf_daily_klines('512480.SH')
shares = fetch_etf_share_history('512480.SH')

# 2. 计算指标
import pandas as pd
df = pd.DataFrame(klines)
tech = _compute_indicators_numpy(df)

# 3. 注入ETF早期信号
etf_data = {'share_history': shares, ...}
tech = inject_etf_early_signals_to_tech(etf_data, tech)

# 4. L1-L4评分
sc = calculate_composite_score(tech, {'last_price': klines[-1]['close']},
                                etf_data=etf_data)
print(f"{sc['grade']}: {sc['total']}分, 方向={sc['direction']}")
```

## 📊 信号等级说明

| 等级 | 分值范围 | 含义 | 操作建议 |
|------|:--------:|------|---------|
| **STRONG** | ≥75分 | 强趋势信号，多维度共振 | 可考虑主仓介入 |
| **WATCH** | 60-74分 | 趋势信号明确，但需验证 | 观察等待右侧确认 |
| **WEAK** | 40-59分 | 信号较弱或已走远 | 轻仓试探或观望 |
| **NOISE** | <40分 | 噪音信号，趋势不明确 | 不操作 |

## 🏆 行业轮动SOP

```
Step 1: 全行业扫描 ─→ Step 2: β过滤(>1.1) ─→ Step 3: L1-L4评分排名
    → Step 4: 宏观时钟过滤 ─→ Step 5: 行业Rank Top5进入观察池
    → Step 6: 份额/北向/融资确认 ─→ Step 7: 尾盘决断入场
```

**核心原则**：
- **只交易β>1.1的行业**（排除低贝塔防御型行业）
- **Rank掉出前5触发移仓**（行业轮动切换信号）
- **T+1尾盘决断**（非日内交易，跌破MA20减半仓）
- **宏观时钟优先**（复苏配金融消费、过热配周期制造、滞胀配防御）

## ⚠️ ETF vs 期货关键差异提醒

1. **无杠杆**：仓位公式用基础百分比（不加ATR乘数）
2. **T+1**：止损不能日内硬砍，用"跌破关键均线减仓 + 尾盘决断"
3. **无到期换月**：不处理展期，但需要"行业轮动切换"逻辑
4. **易缩量上涨**：量能要求可放宽，侧重均线结构
5. **ETF只能做多**（融券标的有限）：空头信号仅用于降级，不用于开空仓

## 🔴 评分逻辑单源真理原则

所有评分逻辑必须且只能通过 `scoring_system.py` 实现。任何脚本文件不得内联 L1-L4 打分/趋势阶段判断/否决逻辑。

### 架构分层

```
scripts/
├── scoring_system.py         ← 唯一评分来源（不可分叉）
│   ├── score_L1_germination()
│   ├── score_L2_volume_price()
│   ├── score_L3_structure()
│   ├── score_L4_confirmation()
│   ├── score_veto_dimension()
│   └── calculate_composite_score()  ← 唯一入口
├── indicators.py             ← 唯一指标计算来源
├── collect_data.py           ← 唯一数据采集来源
├── scan_all.py               ← CLI入口：必须 import scoring_system
└── ...
```

## 🔒 Signal Quality Circuit Breaker

| 防呆机制 | 规则 | 触发后果 |
|:---------|:----|:---------|
| L1-L4评分范围 | 各层固定范围（L1≤30, L2≤30, L3≤25, L4≤15） | 裁剪至合法范围 |
| 否决项上限 | veto范围-20~0 | 超出裁剪 |
| 方向一致性 | ≥3层方向相反→标注"层间矛盾" | 信号等级降至NOISE |
| 信号等级映射 | ≥75=STRONG, 60-74=WATCH, 40-59=WEAK, <40=NOISE | 以abs值为准覆盖 |
| Z分数范围 | 方向感知Z-score -3~+3 | 超出标注"极端Z" |

## 📋 常见使用场景

### 1. 每日行业轮动信号
```bash
cd ~/.workbuddy/skills/etf-trend-signal && python scripts/scan_all.py
# 查看输出HTML报表中的Top5多头信号
```

### 2. 单个ETF深度分析
```python
from scripts.collect_data import collect_etf_data
from scripts.indicators import _compute_indicators_numpy
from scripts.scoring_system import calculate_composite_score

data = collect_etf_data('半导体', '512480.SH')
# ... 后续指标计算和评分
```

### 3. 宏观时钟过滤
```python
from scripts.sector_rotation import get_macro_clock_sectors

# 假设当前处于"复苏"阶段
preferred = get_macro_clock_sectors('复苏')
print(f"复苏期偏好行业: {preferred}")
```

## 📝 版本历史

### v1.1.0 (2026-07-03)
**核心改动：数据源切换为通达信TQ-Local + 权重重调为40/30/20/10**

1. **数据源重写**：`collect_data.py` 新增 `TdxCollector` + `EtfDataCollector` 双源自动路由
   - 通达信TQ-Local（HTTP JSON-RPC `http://127.0.0.1:17709/`）优先
   - AKShare 降级备用
   - 利用 `get_market_snapshot.Jjjz` 获取 IOPV、`get_more_info.More_YJL` 获取溢价率
2. **权重重调 40/30/20/10**：L1 30→40升权（通达信专业数据增强）、L3 25→20降权、L4 15→10降权
3. **配置文件更新**：`config.py` 新增 `TDX_CONFIG`、`TDX_DATA_MAP` 配置段
4. **早期信号兼容**：`early_signal.py` 的 `inject_etf_early_signals_to_tech()` 支持双数据源格式
5. **scan_all**：自动检测 TQ-Local 可用性，TDX 不可用则静默降级 AKShare

### v1.0.0 (2026-07-03)
初始版本：从 commodity-trend-signal v2.18.0 迁移改造。
