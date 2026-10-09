# 政策支持行业 ETF 事件研究

研究单位是“经审批的政策主题事件 × 事件时已有可核验暴露的行业 ETF”。只做分类因子研究，不生成交易指令。数据准备见[政策新闻管理说明](../../../policy_news/README.md)；总体方法见[研究方案](../../../../docs/政策支持行业ETF因子研究方案.md)。

## 运行

```bash
python -m python.policy_news export
./scripts/backtest.sh list research
./scripts/backtest.sh run research industry_etf_policy_support --start 20201103 --end 20251028
```

`--start/--end` 筛选政策首次公开日；研究仍需读取这段日期之后的行情。原始行情在 `data/backtest_data/ETF_60min_2005_2025/<代码>.csv`。任务将 60 分钟 K 线按日合并，以发布后可交易的下一开盘价买入，第 20/60/120/250 个交易日收盘观察；60 日为预先指定主窗口。只有公开日期而无时分的消息按当日收盘后可见。ETF 和 `510300.SH` 使用相同入场日与退出日；分红在除息日收盘再投资，份额变动按核验的生效日处理，研究费用为零。

在 `inputs/corporate_actions.csv` 逐条录入所需 ETF 和基准的分红、拆并份额数据，在 `inputs/corporate_action_audit.json` 中逐只标记 `status: verified`、`coverage_start`、`coverage_end` 和 `source_url`。当前审计文件没有已核验基金，因此真实政策条款不会被算出收益。只有核对完整历史后才能标为 `verified`，其中“没有公司行动”也需证据。行情缺口、停牌、未成熟窗口和审计缺口分开写入 `missing_reason`，不能填零。2026 年的“十五五”《纲要》还需补齐 2026 年 ETF 行情。

首批四份原文已存入本地快照：生态环境部转载的[“十四五”《建议》](https://www.mee.gov.cn/zcwj/zyygwj/202011/t20201103_806153.shtml)与[“十五五”《建议》](https://www.mee.gov.cn/ywdt/szyw/202510/t20251028_1130924.shtml)，发改委发布的[“十四五”《纲要》PDF](https://www.ndrc.gov.cn/xxgk/zcfb/ghwb/202103/P020210313315693279320.pdf)与[“十五五”《纲要》PDF](https://www.ndrc.gov.cn/fggz/fzzlgh/gjfzgh/202603/U020260317369114704096.pdf)。两份《建议》共审核了 3 条示例条款，均未核实事件当时 ETF 历史暴露，`new_support` 也暂不定性。两份《纲要》仍处于待审状态，全文最早公开日、此前已公开内容的比较及 ETF 映射尚未完成；PDF 文件名或转载日期不能自动充当最早事件时点。

运行目录在 `data/factor_research_runs/industry_etf_policy_support__.../`，包括：

- `policy_documents.csv`、`policy_clauses.csv`、`policy_industry_labels.csv`：政策正文证据和分类。
- `policy_concepts.csv`、`concept_relations.csv`、`company_exposures.csv`、`etf_exposures_asof.csv`、`unmapped_policy_themes.csv`：新兴主题关联与未映射状态。
- `etf_coverage.csv`、`observations.csv`、`event_summary.csv`、`same_day_controls.csv`、`summary.csv`、`report.md`：行情覆盖、逐对标签、按事件统计和分类汇总。
- `run_manifest.json`、`execution_metadata.json`、`inputs/`：运行状态、代码及数据哈希、政策导出、所选原文和公司行动输入快照。行情文件较大，仅存路径和哈希。

同一政策日只有同时存在可交易的“新增支持”和“延续支持”ETF 时，才生成同日对照。当前没有全市场“未涉及行业”及历史已上市 ETF 完整目录，不能把项目本地 ETF 文件夹当成那个对照池。报告中的分组均值只是描述统计；五年规划事件少，同日 ETF 相关性高，不能当成独立因果样本。
