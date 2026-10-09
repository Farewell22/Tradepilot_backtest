# 最新运行报告：industry_etf_policy_support

- 任务类型：`research`
- 运行时间（UTC）：`2026-09-30T07:48:48.713470+00:00`
- 请求区间：`20201103` ～ `20251028`
- 运行目录：[data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f)
- 运行清单：[data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/run_manifest.json](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/run_manifest.json)
- 输入数据：
  - [data/policy_news/approved_events.jsonl](../../../../data/policy_news/approved_events.jsonl)
  - [data/backtest_data/ETF_60min_2005_2025](../../../../data/backtest_data/ETF_60min_2005_2025)
  - [python/research/policy/industry_etf_policy_support/inputs/corporate_actions.csv](inputs/corporate_actions.csv)
  - [python/research/policy/industry_etf_policy_support/inputs/corporate_action_audit.json](inputs/corporate_action_audit.json)
- 关键结果文件：
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/company_exposures.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/company_exposures.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/concept_relations.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/concept_relations.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/etf_coverage.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/etf_coverage.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/etf_exposures_asof.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/etf_exposures_asof.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/event_summary.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/event_summary.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/execution_metadata.json](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/execution_metadata.json)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/observations.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/observations.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_clauses.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_clauses.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_concepts.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_concepts.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_documents.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_documents.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_industry_labels.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/policy_industry_labels.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/research_metadata.json](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/research_metadata.json)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/same_day_controls.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/same_day_controls.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/summary.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/summary.csv)
  - [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/unmapped_policy_themes.csv](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/unmapped_policy_themes.csv)

## 本次报告

### [data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/report.md](../../../../data/factor_research_runs/industry_etf_policy_support__20260930T074848Z__fa42288f/report.md)

# 政策支持行业 ETF 事件研究

政策事件 3 条；已核验 ETF 观测 0 条；60 日为预先指定主窗口。

## 分类结果

暂无可计算的收益观测。

## 覆盖与排除

{
  "selected_events": 3,
  "unique_events": 3,
  "duplicate_theme_events": 0,
  "event_statuses": {
    "ETF_EXPOSURE_UNVERIFIED": 3
  },
  "missing_by_reason": {},
  "valid_observations": 0,
  "horizons": [
    20,
    60,
    120,
    250
  ],
  "primary_horizon": 60,
  "return_basis": "next eligible open to horizon-th close; ex-close dividend reinvestment; zero fees"
}

## 口径与限制

只有审批事件且 ETF 上市、历史暴露和公司行动覆盖都核验时才计算收益。日期精度的消息保守地视为收盘后公开；第 1 个交易日为入场日。收益为统计标签，忽略交易费用，分红在除息日收盘再投资。样本按事件展示；同一规划下多只 ETF 不是独立政策冲击。未核验关联、未上市工具和未成熟窗口不填零，也不推断政策因果效应。
