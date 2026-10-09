# 本地清洁样本模式（2026-10-09）

用户允许使用尽量正常的本地ETF行情。统一入口默认采用 `local_screen`，无需下载辅助资料：

```bash
./scripts/backtest.sh run research amv_entry_corr60
```

60日因子是截至事件收盘的ETF日价格变化与0AMV日变化的Pearson相关性，要求60对完整日收益。
以原策略两个防守版本实际进攻仓买入日并集去重，次日开盘至第5/10/20个市场交易日收盘计算收益。
本地分钟数据先去重聚合，要求4根完整60分钟K线及有效OHLC、正日成交量。
相邻有效报价收盘或隔夜开盘绝对跳变超过25%时标记疑似断点；受影响的因子窗口和远期收益标签设为缺失。
未来断点不能取消此前样本；代表选择先于未来标签，缺失标签不换基金。

名称去除已知管理人及ETF字样，保留ESG、增强等变体；300/500/1000等明确简称归一化。
同名称组以首次有效行情日期、代码选择代表。它只是去重代理，不能视为已核验的指数映射或上市日期。
收益为未复权价格收益，不含分红、费用，25%以下分红除权或份额变化可能残留。
疑似断点可能包含真实大涨跌，筛选属于数据质量控制；结果不能解释为全市场无偏估计或总回报。

产物包括 `suspected_price_breaks.csv`、`etf_audit.csv`、`dedup_audit.parquet`、`coverage.csv`、
`observations.parquet`、`event_statistics.csv`、`summary.csv`、`report.md`及输入代码快照。
Python接口 `run_research(..., price_mode="verified")` 保留严格辅助资料模式（也是Python默认）。

---

# 0AMV 60日相关性：原策略进攻仓开仓日截面

本地行情固定读取 `data/backtest_data/ETF_60min_2005_2025`。新增任务不会重新下载或改写分钟行情。
原策略仅作为时间事件来源：从2019-01-18开始重跑 `amv_winning_defensive`，
两种防守版本中512100实际买入日期取并集去重，并保存源策略结果、配置、代码快照与差异日期。

## 运行

```bash
python -m python.research.etf.amv_entry_corr60.prepare
./scripts/backtest.sh run research amv_entry_corr60 --start 20190118 --end 20251231
```

`--start/--end` 只过滤开仓观察日期；源策略固定从2019-01-18重跑，因子读取区间前的预热历史，
收益标签可以读取区间后的已存在行情。默认研究截止2025-12-31，与本地ETF行情一致。
费用为零的研究价格收益，源策略仍用其默认真实费用决定实际开仓日。

## 辅助资料

原始分钟文件不包含跟踪指数、上市日期或完整复权资料。准备阶段优先探测
[Tushare ETF基础资料](https://tushare.pro/document/2?doc_id=385)和
[基金复权因子](https://tushare.pro/document/2?doc_id=199)。所有请求使用HTTPS，空返回不是成功。
仅获取辅助资料，**不下载历史价格**。

当前ETF基础接口只提供当前目录，不能证明基金历史上一直跟踪同一个指数。
因此自动取得的当前目录只保存为 `metadata_candidates.csv`，不擅自回填历史。
准备阶段支持导入已核验的历史映射及每日乘数：

```bash
python -m python.research.etf.amv_entry_corr60.prepare \
  --metadata /path/to/verified_index_history.csv \
  --adjustments /path/to/daily_fund_adjustments.parquet
```

历史映射CSV列：

| 字段 | 含义 |
| --- | --- |
| code / name | ETF代码（含.SH/.SZ）及名称 |
| index_id | 统一跟踪指数标识；沪深300、500、1000、800的常见交易所别名会归并 |
| list_date | 核实的上市日期，不能用本地行情起点或基金成立日替代 |
| valid_from / valid_to | 已核验该跟踪关系的有效闭区间；valid_to为空表示延续 |
| source_url | 可核实的公开资料来源 |

同代码区间不得重叠。来源可为交易所或基金公司历史招募书、基金合同及变更公告。
导入每日复权资料列为 `code,date,adj_factor`，不允许缺失日填1或不明乘数前填。
若没有传入复权文件，尝试为已核验映射的ETF获取Tushare逐日因子。
不直接复用股票研究的新浪 `hfq.js` 解析器：ETF中的 `f/s/u` 含份额和现金信息，不能只取 `f`。

缓存目录为 `data/factor_research_data/amv_entry_corr60`。准备清单保存来源文件哈希、
获取时间、接口失败及逐只覆盖审计。无可用基金时prepare退出1，但保留审计文件。
资料缺失ETF逐只排除；没有合格截面或不能计算IC时研究失败，保留审计和源策略事件，不发布正式结论。

## 因子与收益

截至开仓日收盘，ETF前复权收盘收益率与0AMV收盘变化率最近60个市场交易日Pearson相关性。
要求连续市场日历上60对有效收益，即61个收盘价；缺失/停牌不压缩日历。
收益为次一市场日开盘到第5/10/20个后续市场日收盘；缺失端点不顺延。
同指数每个日期选择已上市、映射有效、因子有效的最早上市ETF；同日上市按代码排序。
未来标签不足时不替换代表。

按日期分Q1—Q5，至少10只且5个不同因子值。同分用平均秩，不强行拆组。
分组和代表选择先于未来标签过滤。基准为同日、同窗口代表ETF中标签有效者的等权收益。
先日期内统计，再日期等权汇总。IC是截面Spearman相关；95%区间采用重叠窗口时间簇bootstrap，
2000次、种子42，至少10簇。2019—2023与2024—2025仅作描述性比较，不宣称严格未知样本外。

## 产物

运行目录位于 `data/factor_research_runs/amv_entry_corr60__...`：

- `events.csv`、`source_strategy/`：实际开仓日期、版本差异、原策略结果和来源快照。
- `observations.parquet`、`dedup_audit.parquet`：日期×代表ETF、相关系数、分组、收益、超额和缺失原因；去重前记录与选择原因。
- `event_statistics.csv`、`summary.csv`、`report.md`：逐日期统计、日期等权汇总及报告。
- `etf_audit.csv`、`coverage.csv`：逐基金排除原因及逐日期去重/标签数量。
- `input_audit.json`、`inputs/`、`code_snapshot/`、`research_metadata.json`、`run_manifest.json`：来源、代码、配置及运行状态。

本地目录可能遗漏退市基金，参考资料不足也会带来选择偏差；覆盖子集不能解释成全市场ETF。
