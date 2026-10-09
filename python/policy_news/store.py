"""Official URL intake, immutable raw snapshots, review and approved exports."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
import yaml

from .extract import extract_text, normalize_text


STAGES = {"建议", "纲要", "部委文件", "其他官方文件"}
SUPPORT = {"directional", "quantitative", "funding_project", "constraint", "mixed", "unclear"}
CHANGE = {"new", "enhanced", "continued", "weakened", "unknown"}
RELATION = {"direct", "upstream", "downstream", "unknown"}
MAPPING = {"VERIFIED", "NO_ETF_IN_LOCAL_DATA", "NO_LISTED_ETF", "ETF_EXPOSURE_UNVERIFIED",
           "INDEX_ONLY", "COMPANY_NOT_LISTED_YET", "NO_VERIFIED_LISTED_COMPANY"}
DOMAINS = ("gov.cn", "npc.gov.cn")
CHINA = ZoneInfo("Asia/Shanghai")


def _official(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and parsed.username is None and parsed.password is None and parsed.port in (None, 443) and any(
        host == domain or host.endswith("." + domain) for domain in DOMAINS
    )


def _date(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} 必须填写日期或含时区的时间")
    try:
        date = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} 日期无效: {value}") from error
    if len(value) > 10 and date.tzinfo is None:
        raise ValueError(f"{field} 时间必须包含时区")
    return date


def _known_before(evidence: str, event: str, field: str) -> None:
    observed = _date(evidence, field)
    public = _date(event, "first_public_at")
    observed_day = observed.astimezone(CHINA).date() if observed.tzinfo else observed.date()
    public_day = public.astimezone(CHINA).date() if public.tzinfo else public.date()
    if observed_day > public_day:
        raise ValueError(f"{field} 晚于政策事件")
    if observed_day == public_day:
        # A date with no time is only deemed available after the close.
        if len(evidence) == 10 or len(event) == 10:
            raise ValueError(f"{field} 与政策同日但缺少可核对的先后时间")
        if observed.astimezone(timezone.utc) >= public.astimezone(timezone.utc):
            raise ValueError(f"{field} 晚于政策事件")


def _not_before_publication(first_at: str, published_at: str, context: str) -> None:
    first = _date(first_at, "first_public_at")
    published = _date(published_at, "published_at")
    first_day = first.astimezone(CHINA).date() if first.tzinfo else first.date()
    published_day = published.astimezone(CHINA).date() if published.tzinfo else published.date()
    if first_day < published_day:
        raise ValueError(f"{context} 首次公开早于来源发表时间")
    if first_day == published_day and first.tzinfo:
        if published.tzinfo is None:
            raise ValueError(f"{context} 同日精确首发时间缺少来源发布时间核验")
        if first.astimezone(timezone.utc) < published.astimezone(timezone.utc):
            raise ValueError(f"{context} 首次公开早于来源发表时间")


def _extract_snapshot(raw: Path) -> str:
    if raw.suffix == ".pdf":
        return extract_text(raw, "pdf")
    content = raw.read_bytes()
    declared = re.search(rb"charset\s*=\s*['\"]?([A-Za-z0-9_-]+)", content[:4096], re.IGNORECASE)
    if declared:
        encoding = declared.group(1).decode("ascii")
    else:
        try:
            content.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "gb18030"
    return extract_text(raw, "html", encoding)


def _check_body_snapshot(raw: Path, body: str, draft: dict) -> None:
    extracted = _extract_snapshot(raw)
    scanned = raw.suffix == ".pdf" and len(extracted) < 100
    if scanned:
        if draft.get("extraction_status") != "needs_manual_text" or len(normalize_text(body)) < 100:
            raise ValueError("扫描 PDF 需要人工录入可核对正文")
        _required(draft, ("transcription_review_note",), "扫描件人工转录")
    elif draft.get("extraction_status") != "extracted" or normalize_text(body) != extracted:
        raise ValueError("正文文本或抽取状态与原始快照不一致")


def _required(row: dict, names: tuple[str, ...], context: str) -> None:
    missing = [key for key in names if not row.get(key)]
    if missing:
        raise ValueError(f"{context} 缺少字段: {', '.join(missing)}")


def validate_review(review: dict, text: str, raw_sha256: str) -> list[dict]:
    _required(review, ("document_id", "title", "document_stage", "cycle", "source_url", "published_at", "raw_sha256"), "文档")
    if review["raw_sha256"] != raw_sha256:
        raise ValueError("原文哈希与待审稿不一致")
    if not _official(review["source_url"]):
        raise ValueError("文档来源必须是 HTTPS 官方站点")
    if review["document_stage"] not in STAGES:
        raise ValueError("document_stage 无效")
    _date(review["published_at"], "published_at")
    clauses = review.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        raise ValueError("审核至少需要一条正文条款；不能仅凭标题生成事件")
    events = []
    seen = set()
    compact_body = re.sub(r"\s+", "", normalize_text(text))
    for index, row in enumerate(clauses, 1):
        if not isinstance(row, dict):
            raise ValueError(f"条款 {index} 必须是映射")
        _required(row, ("quote", "section", "first_public_at", "first_public_url", "theme_id", "industry_id",
                        "policy_action", "support_type", "change_vs_previous", "relation", "mapping_reason",
                        "review_status", "etf_status"), f"条款 {index}")
        if row["review_status"] != "approved":
            raise ValueError(f"条款 {index} 尚未人工复核")
        if row["support_type"] not in SUPPORT or row["change_vs_previous"] not in CHANGE or row["relation"] not in RELATION:
            raise ValueError(f"条款 {index} 分类枚举无效")
        if row["etf_status"] not in MAPPING:
            raise ValueError(f"条款 {index} ETF 映射状态无效")
        if not _official(row["first_public_url"]):
            raise ValueError(f"条款 {index} 缺少官方首次公开来源")
        first = _date(row["first_public_at"], "first_public_at")
        first_day = first.astimezone(CHINA).date() if first.tzinfo else first.date()
        if first_day > datetime.now(CHINA).date():
            raise ValueError(f"条款 {index} 的首次公开时间在未来")
        if row["first_public_url"] == review["source_url"]:
            _not_before_publication(row["first_public_at"], review["published_at"], f"条款 {index} 同一来源")
        if row["first_public_url"] != review["source_url"]:
            _required(row, ("first_public_document_id", "first_public_quote"), f"条款 {index} 的较早来源")
            if re.sub(r"\s+", "", row["first_public_quote"]) != re.sub(r"\s+", "", row["quote"]):
                raise ValueError(f"条款 {index} 的较早来源引文必须与当前政策信息一致")
        if re.sub(r"\s+", "", row["quote"]) not in compact_body:
            raise ValueError(f"条款 {index} 的原文片段不在快照正文中")
        key = (row["theme_id"], row["first_public_at"], row["quote"])
        if key in seen:
            raise ValueError(f"条款 {index} 重复")
        seen.add(key)
        links = row.get("etf_links", [])
        if not isinstance(links, list):
            raise ValueError(f"条款 {index} etf_links 必须是列表")
        if row["etf_status"] == "VERIFIED" and not links:
            raise ValueError(f"条款 {index} 已验证状态需要 ETF 暴露证据")
        exposures = row.get("company_exposures", [])
        verified_companies = {item.get("company_code"): item.get("tier") for item in exposures
                              if item.get("theme_id") == row["theme_id"] and
                              item.get("tier") in {"direct_business", "verified_supply"}}
        if row["etf_status"] == "VERIFIED" and not verified_companies:
            raise ValueError(f"条款 {index} 缺少已核验的上市公司业务关联")
        for link in links:
            _required(link, ("etf_code", "listed_at", "exposure_source_url", "exposure_public_at",
                             "exposure_asof", "exposure_method", "exposure_reason",
                             "matched_company_codes", "constituents"), "ETF 连接")
            if not re.fullmatch(r"\d{6}\.(SH|SZ)", link["etf_code"]):
                raise ValueError("ETF 代码无效")
            _known_before(link["listed_at"], row["first_public_at"], "listed_at")
            _known_before(link["exposure_public_at"], row["first_public_at"], "exposure_public_at")
            _known_before(link["exposure_asof"], row["first_public_at"], "exposure_asof")
            if not link["exposure_source_url"].startswith("https://"):
                raise ValueError("ETF 暴露缺少 HTTPS 证据")
            if link["exposure_method"] not in {"historical_index_constituents", "disclosed_fund_holdings"}:
                raise ValueError("ETF 暴露须由历史指数成分或已披露持仓核验")
            matched = link["matched_company_codes"]
            if not isinstance(matched, list) or not matched or not set(matched).issubset(verified_companies):
                raise ValueError("ETF 连接缺少已核验公司业务证据")
            direct, supply = float(link.get("direct_weight", -1)), float(link.get("supply_weight", -1))
            if direct < 0 or supply < 0 or direct + supply > 1.001:
                raise ValueError("ETF 直接及供需关联权重无效")
            constituents = link["constituents"]
            if not isinstance(constituents, list) or {item.get("company_code") for item in constituents} != set(matched):
                raise ValueError("ETF 历史成分与匹配公司不一致")
            expected = {"direct_business": 0.0, "verified_supply": 0.0}
            for constituent in constituents:
                weight = float(constituent.get("weight", -1))
                if weight <= 0 or weight > 1:
                    raise ValueError("ETF 历史成分权重无效")
                expected[verified_companies[constituent["company_code"]]] += weight
            if abs(direct - expected["direct_business"]) > 1e-8 or abs(supply - expected["verified_supply"]) > 1e-8:
                raise ValueError("ETF 暴露权重与历史成分不一致")
        if row["etf_status"] != "VERIFIED" and links:
            raise ValueError("未验证 ETF 不得生成正式配对")
        for relation in row.get("concept_relations", []):
            _required(relation, ("from_concept", "to_concept", "relation", "source_url", "public_at"), "主题关联")
            if not relation["source_url"].startswith("https://"):
                raise ValueError("主题关联证据晚于事件或缺少 HTTPS 来源")
            _known_before(relation["public_at"], row["first_public_at"], "public_at")
        for exposure in row.get("company_exposures", []):
            _required(exposure, ("company_code", "theme_id", "tier", "source_url", "public_at", "reason"), "公司关联")
            if exposure["tier"] not in {"direct_business", "verified_supply", "planned", "name_only"}:
                raise ValueError("公司关联档位无效")
            if not re.fullmatch(r"\d{6}\.(SH|SZ)", exposure["company_code"]):
                raise ValueError("上市公司代码无效")
            if not exposure["source_url"].startswith("https://"):
                raise ValueError("公司业务证据晚于事件或缺少 HTTPS 来源")
            _known_before(exposure["public_at"], row["first_public_at"], "public_at")
        is_support = row["support_type"] in {"directional", "quantitative", "funding_project"}
        direction = "support" if is_support else "constraint" if row["support_type"] == "constraint" else row["support_type"]
        new_support = (1 if row["change_vs_previous"] in {"new", "enhanced"} else 0
                       if row["change_vs_previous"] == "continued" else None) if is_support else None
        events.append({"event_id": f"{review['document_id']}:{index:03d}", "document_id": review["document_id"],
                       "document_stage": review["document_stage"], "cycle": review["cycle"],
                       "published_at": review["published_at"], "source_url": review["source_url"],
                       "raw_sha256": raw_sha256, **row, "policy_direction": direction, "new_support": new_support})
    return events


class PolicyStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def document_dir(self, document_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{5,80}", document_id):
            raise ValueError("无效 document_id")
        return self.root / "documents" / document_id

    def status(self, document_id: str) -> str:
        folder = self.document_dir(document_id)
        pointer = folder / "current_approval.txt"
        if not pointer.exists():
            return "draft"
        version = pointer.read_text(encoding="utf-8").strip()
        approved = json.loads((folder / "approved" / f"{version}.json").read_text(encoding="utf-8"))
        draft = yaml.safe_load((folder / "draft.yaml").read_text(encoding="utf-8"))
        body_path = folder / draft["body_file"]
        if (draft["raw_sha256"] != approved["document"]["raw_sha256"] or
                not body_path.is_file() or hashlib.sha256(body_path.read_bytes()).hexdigest() != approved["body_sha256"]):
            return "revision_pending"
        candidates = [path for path in folder.glob("candidate-*.yaml")
                      if path.stem != f"candidate-{draft['raw_sha256'][:16]}"]
        return "candidate_available" if candidates else "approved"

    def import_url(self, url: str) -> dict:
        if not _official(url):
            raise ValueError("仅支持 HTTPS 官方政策来源（*.gov.cn）")
        fetch_url = url
        for _ in range(6):
            response = requests.get(fetch_url, timeout=30, headers={"User-Agent": "TradePilot-policy-research/1.0"},
                                    stream=True, allow_redirects=False)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            target = urljoin(fetch_url, response.headers.get("Location", ""))
            response.close()
            if not _official(target):
                raise ValueError("跳转目标不是官方 HTTPS 站点")
            fetch_url = target
        else:
            raise ValueError("官方页面跳转次数过多")
        response.raise_for_status()
        if not _official(response.url):
            raise ValueError("跳转目标不是官方 HTTPS 站点")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > 20_000_000:
                raise ValueError("文件超过 20 MB")
            chunks.append(chunk)
        content = b"".join(chunks)
        kind = "pdf" if content.startswith(b"%PDF-") else "html"
        if kind == "html" and b"<html" not in content[:4096].lower() and b"<!doctype html" not in content[:4096].lower():
            raise ValueError("仅支持 HTML 页面或文本 PDF")
        sha = hashlib.sha256(content).hexdigest()
        doc_id = "policy_" + hashlib.sha256(url.encode()).hexdigest()[:16]
        folder = self.document_dir(doc_id)
        raw = folder / "raw" / f"{sha}.{kind}"
        raw.parent.mkdir(parents=True, exist_ok=True)
        if not raw.exists():
            raw.write_bytes(content)
        response.close()
        extracted = _extract_snapshot(raw)
        extraction_status = "needs_manual_text" if kind == "pdf" and len(extracted) < 100 else "extracted"
        body = folder / f"{sha}.txt"
        if not body.exists():
            body.write_text(extracted + "\n", encoding="utf-8")
        current = folder / "draft.yaml"
        draft_path = current
        if current.exists():
            existing = yaml.safe_load(current.read_text(encoding="utf-8"))
            if existing.get("raw_sha256") != sha:
                draft_path = folder / f"candidate-{sha[:16]}.yaml"
        if not draft_path.exists():
            draft = {"document_id": doc_id, "title": "", "cycle": "", "document_stage": "",
                     "source_url": url, "fetched_url": response.url, "fetched_at": datetime.now(timezone.utc).isoformat(),
                     "published_at": "", "raw_sha256": sha, "raw_file": str(raw.relative_to(folder)),
                     "body_file": body.name, "extraction_status": extraction_status,
                     "clauses": []}
            draft_path.write_text(yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {"document_id": doc_id, "raw_sha256": sha, "draft": str(draft_path), "body": str(body),
                "candidate_revision": draft_path != current,
                "extraction_status": extraction_status}

    def adopt_candidate(self, document_id: str, sha_prefix: str) -> Path:
        folder = self.document_dir(document_id)
        if not re.fullmatch(r"[a-f0-9]{16}", sha_prefix):
            raise ValueError("候选版本需要 16 位哈希前缀")
        candidate = folder / f"candidate-{sha_prefix}.yaml"
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        current = folder / "draft.yaml"
        if current.exists():
            old = yaml.safe_load(current.read_text(encoding="utf-8"))
            backup = folder / f"draft-{old['raw_sha256'][:16]}.yaml"
            if not backup.exists():
                backup.write_bytes(current.read_bytes())
        current.write_bytes(candidate.read_bytes())
        return current

    def approve(self, document_id: str) -> Path:
        draft, body, events = self.validate(document_id)
        folder = self.document_dir(document_id)
        approved = {"document": {key: draft[key] for key in ("document_id", "title", "cycle", "document_stage",
                                                                 "source_url", "fetched_url", "fetched_at", "published_at", "raw_sha256")},
                    "body_sha256": hashlib.sha256(body.encode()).hexdigest(), "events": events, "schema_version": 1}
        approved["document"]["extraction_status"] = draft["extraction_status"]
        if draft["extraction_status"] == "needs_manual_text":
            approved["document"]["transcription_review_note"] = draft["transcription_review_note"]
        stable = json.dumps(approved, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        version = hashlib.sha256(stable.encode()).hexdigest()[:16]
        target = folder / "approved" / f"{version}.json"
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            approved["approved_at"] = datetime.now(timezone.utc).isoformat()
            target.write_text(json.dumps(approved, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (folder / "current_approval.txt").write_text(version + "\n", encoding="utf-8")
        return target

    def validate(self, document_id: str) -> tuple[dict, str, list[dict]]:
        folder = self.document_dir(document_id)
        draft = yaml.safe_load((folder / "draft.yaml").read_text(encoding="utf-8"))
        if draft.get("document_id") != document_id:
            raise ValueError("待审稿 ID 不一致")
        raw = folder / draft["raw_file"]
        if not raw.is_file() or hashlib.sha256(raw.read_bytes()).hexdigest() != draft["raw_sha256"]:
            raise ValueError("原始快照不存在或已被改动")
        body = (folder / draft["body_file"]).read_text(encoding="utf-8")
        _check_body_snapshot(raw, body, draft)
        events = validate_review(draft, body, draft["raw_sha256"])
        for event in events:
            if event["first_public_url"] == draft["source_url"]:
                continue
            earlier = self.document_dir(event["first_public_document_id"])
            prior = yaml.safe_load((earlier / "draft.yaml").read_text(encoding="utf-8"))
            if prior.get("source_url") != event["first_public_url"]:
                raise ValueError("较早公开来源 URL 与归档文档不一致")
            prior_raw = earlier / prior["raw_file"]
            if hashlib.sha256(prior_raw.read_bytes()).hexdigest() != prior["raw_sha256"]:
                raise ValueError("较早来源原始快照缺失或已被改动")
            prior_body = (earlier / prior["body_file"]).read_text(encoding="utf-8")
            if re.sub(r"\s+", "", event["first_public_quote"]) not in re.sub(r"\s+", "", prior_body):
                raise ValueError("较早来源引文不在归档正文中")
            _not_before_publication(event["first_public_at"], prior["published_at"], "较早来源")
            _check_body_snapshot(prior_raw, prior_body, prior)
            event["first_public_evidence"] = {
                "document_id": prior["document_id"], "source_url": prior["source_url"],
                "raw_file": prior["raw_file"], "raw_sha256": prior["raw_sha256"],
                "body_file": prior["body_file"], "body_sha256": hashlib.sha256(prior_body.encode()).hexdigest(),
                "published_at": prior["published_at"], "quote": event["first_public_quote"],
                "extraction_status": prior["extraction_status"],
            }
            if prior["extraction_status"] == "needs_manual_text":
                event["first_public_evidence"]["transcription_review_note"] = prior["transcription_review_note"]
        return draft, body, events

    def export(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        rows = []
        sources = []
        for pointer in sorted((self.root / "documents").glob("*/current_approval.txt")):
            version = pointer.read_text(encoding="utf-8").strip()
            approval = json.loads((pointer.parent / "approved" / f"{version}.json").read_text(encoding="utf-8"))
            rows.extend({**event, "approval_version": version} for event in approval["events"])
            sources.append({**approval["document"], "body_sha256": approval["body_sha256"],
                            "approval_version": version, "approved_at": approval["approved_at"]})
        target = self.root / "approved_events.jsonl"
        target.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        import csv
        with (self.root / "timeline.csv").open("w", encoding="utf-8-sig", newline="") as file:
            columns = ("event_id", "document_id", "document_stage", "published_at", "first_public_at", "first_public_url",
                       "theme_id", "industry_id", "support_type", "change_vs_previous", "etf_status", "approval_version")
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(sorted(rows, key=lambda row: (row["first_public_at"], row["event_id"])))
        with (self.root / "sources.csv").open("w", encoding="utf-8-sig", newline="") as file:
            columns = ("document_id", "title", "cycle", "document_stage", "source_url", "fetched_url", "fetched_at",
                       "published_at", "raw_sha256", "body_sha256", "approval_version", "approved_at")
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(sources)
        with (self.root / "source_inventory.csv").open("w", encoding="utf-8-sig", newline="") as file:
            columns = ("document_id", "title", "cycle", "document_stage", "source_url", "published_at",
                       "raw_sha256", "extraction_status", "review_status")
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for draft_path in sorted((self.root / "documents").glob("*/draft.yaml")):
                draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
                writer.writerow({**draft, "review_status": self.status(draft_path.parent.name)})
        return target
