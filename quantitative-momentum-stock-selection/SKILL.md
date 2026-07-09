---
name: quantitative-momentum-stock-selection
version: 1.2.0
description: 量化动量选股系统 v1.2.0 — 数据源切换为腾讯自选股 MCP (westock-mcp)。多维度动量打分体系识别强势股票，构建动量投资组合。核心思想：买入赢家股而非成长型投资。支持全市场扫描、动量信号筛选、投资组合构建、回测验证。A股优化：涨跌停过滤+T+1适配+北向资金数据。数据源：腾讯自选股 MCP (westock-mcp connector)。
agent_created: true
user_invocable: true
triggers:
  - 动量选股
  - 量化动量
  - 赢家股
  - 趋势选股
  - 动量策略
  - 股票筛选
  - 强势股
  - 动量打分
  - 投资组合
  - 回测验证
  - A股动量
  - 涨跌停过滤
---

# 量化动量选股系统 v1.2.0 — 数据源：腾讯自选股 MCP

## 核心理念

**动量投资的本质**：买入赢家股（价格走势强劲的股票），而不是预测未来或寻找成长型股票。

**与价值投资的区别**：
- 价值投资者：买入便宜的"失宠"股
- 动量投资者：勇敢追涨，买入价格走势强劲股

**行为金融学基础**：推动价值投资者获得超额收益的行为偏差和职业担忧，正是推动动量效应长期存在的关键机制。

## 核心能力

### 1. 多维度动量打分体系（100分制，A股优化版）

| 维度 | 权重 | 指标 | 说明 |
|------|------|------|------|
| **价格动量** | 25分 | 15日收益率、45日收益率、150日收益率 | 核心动量指标，A股优化后窗口更短 |
| **相对强度** | 20分 | 行业相对强度、市场相对强度 | 相对于基准和行业的表现 |
| **成交量确认** | 25分 | 量价配合、成交量趋势 | A股散户交易活跃，成交量更重要 |
| **趋势结构** | 15分 | 均线排列、通道位置 | 价格结构健康度 |
| **风险控制** | 15分 | 波动率、回撤控制 | A股波动大，风险控制更重要 |

### 2. 趋势阶段识别

| 阶段 | 特征 | 操作建议 |
|------|------|---------|
| **启动期** | 价格突破关键阻力，成交量放大 | 重点关注，轻仓试探 |
| **主升期** | 均线多头排列，趋势明确 | 主力介入，持有待涨 |
| **衰竭期** | 动量减弱，出现顶背离 | 警惕风险，逐步减仓 |
| **反转期** | 趋势破坏，跌破关键支撑 | 及时止损，空仓观望 |

### 3. 估值过滤机制

- **PE分位过滤**：避免在估值过高时追涨
- **PB分位过滤**：辅助判断估值水平
- **行业估值对比**：相对估值优势判断

### 4. 风险管理框架（A股优化版）

- **仓位控制**：单只股票最大仓位15%，单个行业25%，总仓位70%
- **止损策略**：初始止损1.5倍ATR，移动止损0.75倍ATR，时间止损15天
- **止盈策略**：阶段式止盈，保护利润
- **分散投资**：行业分散，降低集中风险
- **涨跌停风险控制**：跌停时强制止损，连续下跌风险预警

### 5. A股市场特性适配（v1.1.0新增）

#### 5.1 涨跌停限制处理
- 自动过滤涨跌停数据，避免技术指标失真
- 跌停时触发强制止损信号
- 连续下跌风险预警（近5日4日下跌）

#### 5.2 T+1交易制度适配
- 更紧的止损设置（1.5倍ATR，考虑T+1限制）
- 更短的动量窗口（15/45/150天）
- 更早的入场和离场信号

#### 5.3 A股特有数据源
- **北向资金数据**：外资动向指标
- **融资融券数据**：杠杆资金动向
- **行业资金流向**：行业资金流入流出
- **涨跌停数据**：市场热度和风险指标

#### 5.4 A股特有指标
- 北向资金净流入
- 融资余额变化
- 涨停家数
- 换手率

### 6. 参数优化（A股市场）

| 参数 | 原值 | 优化值 | 说明 |
|------|------|--------|------|
| 短期窗口 | 20天 | 15天 | 更敏感 |
| 中期窗口 | 60天 | 45天 | 更短 |
| 长期窗口 | 252天 | 150天 | 更短 |
| 价格动量权重 | 30% | 25% | A股波动大 |
| 成交量权重 | 20% | 25% | 散户交易活跃 |
| 风险控制权重 | 10% | 15% | 风险控制更重要 |
| 强烈买入阈值 | 80分 | 75分 | 更宽松 |
| 买入阈值 | 70分 | 65分 | 更早入场 |
| 初始止损 | 2.0倍ATR | 1.5倍ATR | 更紧 |
| 移动止损 | 1.0倍ATR | 0.75倍ATR | 更紧 |
| 单股仓位 | 20% | 15% | 更分散 |
| 总仓位上限 | 80% | 70% | 更保守 |

## 使用方式 — 基于 westock-mcp 的流程

### 1. 全市场动量扫描模式（MCP 工具链版本）

```python
# 推荐工作流：通过 westock-mcp MCP 工具链完成全流程，无需第三方 Python 库

# Step 1: 获取市场概览 → mcp__westock-mcp__data_market_overview
# Step 2: 多因子排行筛选候选池 → mcp__westock-mcp__tool_ranking
#   参数: metric=CompScore(综合评分), limit=100
# Step 3: 批量获取 K 线数据 → mcp__westock-mcp__data_kline
#   参数: codes=sh600519,sz000001,... , period=day, limit=200, fq=qfq
# Step 4: 补充基本面 → mcp__westock-mcp__data_profile / data_finance
# Step 5: 技术指标确认 → mcp__westock-mcp__data_technical
#   参数: group=kdj,macd,rsi,boll
# Step 6: 资金流向验证 → mcp__westock-mcp__data_fund_flow
# Step 7: 北向资金数据 → mcp__westock-mcp__data_north_holding

# 数据处理完成后，按动量打分算法(见下文)计算各维度分数
# 最终输出 Top N 动量选股结果
```

### 候选池构建策略

| 策略 | 对应 MCP 工具 | 参数 |
|------|-------------|------|
| **综合评分排行** | `mcp__westock-mcp__tool_ranking` | `metric=CompScore, limit=200` |
| **条件筛选** | `mcp__westock-mcp__tool_filter` | `expression="PE_TTM<30 AND ROE>10"` |
| **板块内筛选** | `tool_filter + data_sector` | `universe={板块码}, expression="..."` |
| **涨停热度** | `data_market_overview(type=updown)` | 获取当日涨停/跌停分布 |
| **北向增持** | `data_north_holding` + `tool_ranking` | 查北向重仓个股 |

### 2. 单股分析模式（MCP 工具链版本）

```python
# Step 1: 搜索股票代码 → mcp__westock-mcp__data_search
#   参数: query="贵州茅台", type=stock
#   → 返回: [{code: "sh600519", name: "贵州茅台", ...}]

# Step 2: 获取日线行情 → mcp__westock-mcp__data_kline
#   参数: code=sh600519, period=day, limit=200, fq=qfq
#   → 返回: KlineData[{date, open, high, low, close, volume}]

# Step 3: 技术指标 → mcp__westock-mcp__data_technical
#   参数: code=sh600519, group=kdj,macd,rsi,boll

# Step 4: 公司概况 → mcp__westock-mcp__data_profile
#   参数: code=sh600519

# Step 5: 财务数据 → mcp__westock-mcp__data_finance
#   参数: code=sh600519, type=income, num=4

# Step 6: 机构一致预期 → mcp__westock-mcp__data_consensus
#   参数: code=sh600519

# Step 7: 资金流向 → mcp__westock-mcp__data_fund_flow
#   参数: code=sh600519, start=2026-01-01, end=2026-07-09

# Step 8: 北向持股 → mcp__westock-mcp__data_north_holding
#   参数: code=sh600519

# 收集全部数据后，按动量打分算法计算各维度分数
# 输出单股深度分析报告（含动量分数、趋势阶段、估值分位、操作建议）
```

### 3. 回测验证模式

回测使用 westock-mcp 的 `data_kline` 导出历史数据，在本地计算动量信号：

```python
# Step 1: 确定回测标的池（沪深300成分股等）
# Step 2: 批量获取历史K线 → data_kline(start=回测起始, end=回测终止, limit=500)
# Step 3: 滚动计算动量分数（每月/每季度调仓日）
# Step 4: 模拟买卖操作，记录收益/回撤/胜率
# Step 5: 输出回测报告（年化收益、最大回撤、夏普比率）
```

### 4. 实时信号模式

```python
# Step 1: 获取持仓股票行情快照 → mcp__westock-mcp__data_quote
#   参数: codes=sh600519,sz000001,...

# Step 2: 检查止损条件:
#   - 当前价 < 止损价 → 触发止损信号
#   - 近期最低点移动 → 计算移动止损
#   - 跌停 → 强制止损

# Step 3: 检查止盈条件:
#   - 累计涨幅 > 20% → 减仓30%
#   - 趋势破坏 → 清仓

# Step 4: 输出今日操作信号（买入/卖出/持有/减仓）
```

## 模块说明 — 基于 MCP 工具链的架构

| 能力模块 | 对应操作 | 依赖的 MCP 工具 |
|---------|---------|----------------|
| **候选池构建** | 全市场筛选/排行 | `data_search`, `tool_filter`, `tool_ranking`, `data_sector` |
| **行情数据** | 日K/周K/月K 获取 | `data_kline(period=day, fq=qfq)` |
| **动量打分** | 价格动量+成交量确认+趋势结构+风险控制 | `data_kline` + `data_technical` |
| **相对强度** | 行业/市场相对强弱 | `data_sector` + `data_kline(指数)` |
| **基本面过滤** | PE/PB/ROE/机构预期 | `data_profile`, `data_finance`, `data_consensus` |
| **资金流向** | 主力/北向/融资 | `data_fund_flow`, `data_north_holding` |
| **板块分析** | 行业/概念板块归属 | `data_sector` |
| **市场概览** | 大盘涨跌/成交量/资金 | `data_market_overview` |
| **单股分析** | 深度诊断 | 全链路 MCP 工具组合 |
| **回测验证** | 历史信号模拟 | `data_kline` 批量导出后本地计算 |
| **实时监控** | 持仓信号/止损止盈 | `data_quote` 快照 |

## 数据源 — 腾讯自选股 MCP (westock-mcp connector)

**注意**：本技能 v1.2.0 的数据源已从 AKShare/Tushare 全面切换至 westock-mcp（腾讯自选股 MCP）。所有数据操作通过 `mcp__westock-mcp__*` 工具完成，无需安装第三方 Python 金融数据库。

### 数据源映射表

| 数据类型 | 旧数据源 (AKShare/Tushare) | ✅ 新数据源 (westock-mcp) | 对应工具参数要点 |
|----------|---------------------------|--------------------------|----------------|
| **日线行情** | `ak.stock_zh_a_hist()` | `mcp__westock-mcp__data_kline` | `period=day, fq=qfq(前复权)` |
| **行情快照** | `ak.stock_zh_a_spot_em()` | `mcp__westock-mcp__data_quote` | 传 `codes=sh600519,sz000001` |
| **个股概览** | `ak.stock_individual_info_em()` | `mcp__westock-mcp__data_profile` | `code=sh600519` |
| **财务数据** | `ak.stock_financial_abstract()` | `mcp__westock-mcp__data_finance` | `type=income/balance/cashflow` |
| **技术指标** | 自行计算 | `mcp__westock-mcp__data_technical` | `group=kdj,macd,rsi,boll` |
| **资金流向** | `ak.stock_individual_fund_flow()` | `mcp__westock-mcp__data_fund_flow` | `code=sh600519, start=, end=` |
| **北向资金** | `ak.stock_hsgt_north_net_flow_in_em()` | `mcp__westock-mcp__data_north_holding` | `code=sh600519` |
| **板块数据** | `ak.stock_board_industry_name_em()` | `mcp__westock-mcp__data_sector` | `mode=constituent, code=板块码` |
| **条件选股** | 手动实现筛选 | `mcp__westock-mcp__tool_filter` | `expression="PE_TTM < 20"` |
| **多因子排行** | 手动计算排名 | `mcp__westock-mcp__tool_ranking` | `metric=CompScore, limit=20` |
| **搜索股票** | `ak.stock_info_a_code_name()` | `mcp__westock-mcp__data_search` | `query=茅台, type=stock` |
| **筹码分布** | — | `mcp__westock-mcp__data_chip` | `code=sh600519` |
| **机构预期** | `ak.stock_profit_forecast()` | `mcp__westock-mcp__data_consensus` | `code=sh600519` |
| **大盘概览** | `ak.stock_zh_index_daily()` | `mcp__westock-mcp__data_market_overview` | `type=summary` |

### 数据获取流程

```
Step 1: 搜索/筛选 → mcp__westock-mcp__data_search / tool_filter / tool_ranking
   └── 返回股票代码列表 (sh600519/sz000001 格式)

Step 2: 行情数据 → mcp__westock-mcp__data_kline (日K, 前复权)
   └── 返回 KlineData[{date, open, high, low, close, volume, amount}]

Step 3: 补充数据 → data_technical / data_fund_flow / data_north_holding
   └── 获取技术指标、资金流向、北向数据

Step 4: 基本面 → data_profile / data_finance / data_consensus
   └── 获取估值、财务数据、机构预期

Step 5: 板块归属 → data_sector
   └── 获取行业/概念板块归属，用于相对强度计算
```

### 代码格式规范

westock-mcp 使用 A 股专用代码格式 `sh600519` / `sz000001`，而非纯数字码：
- `sh` = 上海 (沪)
- `sz` = 深圳 (深)
- `bj` = 北京 (北交所)
- `hk` = 香港 (港股)

## 策略逻辑详解

### 动量打分算法

```python
def calculate_momentum_score(stock_data):
    """
    计算股票的动量分数（100分制）
    
    Args:
        stock_data: 股票历史数据
    
    Returns:
        momentum_score: 动量分数（0-100）
        components: 各维度分数明细
    """
    # 1. 价格动量（30分）
    price_momentum = calculate_price_momentum(stock_data)
    
    # 2. 相对强度（25分）
    relative_strength = calculate_relative_strength(stock_data)
    
    # 3. 成交量确认（20分）
    volume_confirmation = calculate_volume_confirmation(stock_data)
    
    # 4. 趋势结构（15分）
    trend_structure = calculate_trend_structure(stock_data)
    
    # 5. 风险控制（10分）
    risk_control = calculate_risk_control(stock_data)
    
    # 加权汇总
    total_score = (
        price_momentum * 0.30 +
        relative_strength * 0.25 +
        volume_confirmation * 0.20 +
        trend_structure * 0.15 +
        risk_control * 0.10
    )
    
    return total_score, {
        'price_momentum': price_momentum,
        'relative_strength': relative_strength,
        'volume_confirmation': volume_confirmation,
        'trend_structure': trend_structure,
        'risk_control': risk_control
    }
```

### 信号生成规则

| 信号类型 | 条件 | 操作建议 |
|----------|------|---------|
| **强烈买入** | 动量分数 ≥ 80，趋势阶段为启动期或主升期 | 主力介入，重仓买入 |
| **买入** | 动量分数 ≥ 70，趋势结构健康 | 可以买入，控制仓位 |
| **持有** | 动量分数 ≥ 60，趋势延续 | 继续持有，设置止损 |
| **减仓** | 动量分数 < 60，或出现顶背离 | 逐步减仓，保护利润 |
| **卖出** | 动量分数 < 50，趋势破坏 | 及时卖出，空仓观望 |

### 风险管理规则（A股优化版）

1. **仓位限制**：
   - 单只股票最大仓位：15%
   - 单个行业最大仓位：25%
   - 总仓位上限：70%

2. **止损策略**：
   - 初始止损：买入价下方1.5×ATR（更紧，考虑T+1限制）
   - 移动止损：趋势延续时，止损移至近期低点下方0.75×ATR
   - 时间止损：持有超过15个交易日未盈利，考虑止损

3. **止盈策略**：
   - 第一目标：盈利20%时减仓30%
   - 第二目标：盈利40%时再减仓30%
   - 最终目标：趋势破坏时清仓

4. **涨跌停风险控制**：
   - 跌停时强制止损
   - 近5日4日下跌时预警
   - 最大回撤限制15%

## 报告生成

### 报告内容

1. **市场概览**：大盘走势、行业轮动、资金流向
2. **动量扫描结果**：Top 10/20 动量股票列表
3. **投资组合建议**：具体股票、仓位比例、操作建议
4. **风险提示**：市场风险、个股风险、策略局限性
5. **回测验证**：策略历史表现、绩效指标

### 报告格式

- **HTML报告**：交互式图表、可折叠章节、移动端适配
- **PDF报告**：适合打印和分享
- **JSON数据**：程序化处理和分析

### v1.2.0 (2026-07-09) **数据源切换：westock-mcp (腾讯自选股 MCP)**
**数据源全面切换至腾讯自选股 MCP，移除 AKShare/Tushare 依赖**

1. **数据源重构**：
   - AKShare/Tushare → 全面替换为 `mcp__westock-mcp__*` 工具链
   - 所有数据获取通过已连接的 `westock-mcp` connector 完成
   - 无需安装第三方 Python 金融数据库（免 akshare/tushare 依赖）

2. **新增数据源映射表**：覆盖 14 类数据操作及对应的 MCP 工具参数

3. **使用方式重构**：
   - 全市场扫描 → `tool_ranking` / `tool_filter` + `data_kline` 组合
   - 单股分析 → `data_search` → `data_kline` → `data_technical` → `data_profile` → `data_finance` 全链路
   - 实时信号 → `data_quote` 快照模式
   - 回测验证 → `data_kline` 历史数据导出

4. **模块架构变更**：
   - 去除 `scripts/*.py` 模块引用（不再需要独立 Python 脚本层）
   - 新增"能力模块 → MCP 工具"映射表

## 版本历史

### v1.1.0 (2026-06-28) **A股优化版**
**基于A股市场特性进行全面优化**

1. **A股市场特性适配**：
   - **涨跌停限制处理**：自动过滤涨跌停数据，跌停时强制止损
   - **T+1交易制度适配**：更紧的止损设置，更短的动量窗口
   - **政策影响因素**：预留政策事件驱动因子接口
   - **散户行为影响**：提高成交量确认权重

2. **数据源扩展**：
   - 新增东方财富数据源
   - 新增北向资金数据接口
   - 新增融资融券数据接口
   - 新增行业资金流向数据接口
   - 新增涨跌停数据接口

3. **策略参数优化**：
   - **动量窗口**：短期15天/中期45天/长期150天（原20/60/252天）
   - **打分权重**：价格动量25%/相对强度20%/成交量25%/趋势15%/风险15%
   - **动量阈值**：强烈买入75分/买入65分/持有55分/减仓45分/卖出35分

4. **风险管理优化**：
   - **止损策略**：初始止损1.5倍ATR/移动止损0.75倍ATR/时间止损15天
   - **仓位限制**：单股15%/行业25%/总仓位70%
   - **涨跌停风险控制**：跌停强制止损，连续下跌预警

5. **新增A股特有指标**：
   - 北向资金净流入
   - 融资余额变化
   - 涨停家数
   - 换手率

### v1.0.0 (2026-06-28)
**初始版本 - 基于《构建量化动量选股系统的实用指南》**

1. **核心功能实现**：
   - 100分制多维动量打分体系（5个维度）
   - 趋势阶段识别（启动/主升/衰竭/反转）
   - 估值过滤机制（PE/PB分位）
   - 风险管理框架（仓位/止损/止盈）

2. **模块架构**：
   - 数据采集与缓存（data_collector.py）
   - 全市场扫描（scanner.py）
   - 动量打分系统（scoring.py）
   - 单股分析（analyzer.py）
   - 策略核心（strategy.py）
   - 投资组合管理（portfolio.py）
   - 回测引擎（backtest.py）
   - 实时信号（signal.py）
   - 投资组合监控（monitor.py）
   - 报告生成（report.py）

3. **数据源集成**：
   - AKShare作为主要数据源
   - 本地缓存提高效率
   - 多数据源降级策略

4. **使用方式**：
   - 全市场扫描模式
   - 单股分析模式
   - 回测验证模式
   - 实时信号模式

5. **风险提示**：
   - 动量衰减风险
   - 市场系统性风险
   - 个股特异性风险
   - 策略局限性说明

## 与现有技能的配合

### 与 commodity-trend-signal 的配合

- **commodity-trend-signal**：负责商品期货趋势信号发现
- **quantitative-momentum-stock-selection**：负责股票动量选股
- **配合方式**：两个技能独立部署，通过数据字典传递中间结果

### 与 a-share-etf-momentum 的配合

- **a-share-etf-momentum**：负责行业ETF轮动策略
- **quantitative-momentum-stock-selection**：负责个股动量选股
- **配合方式**：ETF轮动提供市场趋势判断，个股选股提供具体标的

## 注意事项

1. **市场适应性**：动量策略在趋势明显的市场中表现最佳，在震荡市中可能表现不佳
2. **参数敏感性**：动量窗口、打分权重等参数需要根据市场环境调整
3. **交易成本**：频繁调仓会产生较高的交易成本，需要权衡收益与成本
4. **流动性风险**：确保选择的股票具有足够的流动性，避免冲击成本过高
5. **历史回测局限性**：过去的表现不代表未来收益，策略需要持续监控和优化