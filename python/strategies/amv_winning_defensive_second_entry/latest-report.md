# 最新运行报告：amv_winning_defensive_second_entry

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-29T07:44:31.635167+00:00`
- 请求区间：`20200102` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173)
- 运行清单：[data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_defensive/dividends_601288.csv](../amv_winning_defensive/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/amv_signals.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/amv_signals.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/annual_returns.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/annual_returns.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/comparison_nav.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/comparison_nav.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/metrics.json](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/metrics.json)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/nav.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/nav.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/paired_trades.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/paired_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/primary_trades.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/primary_trades.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/signal_trade_stats.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/signal_trade_stats.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/source_manifest.json](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/source_manifest.json)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/trades.csv](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/trades.csv)
  - [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/verification.json](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/verification.json)

## 本次报告

### [data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/report.md](../../../data/backtest_runs/amv_winning_defensive_second_entry__20260929T074431Z__d81ce173/report.md)

# 农行直接防守：单日≥4%或二类P60–P80买点

区间 20200102—20251231，1454个交易日，初始资金 200,000 元。

主仓买点一为0AMV单日≥4%；买点二为MA10>MA30、正gap10首次进入[P60,P80)。两类均要求收盘≥MA5，离场优先，全仓整手买入512100；同时满足时归因于买点一。

| 成交口径 | 入场规则 | 总收益 | 年化 | 最大回撤 | 夏普 | 主仓买入次数 | 主仓闭合胜率 |
|---|---|---:|---:|---:|---:|---:|---:|
| 次日开盘（主结果） | 仅单日 | 391.21% | 30.38% | -18.49% | 1.877 | 32 | 65.62% |
| 次日开盘（主结果） | 单日+二类 | 337.93% | 27.91% | -18.92% | 1.696 | 46 | 52.17% |
| 同日收盘（理想化） | 仅单日 | 330.96% | 27.57% | -20.38% | 1.711 | 32 | 59.38% |
| 同日收盘（理想化） | 单日+二类 | 319.57% | 27.00% | -22.25% | 1.639 | 45 | 51.11% |

## 主仓完整交易：按入场买点统计

| variant             | entry_branch       |   closed_positions |   wins |   win_rate_pct |   avg_net_pnl_pct |   total_pnl |
|:--------------------|:-------------------|-------------------:|-------:|---------------:|------------------:|------------:|
| second_entry        | class_2_gap        |                 17 |      4 |          23.53 |             -0.34 |    29103.17 |
| second_entry        | single_day_ge_4pct |                 29 |     20 |          68.97 |              2.81 |   285243.18 |
| single_day          | single_day_ge_4pct |                 32 |     21 |          65.62 |              2.46 |   318025.95 |
| legacy_second_entry | class_2_gap        |                 16 |      5 |          31.25 |              0.05 |    41963.42 |
| legacy_second_entry | single_day_ge_4pct |                 29 |     18 |          62.07 |              2.44 |   254172.17 |
| legacy_single_day   | single_day_ge_4pct |                 32 |     19 |          59.38 |              2.09 |   260767.93 |

## 年度收益

|    year |   second_entry_return_pct |   single_day_return_pct |   legacy_second_entry_return_pct |   legacy_single_day_return_pct |
|--------:|--------------------------:|------------------------:|---------------------------------:|-------------------------------:|
| 2020.00 |                      3.23 |                    6.04 |                             1.20 |                           1.56 |
| 2021.00 |                     -2.91 |                   10.82 |                            -2.09 |                          10.78 |
| 2022.00 |                     16.24 |                   17.53 |                            11.28 |                           6.90 |
| 2023.00 |                     27.39 |                   27.39 |                            28.57 |                          28.56 |
| 2024.00 |                    113.69 |                  132.19 |                           115.19 |                         132.70 |
| 2025.00 |                     38.10 |                   20.23 |                            37.54 |                          19.77 |

## 规则与限制

主结果与单日基线均从现金启动，信号于收盘确认、下一共同交易日开盘执行；区间最后一天的信号不再执行。主仓买入日不可卖出，遵守T+1。
0AMV低于MA10或MACD死叉优先离场，次日开盘转农行。主仓盘中2.5%硬止损；浮盈超过5%后次日起按前日实体低点跟踪退出。盘中退出当天的主仓买入信号被取消，若有0AMV离场信号仍于次日转农行。
农行无止损，费用后净价差8%止盈（现金股息不计入阈值）；止盈后现金锁定直到有效主仓买点。再次进场时先卖出全部农行，再全仓买入512100。
750个历史有效MA10>MA30观察值计算分位，至少250个预热，仅使用此前数据。P80上界不含、已有主仓时不重复开仓。
同日收盘对照保留原策略理想化时点；两种成交口径分别比较，不将差异全部归于新买点。
交易费用、100份/股整手、农行税前现金股息及主仓份额合并沿用原模型。农行除息日开盘卖出仍享有此前持仓股息，当日新买入不享有。ETF现金派息仍沿用原策略未单独记账的口径。
年化按365自然日，夏普按243交易日。期末持仓估值但不计作闭合交易。固定旧税费、未完整模拟股息税和到账延迟、涨跌停、停牌及成交容量。
新增分支交易会改变后续主仓与农行路径，其逐笔盈亏不等于相对基线的增量收益。
inputs/、code_snapshot/和source_manifest.json保存输入、代码与SHA256；baseline/是次日开盘单日版，legacy_same_close/是两组原成交口径对照。
