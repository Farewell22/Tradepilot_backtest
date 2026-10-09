# 最新运行报告：amv_winning

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-28T14:16:55.342664+00:00`
- 请求区间：`20200101` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning__20260928T141655Z__0456a927](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927)
- 运行清单：[data/backtest_runs/amv_winning__20260928T141655Z__0456a927/run_manifest.json](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/5m_price](../../../data/backtest_data/5m_price)
  - [python/strategies/amv_winning_defensive/dividends_601288.csv](../amv_winning_defensive/dividends_601288.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/annual_returns.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/annual_returns.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/bank_weekly_kdj.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/bank_weekly_kdj.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/metrics.json](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/metrics.json)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/nav.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/nav.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/original_nav.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/original_nav.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/original_trades.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/original_trades.csv)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/source_manifest.json](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/source_manifest.json)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/strategy_config.json](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/strategy_config.json)
  - [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/trades.csv](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/trades.csv)

## 本次报告

### [data/backtest_runs/amv_winning__20260928T141655Z__0456a927/report.md](../../../data/backtest_runs/amv_winning__20260928T141655Z__0456a927/report.md)

# 0AMV 必胜策略回测报告

主仓：`512100.SH`；农业银行：`601288.SH`；区间：`2020-01-02～2025-12-31`；初始资金：200,000 元。

> 执行口径：0AMV 信号、动态周线 J 和 ETF 收盘价在收盘后最终确定，本回测沿用“信号日收盘成交”的理想化假设（legacy_same_close_idealized）。

## 交易规则

主仓任何规则卖出后开始观察农业银行；初始现金阶段不买银行。每日收盘以该标的截至当天的当周周线计算 KDJ(9,3,3)，J<10 时用可用现金全仓买入，整百份/股取整。
有效主仓进场信号优先：卖出全部农业银行后按原规则买回主仓。主仓同日买卖信号冲突仍以离场优先；其余止损、跟踪止盈规则不变。
农业银行 以实际买入成交价上涨 8% 盘中止盈，无止损，J 回升不卖出。止盈当天不回买银行，最早下一交易日收盘再次检查 J<10；有效主仓进场信号始终优先。目标价不包含卖出费用，净收益可能低于 8%。 股票止盈目标价向上取整到 0.01 元。

## 收益与风险

| 指标 | 改造后策略 | 原纯现金策略 | 买入持有基准 |
|---|---:|---:|---:|
| 总收益率 | 114.19 | 80.60 | 54.39 |
| 年化收益率 | 13.54 | 10.35 | 7.51 |
| 最大回撤 | -18.54 | -18.98 | -45.82 |
| 夏普比率 | 1.03 | 0.88 | 0.42 |

策略完成 73 笔交易，胜率 46.58%，资金暴露 45.39%。
农业银行完成 18 笔交易，已实现盈亏 44,063.62 元，资金暴露 18.50%。
期末持仓：{"entry_date": "20251216", "quantity": 55700, "reference_price": 7.37736988544464, "code": "601288.SH", "dividend_income": 0.0}。

## 年度收益

|    year |   strategy_return_pct |   original_strategy_return_pct |   benchmark_return_pct |
|--------:|----------------------:|-------------------------------:|-----------------------:|
| 2020.00 |                 19.06 |                          23.07 |                  28.67 |
| 2021.00 |                  0.09 |                          -4.74 |                  24.30 |
| 2022.00 |                 -5.72 |                          -4.07 |                 -21.40 |
| 2023.00 |                  3.94 |                           3.94 |                  -5.30 |
| 2024.00 |                 41.39 |                          33.62 |                   1.94 |
| 2025.00 |                 29.73 |                          15.62 |                  27.23 |

## 退出原因

{
  "hard_stop_2.5pct": 21,
  "profit_trail_body_break_5pct": 16,
  "amv_buy_signal_rotate_back": 16,
  "amv_close_below_ma10": 14,
  "amv_macd_dead_cross": 3,
  "bank_take_profit_8pct": 2,
  "amv_close_below_ma10_and_macd_dead_cross": 1
}

## 数据与复现

周线使用回测起点前的银行历史行情预热，不足 9 周时不触发买入。仅使用截至各观察日的行情；本周后续价格不会影响此前 J 值。
农行原始行情与成交额/成交量均价核对，成交和估值使用未复权价格；指标从现金分红生效日起向前连续化，不利用未来分红回改历史 J。农行不套用银行 ETF 拆分。
农业银行沿用相邻策略的固定 stock_legacy 股票费用，卖出印花税 0.001、双向过户费 0.00001（可在配置 bank_fees 覆盖），佣金和滑点跟随主仓；实际本次费用详见 metrics.json 的 bank_fees。没有模拟历史税率变更。分红按相邻策略公告表，仅前一交易日收盘持有的股份在除息日获得现金；卖出交易 PnL 包含所属税前分红，现金只记一次。未扣个人股息税，分红留在现金、不自动追加农行股份。 原纯现金版本和买入持有基准使用相同主仓日期、初始资金与费用。
回测日历沿用原主仓有效交易日；银行缺失必需日期行情会报错。未单独模拟盘口容量、涨跌停无法成交或额外基金现金派息；期末持仓按收盘价估值，不强制卖出。
