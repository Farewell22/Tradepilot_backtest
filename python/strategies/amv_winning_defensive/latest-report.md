# 最新运行报告：amv_winning_defensive

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-10-09T05:47:12.081505+00:00`
- 请求区间：`20190118` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04)
- 运行清单：[data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/run_manifest.json](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512890.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512890.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_defensive/dividends_601288.csv](dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/metrics.json](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/metrics.json)
  - [data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/nav.csv](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/nav.csv)
  - [data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/trades_512890.SH.csv](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/trades_512890.SH.csv)
  - [data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/trades_601288.SH.csv](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/trades_601288.SH.csv)
  - [data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/trades_original.csv](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/trades_original.csv)

## 本次报告

### [data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/report.md](../../../data/backtest_runs/amv_winning_defensive__20261009T054712Z__44dd6e04/report.md)

# 0AMV 必胜策略：0AMV 离场后全仓防守

区间：2019-01-18 至 2025-12-31；共同交易日：1685。

| 模式 | 总收益 | 年化收益 | 最大回撤 |
| --- | ---: | ---: | ---: |
| 原版现金 | 135.07% | 13.07% | -18.98% |
| 红利低波 512890 | 87.65% | 9.47% | -25.78% |
| 农业银行 601288 | 380.27% | 25.30% | -21.55% |

仅 0AMV 跌破 MA10 或 MACD 死叉时，卖出 512100 并在当天收盘买入防守标的；
512100 盘中触发 2.5% 硬止损或盈利后的跟踪止盈时，卖出后持现金；若当天另有 0AMV 离场信号，则仍转入防守标的。
农业银行买入后的交易日起，5 分钟最高价达到扣除买卖费用后净价差收益 +8% 时全仓止盈；跳空越过阈值按开盘价卖出。
农业银行止盈后持现金，直到下一次有效 0AMV 买入信号；连续离场信号不重复买入。红利低波 ETF 不设此止盈。
下一次有效进场信号按当天收盘卖出仍持有的防守仓、买回 512100。离场优先。

因红利低波无行情而排除的日期：20211022。
因农业银行无行情而排除的日期：无。
0AMV 日线信号在收盘后才能确认，同日收盘成交是理想化假设。
ETF 与股票分别计佣金、滑点，股票额外计印花税和过户费；均按整百份/股交易。
农业银行仅在除息日前已持仓时按公开分红公告计入每股现金红利；止盈阈值不含分红，卖出时不重复加现金红利；未计个人持股期相关股息税。
512890 于 2021-10-22 的 1:2 份额拆分已计入；现金分红按零处理。
未模拟涨跌停、停牌期间的不可成交和尾盘流动性冲击。
本次运行的执行代码快照与 SHA-256 见 code_snapshot/manifest.json。
