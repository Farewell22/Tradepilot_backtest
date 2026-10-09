"""Small known-answer examples for policy intake and event returns."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from python.policy_news.store import PolicyStore, validate_review
from python.policy_news.mapping import suggest_etfs
from python.research.policy.industry_etf_policy_support.study import ACTION_COLUMNS, daily_prices, event_window, load_action_book, load_events, run_research


def reviewed() -> dict:
    url = "https://www.gov.cn/zhengce/example.html"
    return {"document_id": "policy_example", "title": "政策正文", "cycle": "十五五", "document_stage": "建议",
            "source_url": url, "published_at": "2025-10-28", "raw_sha256": "abc",
            "clauses": [{"quote": "支持低空经济发展。", "section": "产业", "first_public_at": "2025-10-28",
                         "first_public_url": url, "theme_id": "low_altitude", "industry_id": "new_low_altitude",
                         "policy_action": "支持发展", "support_type": "directional", "change_vs_previous": "unknown",
                         "relation": "direct", "mapping_reason": "正文直接提及", "review_status": "approved",
                         "etf_status": "ETF_EXPOSURE_UNVERIFIED", "etf_links": []}]}


def test_review_requires_exact_body_quote_and_official_source():
    review = reviewed()
    assert validate_review(review, "产业\n支持低空经济发展。", "abc")[0]["theme_id"] == "low_altitude"
    with pytest.raises(ValueError, match="原文片段"):
        validate_review(review, "支持其他产业发展。", "abc")
    review["source_url"] = "https://other.example.org/story"
    with pytest.raises(ValueError, match="官方"):
        validate_review(review, "支持低空经济发展。", "abc")


def test_earlier_public_claim_requires_archived_earlier_quote():
    review = reviewed()
    review["published_at"] = "2025-11-01"
    with pytest.raises(ValueError, match="首次公开早于来源发表时间"):
        validate_review(review, "支持低空经济发展。", "abc")
    review["clauses"][0]["first_public_url"] = "https://www.gov.cn/zhengce/earlier.html"
    with pytest.raises(ValueError, match="较早来源"):
        validate_review(review, "支持低空经济发展。", "abc")
    review["clauses"][0].update(first_public_document_id="policy_earlier", first_public_quote="支持完全不同的政策。")
    with pytest.raises(ValueError, match="必须与当前政策信息一致"):
        validate_review(review, "支持低空经济发展。", "abc")


def test_same_day_publication_time_cannot_move_event_before_source():
    review = reviewed()
    review["published_at"] = "2025-10-28T15:00:00+08:00"
    review["clauses"][0]["first_public_at"] = "2025-10-28T09:00:00+08:00"
    with pytest.raises(ValueError, match="首次公开早于来源发表时间"):
        validate_review(review, "支持低空经济发展。", "abc")
    review["published_at"] = "2025-10-28"
    with pytest.raises(ValueError, match="缺少来源发布时间核验"):
        validate_review(review, "支持低空经济发展。", "abc")


def test_review_blocks_future_etf_exposure_and_name_only_mapping():
    review = reviewed()
    clause = review["clauses"][0]
    clause["etf_status"] = "VERIFIED"
    clause["company_exposures"] = [{"company_code": "688981.SH", "theme_id": "low_altitude",
                                    "tier": "direct_business", "source_url": "https://issuer/example",
                                    "public_at": "2025-10-27", "reason": "事件前产品披露"}]
    clause["etf_links"] = [{"etf_code": "512760.SH", "listed_at": "2019-06-12",
                            "exposure_source_url": "https://www.sse.com.cn/example",
                            "exposure_public_at": "2025-10-29", "exposure_asof": "2025-10-28",
                            "exposure_method": "disclosed_fund_holdings", "exposure_reason": "历史持仓",
                            "matched_company_codes": ["688981.SH"],
                            "constituents": [{"company_code": "688981.SH", "weight": .1}],
                            "direct_weight": .1, "supply_weight": 0}]
    with pytest.raises(ValueError, match="晚于政策事件"):
        validate_review(review, "支持低空经济发展。", "abc")
    clause["etf_links"][0]["exposure_public_at"] = "2025-10-27"
    clause["etf_links"][0]["exposure_asof"] = "2025-10-27"
    clause["etf_links"][0]["exposure_method"] = "etf_name"
    with pytest.raises(ValueError, match="历史指数成分"):
        validate_review(review, "支持低空经济发展。", "abc")
    clause["etf_links"][0]["exposure_method"] = "disclosed_fund_holdings"
    clause["company_exposures"][0]["theme_id"] = "another_theme"
    with pytest.raises(ValueError, match="缺少已核验的上市公司"):
        validate_review(review, "支持低空经济发展。", "abc")
    clause["company_exposures"][0]["theme_id"] = "low_altitude"
    clause["etf_links"][0]["direct_weight"] = .2
    with pytest.raises(ValueError, match="权重与历史成分不一致"):
        validate_review(review, "支持低空经济发展。", "abc")


def test_approval_is_immutable_and_export_only_approved(tmp_path):
    store = PolicyStore(tmp_path)
    review = reviewed()
    folder = store.document_dir(review["document_id"])
    (folder / "raw").mkdir(parents=True)
    raw = "<html><body>支持低空经济发展。</body></html>".encode()
    digest = hashlib.sha256(raw).hexdigest()
    (folder / "raw" / f"{digest}.html").write_bytes(raw)
    (folder / f"{digest}.txt").write_text("支持低空经济发展。", encoding="utf-8")
    review.update(raw_sha256=digest, raw_file=f"raw/{digest}.html", body_file=f"{digest}.txt", extraction_status="extracted",
                  fetched_url=review["source_url"], fetched_at="2025-10-28T00:00:00+00:00")
    (folder / "draft.yaml").write_text(yaml.safe_dump(review, allow_unicode=True), encoding="utf-8")
    assert store.export().read_text(encoding="utf-8") == ""
    first = store.approve(review["document_id"])
    assert store.approve(review["document_id"]) == first
    exported = store.export()
    assert json.loads(exported.read_text(encoding="utf-8"))["approval_version"] == first.stem
    assert len(load_events(exported)) == 1
    assert (tmp_path / "timeline.csv").exists()
    exported.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="完整集合"):
        load_events(exported)
    exported = store.export()
    (folder / f"{digest}.txt").write_text("伪造政策文本。", encoding="utf-8")
    with pytest.raises(ValueError, match="正文文本或抽取状态与原始快照"):
        store.approve(review["document_id"])
    with pytest.raises(ValueError, match="正文快照与审批记录不一致"):
        load_events(exported)
    draft = yaml.safe_load((folder / "draft.yaml").read_text(encoding="utf-8"))
    draft["extraction_status"] = "needs_manual_text"
    draft["transcription_review_note"] = "伪称扫描件"
    (folder / "draft.yaml").write_text(yaml.safe_dump(draft, allow_unicode=True), encoding="utf-8")
    (folder / f"{digest}.txt").write_text("伪造政策文本。" * 30, encoding="utf-8")
    with pytest.raises(ValueError, match="正文文本或抽取状态与原始快照"):
        store.approve(review["document_id"])


def test_earlier_source_hash_is_frozen_in_approved_event(tmp_path):
    store = PolicyStore(tmp_path)
    quote = "支持低空经济发展。"
    raw = f"<html><body>{quote}</body></html>".encode()
    digest = hashlib.sha256(raw).hexdigest()
    earlier_url = "https://www.gov.cn/zhengce/earlier.html"
    later_url = "https://www.gov.cn/zhengce/later.html"
    for ident, url, published in (("policy_prior", earlier_url, "2025-10-27"),
                                  ("policy_example", later_url, "2025-10-28")):
        folder = store.document_dir(ident)
        (folder / "raw").mkdir(parents=True)
        (folder / "raw" / f"{digest}.html").write_bytes(raw)
        (folder / f"{digest}.txt").write_text(quote, encoding="utf-8")
        draft = reviewed() if ident == "policy_example" else {"clauses": []}
        draft.update(document_id=ident, title="政策正文", cycle="十五五", document_stage="建议",
                     source_url=url, fetched_url=url, fetched_at="2025-10-28T00:00:00+00:00",
                     published_at=published, raw_sha256=digest, raw_file=f"raw/{digest}.html",
                     body_file=f"{digest}.txt", extraction_status="extracted")
        if ident == "policy_example":
            draft["clauses"][0].update(first_public_url=earlier_url, first_public_at="2025-10-27",
                                       first_public_document_id="policy_prior", first_public_quote=quote)
        (folder / "draft.yaml").write_text(yaml.safe_dump(draft, allow_unicode=True), encoding="utf-8")
    store.approve("policy_example")
    exported = store.export()
    assert load_events(exported)[0]["first_public_evidence"]["raw_sha256"] == digest
    (store.document_dir("policy_prior") / f"{digest}.txt").write_text("篡改", encoding="utf-8")
    with pytest.raises(ValueError, match="较早政策来源与审批时快照不一致"):
        load_events(exported)


def test_import_preserves_utf8_chinese_and_never_auto_approves(tmp_path, monkeypatch):
    from python.policy_news import store as module

    class Response:
        url = "https://www.gov.cn/zhengce/example.html"
        status_code = 200
        headers = {}
        encoding = "ISO-8859-1"

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield '<html><meta charset="UTF-8"><body>支持低空经济发展。</body></html>'.encode()

        def close(self):
            pass

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    store = PolicyStore(tmp_path)
    imported = store.import_url(Response.url)
    assert "支持低空经济发展" in Path(imported["body"]).read_text(encoding="utf-8")
    assert imported["extraction_status"] == "extracted"
    assert not (tmp_path / "approved_events.jsonl").exists()


def test_scanned_pdf_stays_in_manual_text_queue(tmp_path, monkeypatch):
    from python.policy_news import store as module

    class Response:
        url = "https://www.gov.cn/policy.pdf"
        status_code = 200
        headers = {}
        encoding = None

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"%PDF-scanned-fixture"

        def close(self):
            pass

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(module, "extract_text", lambda *args, **kwargs: "")
    imported = PolicyStore(tmp_path).import_url(Response.url)
    assert imported["extraction_status"] == "needs_manual_text"
    with pytest.raises(ValueError, match="人工录入"):
        PolicyStore(tmp_path).approve(imported["document_id"])


def prices(dates, opens, closes):
    return pd.DataFrame({"date": pd.to_datetime(dates), "open": opens, "close": closes,
                         "volume": [100] * len(dates)})


def test_date_only_event_enters_next_open_and_counts_entry_as_day_one():
    dates = ["2025-10-28", "2025-10-29", "2025-10-30"]
    etf = prices(dates, [8, 10, 11], [8, 11, 10])
    benchmark = prices(dates, [10] * 3, [10] * 3)
    actions = pd.DataFrame([{"code": "512760.SH", "kind": "dividend", "record_date": dates[1],
                             "ex_date": dates[2], "pay_date": dates[2], "price_effective_date": dates[2],
                             "cash_per_share": 1, "share_ratio": 1,
                             "source_url": "https://www.sse.com.cn/action"}], columns=ACTION_COLUMNS)
    audit = {"funds": {code: {"status": "verified", "source_url": "https://www.sse.com.cn/audit",
                              "coverage_start": dates[0], "coverage_end": dates[-1]}
                       for code in ("512760.SH", "510300.SH")}}
    event = {"event_id": "e1", "document_id": "d1", "first_public_at": dates[0],
             "theme_id": "chip", "industry_id": "chip", "support_type": "directional",
             "change_vs_previous": "new"}
    one = event_window(event, "512760.SH", etf, benchmark, actions, audit, 1)
    two = event_window(event, "512760.SH", etf, benchmark, actions, audit, 2)
    assert one["entry_date"] == dates[1] and one["exit_date"] == dates[1]
    assert one["etf_return"] == pytest.approx(.1)
    assert two["exit_date"] == dates[2] and two["etf_return"] == pytest.approx(.1)
    assert two["excess_return"] == pytest.approx(.1)
    assert event_window(event, "512760.SH", etf, benchmark, actions, audit, 20)["missing_reason"] == "WINDOW_NOT_MATURE"
    audit["funds"].pop("512760.SH")
    assert event_window(event, "512760.SH", etf, benchmark, actions, audit, 1)["missing_reason"].startswith("CORPORATE_ACTION_AUDIT_MISSING")


def test_utc_timestamp_is_converted_to_beijing_before_entry():
    dates = ["2025-10-28", "2025-10-29"]
    etf = prices(dates, [10, 20], [10, 20])
    audit = {"funds": {code: {"status": "verified", "source_url": "https://www.sse.com.cn/audit",
                              "coverage_start": dates[0], "coverage_end": dates[-1]}
                       for code in ("512760.SH", "510300.SH")}}
    event = {"event_id": "e1", "document_id": "d1", "first_public_at": "2025-10-28T04:00:00+00:00",
             "theme_id": "chip", "industry_id": "chip", "support_type": "directional",
             "change_vs_previous": "new"}
    result = event_window(event, "512760.SH", etf, etf, pd.DataFrame(columns=ACTION_COLUMNS), audit, 1)
    assert result["entry_date"] == dates[1]


def test_incomplete_intraday_session_is_reported_not_used(tmp_path):
    path = tmp_path / "etf.csv"
    pd.DataFrame([{"时间": f"2025-10-29 {slot}", "开盘价": 10, "收盘价": 11, "成交量": 100}
                  for slot in ("10:30:00", "11:30:00", "15:00:00")]).to_csv(path, index=False)
    result = daily_prices(path)
    assert not result.iloc[0].bars_complete


def test_action_audit_rejects_invalid_dividend_dates(tmp_path):
    actions = tmp_path / "actions.csv"
    pd.DataFrame([{"code": "512760.SH", "kind": "dividend", "record_date": "2025-10-30",
                   "ex_date": "2025-10-29", "pay_date": "2025-10-31", "price_effective_date": "2025-10-29",
                   "cash_per_share": .1, "share_ratio": 1, "source_url": "https://www.sse.com.cn/action"}],
                 columns=ACTION_COLUMNS).to_csv(actions, index=False)
    audit = tmp_path / "audit.json"
    audit.write_text('{"funds": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="日期"):
        load_action_book(actions, audit)


def test_unmapped_event_runs_and_reports_no_fabricated_return(tmp_path):
    event = validate_review(reviewed(), "支持低空经济发展。", "abc")[0]
    event["approval_version"] = "v1"
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
    actions = tmp_path / "actions.csv"
    pd.DataFrame(columns=ACTION_COLUMNS).to_csv(actions, index=False)
    audit = tmp_path / "audit.json"
    audit.write_text('{"funds": {}}', encoding="utf-8")
    result = run_research(events, tmp_path, actions, audit, tmp_path / "out",
                          start_date="20251028", end_date="20251028")
    assert pd.read_csv(result / "unmapped_policy_themes.csv").iloc[0].etf_status == "ETF_EXPOSURE_UNVERIFIED"
    assert pd.read_csv(result / "observations.csv").empty
    assert "暂无可计算的收益观测" in (result / "report.md").read_text(encoding="utf-8")


def test_constraint_new_is_not_new_support_control(tmp_path):
    dates = pd.bdate_range("2025-01-01", periods=23)
    etf_dir = tmp_path / "etfs"
    etf_dir.mkdir()
    for code in ("510300.SH", "512760.SH", "512761.SH"):
        frame = pd.DataFrame([{"时间": f"{day.date()} {slot}", "开盘价": 10, "收盘价": 10,
                               "成交量": 100} for day in dates
                              for slot in ("10:30:00", "11:30:00", "14:00:00", "15:00:00")])
        frame.to_csv(etf_dir / f"{code}.csv", index=False)
    events = []
    for code, support, change, direction in (("512760.SH", 0, "continued", "support"),
                                             ("512761.SH", None, "new", "constraint")):
        events.append({"event_id": code, "document_id": "d1", "document_stage": "建议", "cycle": "十五五",
                       "published_at": "2025-01-02", "source_url": "https://www.gov.cn/example",
                       "raw_sha256": "abc", "first_public_at": "2025-01-02", "first_public_url": "https://www.gov.cn/example",
                       "theme_id": code, "industry_id": code, "support_type": "directional" if support == 0 else "constraint",
                       "policy_direction": direction, "change_vs_previous": change, "new_support": support,
                       "review_status": "approved", "approval_version": "v1", "etf_status": "VERIFIED",
                       "etf_links": [{"etf_code": code}]})
    event_path = tmp_path / "events.jsonl"
    event_path.write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")
    actions = tmp_path / "actions.csv"
    pd.DataFrame(columns=ACTION_COLUMNS).to_csv(actions, index=False)
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"funds": {code: {"status": "verified", "source_url": "https://www.sse.com.cn/audit",
                                                     "coverage_start": "2025-01-01", "coverage_end": "2025-02-28"}
                                            for code in ("510300.SH", "512760.SH", "512761.SH")}}), encoding="utf-8")
    out = run_research(event_path, etf_dir, actions, audit, tmp_path / "out",
                       start_date="20250102", end_date="20250102")
    assert pd.read_csv(out / "same_day_controls.csv").empty
    assert (out / "event_excess.png").is_file()
    summary = pd.read_csv(out / "summary.csv")
    assert "constraint" in summary.policy_direction.to_list()
    assert summary.loc[summary.policy_direction.eq("constraint"), "new_support"].isna().all()


def test_emerging_theme_candidate_uses_only_past_verified_links():
    companies = pd.DataFrame([
        {"theme_id": "new_theme", "company_code": "A", "tier": "direct_business", "source_url": "https://issuer/a",
         "public_at": "2025-10-27", "reason": "已有产品"},
        {"theme_id": "new_theme", "company_code": "B", "tier": "verified_supply", "source_url": "https://issuer/b",
         "public_at": "2025-10-27", "reason": "已有订单"},
        {"theme_id": "new_theme", "company_code": "C", "tier": "direct_business", "source_url": "https://issuer/c",
         "public_at": "2025-10-29", "reason": "后来发布"},
    ])
    holdings = pd.DataFrame([
        {"etf_code": "512760.SH", "company_code": code, "weight": weight, "listed_at": "2019-06-12",
         "holdings_asof": "2025-09-30", "public_at": "2025-10-27", "source_url": "https://fund/holdings",
         "method": "disclosed_fund_holdings"} for code, weight in (("A", .2), ("B", .1), ("C", .3))
    ])
    result = suggest_etfs("new_theme", "2025-10-28", companies, holdings)
    assert result.iloc[0].direct_weight == pytest.approx(.2)
    assert result.iloc[0].supply_weight == pytest.approx(.1)
    holdings.loc[0, "public_at"] = "2025-10-29"
    assert suggest_etfs("new_theme", "2025-10-28", companies, holdings).iloc[0].direct_weight == 0
