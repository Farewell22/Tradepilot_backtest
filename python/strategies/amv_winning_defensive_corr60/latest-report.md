# 最新运行报告：amv_winning_defensive_corr60

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-10-09T05:55:47.838577+00:00`
- 请求区间：`20190118` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0)
- 运行清单：[data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025](../../../data/backtest_data/ETF_60min_2005_2025)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512890.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512890.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_defensive/dividends_601288.csv](../amv_winning_defensive/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/comparison.csv](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/comparison.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/fixed_etf_pool.csv](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/fixed_etf_pool.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/input_audit.json](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/input_audit.json)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/metrics.json](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/nav.csv](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/pool_audit.csv](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/pool_audit.csv)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/report.md](../../../data/backtest_runs/amv_winning_defensive_corr60__20261009T055547Z__c55b8dd0/report.md)

# 0AMV防守策略：进攻仓60日相关性第一名

区间：20190118—20251231；共同交易日1685；固定候选池1284/1383只。

**探索性回测：固定ETF池按截至2025-12-31完整历史剔除25%疑似断点，使用了未来信息，存在前视偏差。**
**同日收盘信号、相关性和成交属于legacy_same_close_idealized理想化口径。**

## 同期对照

| variant            |   total_return_pct |   annualized_return_pct |   max_drawdown_pct |   primary_buy_count |   closed_trade_count |   win_rate_pct |
|:-------------------|-------------------:|------------------------:|-------------------:|--------------------:|---------------------:|---------------:|
| baseline_512890.SH |             87.652 |                   9.47  |            -25.78  |                  61 |                  102 |         48.039 |
| baseline_601288.SH |            380.265 |                  25.305 |            -21.553 |                  61 |                  103 |         55.34  |
| corr60_512890.SH   |             95.349 |                  10.105 |            -24.754 |                  62 |                  103 |         48.544 |
| corr60_601288.SH   |            399.954 |                  26.031 |            -18.825 |                  62 |                  104 |         55.769 |

## 年度收益

|   year |   baseline_512890.SH |   baseline_601288.SH |   corr60_512890.SH |   corr60_601288.SH |
|-------:|---------------------:|---------------------:|-------------------:|-------------------:|
|   2019 |               17.513 |               25.173 |             18.188 |             25.883 |
|   2020 |               -4.676 |                0.522 |              2.157 |              7.722 |
|   2021 |               -2.486 |                2.203 |              7.034 |             12.179 |
|   2022 |               -2.694 |               -0.94  |             -8.688 |             -7.042 |
|   2023 |               10.259 |               35.842 |              2.154 |             25.858 |
|   2024 |               41.664 |              105.872 |             48.558 |            115.892 |
|   2025 |               13.027 |               34.809 |              9.086 |             30.119 |

## 规则与限制

- 仅实际开进攻仓时选择截至当日的最高corr60，不取绝对值；持仓不因排名变化换仓。重新开仓时重新排序。
- 原策略入场、MA10/MACD退出、2.5%硬止损、超过5%后的跟踪止盈、满仓和防守规则保留。新开仓日可因ETF止损不同而变化。
- 因子要求60对完整市场日收益；名称代理去重、最早有效行情选代表，非官方指数映射及上市日。
- 没有有效候选则保持当前防守或现金。持仓行情缺失报错，不能删交易日或按未来行情换标的。
- ETF未取得完整复权与现金分红；原始价格收益可能残留25%以下除权变化。已知基准512100合并、512890拆分及农行分红保留原记账。
- 保留原费用和同日收盘理想化成交，买入日不做盘中卖出。未模拟盘口容量、涨跌停和停牌成交约束。
- 候选池事后筛选与同日收盘成交均可能夸大可实现表现；本结果不属于严格无前视实盘验证。

逐版本目录保存NAV、逐笔/配对交易、绩效和选股记录；固定池和排除原因见fixed_etf_pool.csv、pool_audit.csv。

512890.SH：总收益变化+7.697个百分点；最大回撤绝对值变化-1.026个百分点。
601288.SH：总收益变化+19.689个百分点；最大回撤绝对值变化-2.729个百分点。
