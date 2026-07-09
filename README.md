# ETF 量化策略技能库

A股 ETF 量化交易 WorkBuddy 技能集。

## 技能列表

| 技能 | 版本 | 说明 | 核心指标 |
|:--|:--:|:--|:--|
| [a-share-etf-momentum](./a-share-etf-momentum/) | 2.0.0 | A股行业ETF双动量轮动策略 — 绝对动量择时+相对动量轮动+估值分位刹车+ATR移动跟踪止损。通过沪深300ETF判断市场趋势，多头轮动持有最强行业ETF，熊市切换货币ET... | 年化44.30%，夏普1.275 |
| [etf-dual-momentum](./etf-dual-momentum/) | ? | ETF双动量轮动策略 — 32行业全覆盖，绝对+相对动量，AKShare估值刹车，ATR止损 | Sharpe 3.85，年化70.5%，Top-3分散 |
| [etf-trend-signal](./etf-trend-signal/) | 2.5.0 | 行业ETF通道突破策略 — 唐奇安通道+布林带+成交量评分，31行业轮动 | 31行业扫描，周频调仓，完整执行管道 |
| [quantitative-momentum-stock-selection](./quantitative-momentum-stock-selection/) | 1.1.0 | 量化动量选股系统 v1.1.0 (A股优化版) — 多维度动量打分体系识别强势股票，构建动量投资组合。核心思想：买入赢家股而非成长型投资。支持全市场扫描、动量信号筛选、投资组... | 全市场扫描，T+1适配，北向资金 |

## 快速开始

每个技能独立安装到 WorkBuddy 的 `~/.workbuddy/skills/` 目录：

```bash
# 克隆仓库
git clone git@github.com:CTAAgents/etf.git

# 安装技能（以 etf-trend-signal 为例）
cp -r etf/etf-trend-signal ~/.workbuddy/skills/
```

在 WorkBuddy 对话中通过 `/skill-name` 或自然语言调用。

## 仓库结构

```
etf/
├── README.md
├── a-share-etf-momentum/
│   ├── examples/
│   ├── reports/
│   ├── scripts/
│   └── tests/
├── etf-dual-momentum/
│   ├── cache/
│   └── scripts/
├── etf-trend-signal/
│   ├── Reports/
│   └── scripts/
├── quantitative-momentum-stock-selection/
│   └── scripts/
```

## 维护

本 README 由 `generate_readme.py` 自动生成，提交前运行：

```bash
python generate_readme.py
```

---

*数据源：通达信 TQ-Local · 执行平台：妙想模拟交易 · 自动调度：WorkBuddy Automation*
