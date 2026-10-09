# 0AMV 60日相关性开仓日截面：实现与数据状态

目前完成研究代码、样例验证、原策略全历史重跑及覆盖审计，**尚无正式因子收益结论**。

## 实际时间样本

来源为amv_winning_defensive现有代码，默认资金、费用、止损、同日收盘成交及共同交易日规则。
重跑区间2019-01-18—2025-12-31，共1685个共同交易日。两种防守版本的实际512100买入日期完全一致，
合并去重后61个日期，首日2019-02-11、末日2025-08-28。

| 年份 | 去重开仓日数 |
| --- | ---: |
| 2019 | 10 |
| 2020 | 11 |
| 2021 | 6 |
| 2022 | 9 |
| 2023 | 7 |
| 2024 | 11 |
| 2025 | 7 |

来源：[events.csv](../../data/factor_research_runs/amv_entry_corr60__20261009T040458Z__8ab3d94f/events.csv)、
[源策略结果](../../data/factor_research_runs/amv_entry_corr60__20261009T040458Z__8ab3d94f/source_strategy/report.md)。

## 辅助资料缺口

指定目录内1383只ETF的历史行情存在，未重新下载。
这些分钟文件不提供可核验的历史跟踪指数、上市日期及每日复权乘数。
当前Tushare HTTPS接口探测发生TLS连接失败；没有把空响应当作成功。
因此1383只均记为缺少辅助资料，没有生成五分组收益、IC或任何有效性结论。

[逐基金排除原因](../../data/factor_research_runs/amv_entry_corr60__20261009T040458Z__8ab3d94f/etf_audit.csv)、
[逐日期覆盖数量](../../data/factor_research_runs/amv_entry_corr60__20261009T040458Z__8ab3d94f/coverage.csv)、
[失败运行清单](../../data/factor_research_runs/amv_entry_corr60__20261009T040458Z__8ab3d94f/run_manifest.json)。

## 恢复运行

研究入口：`./scripts/backtest.sh run research amv_entry_corr60`。
资料准备与导入字段见[任务说明](../../python/research/etf/amv_entry_corr60/README.md)。
只有取得历史有效区间、上市日期及正的逐日复权乘数后，才可产生正式收益结果；资料不足者按已确认规则排除。
