# 政策新闻管理（第一版）

本模块把官方政策全文转成可审核的时间线。导入不会产生研究信号；只有人工核对原文、首次公开时间和映射后，`approve` 才会把条款纳入研究。底层数据在 `data/policy_news/`，不入 Git；原始 HTML/PDF 以 SHA-256 命名，审批快照不可覆盖。

## 操作

从项目根目录执行：

```bash
python -m python.policy_news import-url 'https://www.mee.gov.cn/ywdt/szyw/202510/t20251028_1130924.shtml'
python -m python.policy_news list
python -m python.policy_news show policy_f924d66c35df38f1
```

导入返回 `draft.yaml` 和正文 `.txt` 的路径。先核对网页标题、全文公开日、正文、章节及最早公开来源，然后编辑 `draft.yaml`。可参考[已审核的“十五五”《建议》示例](../research/policy/industry_etf_policy_support/examples/fifteen_five_suggestion_review.yaml)。示例中的 `change_vs_previous: unknown` 和 `ETF_EXPOSURE_UNVERIFIED` 是有意保留的未核验状态，不能解释成政策没有影响。

```bash
python -m python.policy_news validate policy_f924d66c35df38f1
python -m python.policy_news approve policy_f924d66c35df38f1
python -m python.policy_news export
```

`export` 生成 `approved_events.jsonl`、`timeline.csv`、`sources.csv` 和包含未审原文的 `source_inventory.csv`。改动稿件后再次审核会产生新审批版本，`current_approval.txt` 指向研究当前使用的版本。重复审核相同稿件保持同一版本。若官方网站同一 URL 的正文已变，重新导入生成 `candidate-<哈希>.yaml`；检查后用 `adopt-candidate <document_id> <16位哈希>` 切换待审稿，原待审稿留作备份。旧审批记录始终保留。

HTML 用内置解析器抽取正文；PDF 用 `pdftotext`。审核时会从原始快照重新抽取并比较正文，防止修改 `.txt` 后伪造引文。扫描件抽不出文本时标为 `needs_manual_text`，应人工录入正文并填写 `transcription_review_note` 说明复核方式；第一版不做 OCR。只有 `*.gov.cn` 的 HTTPS 网页可导入；转载页与其原始首发页要分开记录。

## 条款结构

每条条款必须填写可在正文快照中找到的 `quote`、`section`、`first_public_at`、`first_public_url`、`theme_id`、`industry_id`、`policy_action`、`support_type`、`change_vs_previous`、`relation`、`mapping_reason`、`review_status: approved` 和 `etf_status`。标题只定位文件，不能单凭标题生成支持事件。只有日期时按当日收盘后才可见；含时分的时间必须带时区。

`support_type` 可选 `directional`、`quantitative`、`funding_project`、`constraint`、`mixed`、`unclear`。`change_vs_previous` 可选 `new`、`enhanced`、`continued`、`weakened`、`unknown`。导出时只给明确支持且新增或增强的条款 `new_support=1`，延续的支持为 `0`，约束、混合和无法判断保留为空。审核人应对照此前已经公开的政策判断新增性；同一内容在《建议》和《纲要》重复时，不应再次标为新增。

新兴主题可在 `concept_relations` 中记录“主题→技术/产品/应用”边，在 `company_exposures` 中记录事件前公开的公司业务证据。公司档位为 `direct_business`、`verified_supply`、`planned`、`name_only`；后两者仅供检索。`etf_links` 必须有当时已上市、历史指数成分或基金已披露持仓证据、披露和持仓日期、对应来源，并填写 `matched_company_codes`、`direct_weight` 和 `supply_weight`。每个匹配公司必须在同一条款中有已核验的业务证据。ETF 名称及今日持仓不能证明事件时点的暴露。日期同日但没有可核对的先后时间时，校验拒绝关联。

如果条款信息早于当前全文公开，需要先导入较早的官方来源，再在条款中填写 `first_public_document_id` 和 `first_public_quote`。第一版要求两处引文内容一致；仅语义近似的较早表述暂不能回溯事件日。审核会核对较早来源的原始哈希、正文引文和发布时间，并将早期证据哈希冻结进审批事件，防止把后公开的全文内容放到前一个事件日。

若缺少核验条件，使用 `NO_ETF_IN_LOCAL_DATA`、`NO_LISTED_ETF`、`ETF_EXPOSURE_UNVERIFIED`、`INDEX_ONLY`、`COMPANY_NOT_LISTED_YET` 或 `NO_VERIFIED_LISTED_COMPANY`。只有核对事件当时完整交易所目录后才能使用 `NO_LISTED_ETF`。`VERIFIED` 需要至少一个经审核的 `etf_links`。

## 新兴主题的 ETF 候选

若已有事件前公司公告证据和 ETF 历史持仓快照，可先做关联候选：

```bash
python -m python.policy_news suggest-etfs low_altitude_economy 2025-10-28 \
  --companies /path/company_exposures.csv \
  --holdings /path/etf_historical_holdings.csv \
  --output /path/etf_candidates.csv
```

公司表至少含 `theme_id,company_code,tier,source_url,public_at,reason`；ETF 表至少含 `etf_code,company_code,weight,listed_at,holdings_asof,public_at,source_url,method`。候选只使用事件前已公开的信息，分别汇总直接业务和明确供需权重，不把它们揉成一个分数。结果仍需人工核对来源后写入 `etf_links`；没有候选时不能据此断言市场没有 ETF。

原文、首次公开时间、公司业务和基金持仓的审核，是研究数据的一部分。每一次修订都需要重新 `approve` 和 `export`，研究运行会保存导出文件及哈希。
