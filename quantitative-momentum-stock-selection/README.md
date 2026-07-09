# 量化动量选股系统 v1.2.0 — 数据源：腾讯自选股 MCP

基于《构建量化动量选股系统的实用指南》的完整动量选股策略，针对A股市场特性进行全面优化。
**v1.2.0 数据源：腾讯自选股 MCP (westock-mcp connector)，无需 AKShare/Tushare 依赖。**

## 核心理念

**动量投资的本质**：买入赢家股（价格走势强劲的股票），而不是预测未来或寻找成长型股票。

**与价值投资的区别**：
- 价值投资者：买入便宜的"失宠"股
- 动量投资者：勇敢追涨，买入价格走势强劲股

## A股优化特性（v1.2.0）

### 1. 市场特性适配
- **涨跌停限制处理**：自动过滤涨跌停数据，跌停时强制止损
- **T+1交易制度适配**：更紧的止损设置，更短的动量窗口
- **散户行为影响**：提高成交量确认权重（25%）

### 2. 数据源 — 腾讯自选股 MCP
- **行情数据**：`mcp__westock-mcp__data_kline`（日K/周K/月K，支持前复权）
- **多因子排行**：`mcp__westock-mcp__tool_ranking`（综合评分/基本面/技术面/风险/资金）
- **条件选股**：`mcp__westock-mcp__tool_filter`
- **技术指标**：`mcp__westock-mcp__data_technical`（KDJ/MACD/RSI/BOLL）
- **资金流向**：`mcp__westock-mcp__data_fund_flow`
- **北向资金**：`mcp__westock-mcp__data_north_holding`
- **个股概览**：`mcp__westock-mcp__data_profile`
- **财务数据**：`mcp__westock-mcp__data_finance`
- **机构预期**：`mcp__westock-mcp__data_consensus`
- **筹码分布**：`mcp__westock-mcp__data_chip`
- **大盘概览**：`mcp__westock-mcp__data_market_overview`
- **板块数据**：`mcp__westock-mcp__data_sector`
- **实时行情**：`mcp__westock-mcp__data_quote`

### 3. 参数优化
- **动量窗口**：15/45/150天（原20/60/252天）
- **打分权重**：成交量和风险控制权重提高
- **动量阈值**：降低阈值，更早入场离场

## 功能特性

### 1. 多维度动量打分体系（100分制，A股优化版）

| 维度 | 权重 | 指标 | 说明 |
|------|------|------|------|
| **价格动量** | 25分 | 15日收益率、45日收益率、150日收益率 | A股优化后窗口更短 |
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

- **仓位控制**：单股15%/行业25%/总仓位70%
- **止损策略**：初始1.5倍ATR/移动0.75倍ATR/时间15天
- **止盈策略**：阶段式止盈，保护利润
- **涨跌停风险控制**：跌停强制止损，连续下跌预警

## 快速开始

### 前置条件
- 确保 `westock-mcp` connector 已连接（状态：已连接）

### 单股分析流程（MCP 工具链）

```
Step 1: 搜索股票代码 → mcp__westock-mcp__data_search(query="贵州茅台")
Step 2: 获取日线行情 → mcp__westock-mcp__data_kline(code=sh600519, period=day, limit=200, fq=qfq)
Step 3: 技术指标   → mcp__westock-mcp__data_technical(code=sh600519, group=kdj,macd,rsi)
Step 4: 公司概况   → mcp__westock-mcp__data_profile(code=sh600519)
Step 5: 财务数据   → mcp__westock-mcp__data_finance(code=sh600519, type=income)
Step 6: 机构预期   → mcp__westock-mcp__data_consensus(code=sh600519)
Step 7: 资金流向   → mcp__westock-mcp__data_fund_flow(code=sh600519)
Step 8: 北向持股   → mcp__westock-mcp__data_north_holding(code=sh600519)
```

### 全市场动量扫描流程

```
Step 1: 多因子排行 → mcp__westock-mcp__tool_ranking(metric=CompScore, limit=100)
Step 2: 批量K线   → mcp__westock-mcp__data_kline(codes=..., period=day, limit=200)
Step 3: 基本面筛选 → mcp__westock-mcp__tool_filter(expression="PE_TTM<30 AND ROE>10")
Step 4: 技术确认   → mcp__westock-mcp__data_technical(codes=..., group=kdj,macd,rsi)
Step 5: 资金验证   → mcp__westock-mcp__data_fund_flow(code=..., date=)
Step 6: 综合打分   → 按动量打分算法计算各维度分数 → 输出Top N
```

所有数据操作通过 `mcp__westock-mcp__*` 工具完成，无需安装 `akshare` / `tushare` 等第三方 Python 金融数据库。

## 模块说明 — MCP 工具链架构

| 能力模块 | 对应 MCP 工具 |
|---------|--------------|
| **候选池构建** | `data_search`, `tool_filter`, `tool_ranking` |
| **行情数据** | `data_kline(period=day, fq=qfq)` |
| **动量打分** | `data_kline` + `data_technical` |
| **基本面过滤** | `data_profile`, `data_finance`, `data_consensus` |
| **资金流向** | `data_fund_flow`, `data_north_holding` |
| **板块分析** | `data_sector` |
| **市场概览** | `data_market_overview` |
| **实时监控** | `data_quote` |

## 数据源 — 腾讯自选股 MCP

所有数据通过 `westock-mcp` connector 的 `mcp__westock-mcp__*` 工具获取，覆盖 14 类数据操作：

| 数据类型 | MCP 工具 | 参数要点 |
|---------|---------|---------|
| 日线行情 | `data_kline` | `period=day, fq=qfq(前复权)` |
| 行情快照 | `data_quote` | `codes=sh600519,sz000001` |
| 个股概览 | `data_profile` | `code=sh600519` |
| 财务数据 | `data_finance` | `type=income/balance/cashflow` |
| 技术指标 | `data_technical` | `group=kdj,macd,rsi,boll` |
| 资金流向 | `data_fund_flow` | `code=sh600519, start=, end=` |
| 北向资金 | `data_north_holding` | `code=sh600519` |
| 板块数据 | `data_sector` | `mode=constituent, code=板块码` |
| 条件选股 | `tool_filter` | `expression="PE_TTM<20"` |
| 多因子排行 | `tool_ranking` | `metric=CompScore, limit=20` |
| 搜索股票 | `data_search` | `query=茅台, type=stock` |
| 筹码分布 | `data_chip` | `code=sh600519` |
| 机构预期 | `data_consensus` | `code=sh600519` |
| 大盘概览 | `data_market_overview` | `type=summary` |

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

### 风险管理规则

1. **仓位限制**：
   - 单只股票最大仓位：20%
   - 单个行业最大仓位：30%
   - 总仓位上限：80%

2. **止损策略**：
   - 初始止损：买入价下方2×ATR
   - 移动止损：趋势延续时，止损移至近期低点下方1×ATR
   - 时间止损：持有超过20个交易日未盈利，考虑止损

3. **止盈策略**：
   - 第一目标：盈利20%时减仓30%
   - 第二目标：盈利40%时再减仓30%
   - 最终目标：趋势破坏时清仓

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

## 版本历史

### v1.2.0 (2026-07-09) **数据源切换：westock-mcp**
**数据源全面切换至腾讯自选股 MCP，移除 AKShare/Tushare 依赖**

1. **数据源重构**：
   - AKShare/Tushare → 全面替换为 `mcp__westock-mcp__*` 工具链
   - 覆盖 14 类数据操作（行情/财务/技术/资金/北向/板块/筹码/排行/筛选）
   - 无需安装第三方 Python 金融数据库

2. **使用方式变更**：
   - 全市场扫描 → `tool_ranking` + `tool_filter` + `data_kline` 组合
   - 单股分析 → 8 步 MCP 工具链（search→kline→technical→profile→finance→consensus→fund_flow→north_holding）
   - 实时信号 → `data_quote` 快照模式
   - 代码格式：`sh600519` / `sz000001`（westock-mcp 标配）

3. **全链路测试通过**：
   - 14/14 工具连通性验证 100% 通过
   - 2 处参数错误修复（tool_ranking/tool_filter 移除不支持参数）
   - 所有金融字段含义验证一致

### v1.1.0 (2026-06-28) **A股优化版**
**基于A股市场特性进行全面优化**

1. **A股市场特性适配**：
   - 涨跌停限制处理：自动过滤涨跌停数据，跌停时强制止损
   - T+1交易制度适配：更紧的止损设置，更短的动量窗口
   - 散户行为影响：提高成交量确认权重（25%）

2. **数据源扩展**：
   - 新增东方财富数据源
   - 新增北向资金数据接口
   - 新增融资融券数据接口
   - 新增行业资金流向数据接口
   - 新增涨跌停数据接口

3. **策略参数优化**：
   - 动量窗口：15/45/150天（原20/60/252天）
   - 打分权重：成交量25%/风险控制15%
   - 动量阈值：强烈买入75分/买入65分

4. **风险管理优化**：
   - 止损策略：初始1.5倍ATR/移动0.75倍ATR/时间15天
   - 仓位限制：单股15%/行业25%/总仓位70%
   - 涨跌停风险控制：跌停强制止损，连续下跌预警

### v1.0.0 (2026-06-28)
**初始版本 - 基于《构建量化动量选股系统的实用指南》**

1. **核心功能实现**：
   - 100分制多维动量打分体系（5个维度）
   - 趋势阶段识别（启动/主升/衰竭/反转）
   - 估值过滤机制（PE/PB分位）
   - 风险管理框架（仓位/止损/止盈）

2. **模块架构**：
   - 数据采集与缓存（data_collector.py）
   - 动量打分系统（scoring.py）
   - 策略核心（strategy.py）
   - 配置管理（config.py）

3. **数据源集成**：
   - AKShare作为主要数据源
   - 本地缓存提高效率
   - 多数据源降级策略

4. **使用方式**：
   - 全市场扫描模式
   - 单股分析模式
   - 回测验证模式
   - 实时信号模式

## 许可证

MIT License