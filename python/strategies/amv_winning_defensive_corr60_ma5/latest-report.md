# 最新运行报告：amv_winning_defensive_corr60_ma5

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-10-09T06:41:43.497428+00:00`
- 请求区间：`20190118` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f)
- 运行清单：[data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025](../../../data/backtest_data/ETF_60min_2005_2025)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512890.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512890.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_defensive/dividends_601288.csv](../amv_winning_defensive/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/branch_statistics.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/branch_statistics.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/comparison.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/comparison.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/exit_statistics.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/exit_statistics.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/fixed_etf_pool.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/fixed_etf_pool.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/input_audit.json](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/input_audit.json)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/metrics.json](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/nav.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/pool_audit.csv](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/pool_audit.csv)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/report.md](../../../data/backtest_runs/amv_winning_defensive_corr60_ma5__20261009T064143Z__19572b6f/report.md)

# 0AMV动态进攻：MA5上穿与分档净收益退出

区间：20190118—20251231；共同交易日1685；固定候选池1284/1383只。

**探索性回测：固定ETF池按截至2025-12-31完整历史剔除25%疑似断点，使用了未来信息，存在前视偏差。**
**同日收盘信号、相关性和成交属于legacy_same_close_idealized理想化口径。**

## 同期对照

| variant            |   total_return_pct |   annualized_return_pct |   max_drawdown_pct |   primary_buy_count |   closed_trade_count |   win_rate_pct |
|:-------------------|-------------------:|------------------------:|-------------------:|--------------------:|---------------------:|---------------:|
| baseline_512890.SH |             95.349 |                  10.105 |            -24.754 |                  62 |                  103 |         48.544 |
| control_512890.SH  |             70.897 |                   8.008 |            -28.157 |                  99 |                  167 |         44.91  |
| ma5_512890.SH      |             50.129 |                   6.015 |            -37.364 |                 108 |                  176 |         44.318 |
| baseline_601288.SH |            399.954 |                  26.031 |            -18.825 |                  62 |                  104 |         55.769 |
| control_601288.SH  |            262.259 |                  20.327 |            -20.795 |                  99 |                  167 |         47.904 |
| ma5_601288.SH      |            218.229 |                  18.106 |            -22.25  |                 108 |                  176 |         47.159 |

## 年度收益

|   year |   baseline_512890.SH |   baseline_601288.SH |   control_512890.SH |   control_601288.SH |   ma5_512890.SH |   ma5_601288.SH |
|-------:|---------------------:|---------------------:|--------------------:|--------------------:|----------------:|----------------:|
|   2019 |               18.188 |               25.883 |              23.159 |              33.204 |          17.124 |          26.673 |
|   2020 |                2.157 |                7.722 |               5.662 |               9.319 |           6.962 |          10.675 |
|   2021 |                7.034 |               12.179 |               4.111 |              11.129 |           4.068 |          11.079 |
|   2022 |               -8.688 |               -7.042 |              -7.242 |              -2.368 |         -17.254 |         -12.905 |
|   2023 |                2.154 |               25.858 |               2.972 |              23.221 |          -1.594 |          17.743 |
|   2024 |               48.558 |              115.892 |              36.663 |              95.876 |          43.359 |         105.461 |
|   2025 |                9.086 |               30.119 |              -3.366 |              -5     |          -1.353 |          -3.011 |

## 规则与限制

- 仅实际开进攻仓时选择截至当日的最高corr60，不取绝对值；持仓不因排名变化换仓。重新开仓时重新排序。
- baseline只开原高质量信号；control增加MA5严格上穿，但均用原退出；ma5对弱仓增加分档净止盈止损和时间退出。高质量原条件保留。
- 弱仓原ETF升级强仓不产生交易，不重置真实成本。盘中退出优先于收盘升级，AMV退出优先于升级，升级优先于时间退出。
- 弱仓持有上限为买入后第3个共同交易日；分档为((0.015, 0.01, 0.015), (0.03, 0.0125, 0.02), (inf, 0.015, 0.025))，分别是涨幅上限、净止损比例、净止盈比例。分档按开仓日冻结。
- 同根60分钟K线先处理跳空开盘；未跳空且同时触及止盈止损时止损优先。弱仓退出当日禁止重开。
- 因子要求60对完整市场日收益；名称代理去重、最早有效行情选代表，非官方指数映射及上市日。
- 没有有效候选则保持当前防守或现金。持仓行情缺失报错，不能删交易日或按未来行情换标的。
- ETF未取得完整复权与现金分红；原始价格收益可能残留25%以下除权变化。已知基准512100合并、512890拆分及农行分红保留原记账。
- 保留原费用和同日收盘理想化成交，买入日不做盘中卖出。未模拟盘口容量、涨跌停和停牌成交约束。
- 候选池事后筛选与同日收盘成交均可能夸大可实现表现；本结果不属于严格无前视实盘验证。

逐版本目录保存NAV、逐笔/配对交易、绩效和选股记录；固定池和排除原因见fixed_etf_pool.csv、pool_audit.csv。


## 入场分支平仓贡献

| variant            | entry_branch   |   trades |      pnl |   mean_pnl_pct |   win_rate_pct |
|:-------------------|:---------------|---------:|---------:|---------------:|---------------:|
| baseline_512890.SH | defense        |       41 | -18323.4 |         -0.16  |         41.463 |
| baseline_512890.SH | high           |       62 | 214186   |          1.403 |         53.226 |
| control_512890.SH  | defense        |       68 | -59586   |         -0.281 |         45.588 |
| control_512890.SH  | high           |       48 | 216998   |          1.861 |         58.333 |
| control_512890.SH  | weak           |       51 | -15619.4 |         -0.047 |         31.373 |
| ma5_512890.SH      | defense        |       68 | -56906.3 |         -0.281 |         45.588 |
| ma5_512890.SH      | high           |       55 | 176602   |          1.452 |         52.727 |
| ma5_512890.SH      | weak           |       53 | -19437.2 |         -0.128 |         33.962 |
| baseline_601288.SH | defense        |       42 | 425013   |          2.086 |         59.524 |
| baseline_601288.SH | high           |       62 | 374895   |          1.403 |         53.226 |
| control_601288.SH  | defense        |       68 | 222868   |          0.837 |         52.941 |
| control_601288.SH  | high           |       48 | 341582   |          1.861 |         58.333 |
| control_601288.SH  | weak           |       51 | -39931.1 |         -0.047 |         31.373 |
| ma5_601288.SH      | defense        |       68 | 183652   |          0.837 |         52.941 |
| ma5_601288.SH      | high           |       55 | 287943   |          1.452 |         52.727 |
| ma5_601288.SH      | weak           |       53 | -35136.4 |         -0.128 |         33.962 |

512890.SH：总收益变化-45.220个百分点；最大回撤绝对值变化+12.611个百分点。
601288.SH：总收益变化-181.725个百分点；最大回撤绝对值变化+3.426个百分点。
