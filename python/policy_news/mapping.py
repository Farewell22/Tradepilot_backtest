"""As-of ETF exposure candidates from reviewed company facts and past holdings.

This is a retrieval aid. A reviewer must inspect underlying disclosures before
copying a candidate into a policy clause's approved ``etf_links``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd


COMPANY_COLUMNS = {"theme_id", "company_code", "tier", "source_url", "public_at", "reason"}
HOLDING_COLUMNS = {"etf_code", "company_code", "weight", "listed_at", "holdings_asof",
                   "public_at", "source_url", "method"}
CHINA = ZoneInfo("Asia/Shanghai")


def _before(value: str, event_at: str) -> bool:
    observed, event = datetime.fromisoformat(value), datetime.fromisoformat(event_at)
    observed_day = observed.astimezone(CHINA).date() if observed.tzinfo else observed.date()
    event_day = event.astimezone(CHINA).date() if event.tzinfo else event.date()
    if observed_day < event_day:
        return True
    if observed_day > event_day or len(value) == 10 or len(event_at) == 10:
        return False
    if observed.tzinfo is None or event.tzinfo is None:
        raise ValueError("同日证据需要带时区的发布时间")
    return observed.astimezone(timezone.utc) < event.astimezone(timezone.utc)


def suggest_etfs(theme_id: str, event_at: str, companies: pd.DataFrame,
                 holdings: pd.DataFrame) -> pd.DataFrame:
    """Return direct and verified supply weights separately, without a score."""
    if not COMPANY_COLUMNS.issubset(companies) or not HOLDING_COLUMNS.issubset(holdings):
        raise ValueError("公司证据或 ETF 历史持仓缺少必要列")
    company = companies.loc[companies.theme_id.eq(theme_id)].copy()
    company = company.loc[company.public_at.map(lambda value: _before(str(value), event_at))]
    company = company.loc[company.tier.isin(["direct_business", "verified_supply"])]
    if company.source_url.eq("").any() or not company.source_url.str.startswith("https://").all():
        raise ValueError("公司证据缺少 HTTPS 来源")
    if company.duplicated("company_code").any():
        raise ValueError("同一主题公司的证据重复，先人工确认关系档位")
    fund = holdings.copy()
    for field in ("listed_at", "holdings_asof", "public_at"):
        fund = fund.loc[fund[field].map(lambda value: _before(str(value), event_at))]
    fund = fund.loc[fund.method.isin(["historical_index_constituents", "disclosed_fund_holdings"])]
    fund["weight"] = pd.to_numeric(fund.weight, errors="raise")
    if (fund.weight.lt(0) | fund.weight.gt(1)).any() or not fund.source_url.str.startswith("https://").all():
        raise ValueError("ETF 历史权重或来源无效")
    if company.empty or fund.empty:
        return pd.DataFrame(columns=["theme_id", "etf_code", "direct_weight", "supply_weight", "matched_companies"])
    # Use the last publicly available full ETF snapshot, not a union of old snapshots.
    fund["_public_utc"] = pd.to_datetime(fund.public_at, utc=True)
    latest = fund.groupby("etf_code")["_public_utc"].transform("max")
    fund = fund.loc[fund._public_utc.eq(latest)]
    if fund.groupby("etf_code").holdings_asof.nunique().gt(1).any():
        raise ValueError("同一 ETF 披露批次混入不同持仓时点")
    if fund.duplicated(["etf_code", "company_code"]).any() or fund.groupby("etf_code").weight.sum().gt(1.001).any():
        raise ValueError("ETF 历史持仓重复或权重合计超过 100%")
    merged = fund.merge(company[["company_code", "tier"]], on="company_code", how="inner", validate="many_to_one")
    result = []
    for code, group in merged.groupby("etf_code"):
        result.append({"theme_id": theme_id, "etf_code": code,
                       "direct_weight": float(group.loc[group.tier.eq("direct_business"), "weight"].sum()),
                       "supply_weight": float(group.loc[group.tier.eq("verified_supply"), "weight"].sum()),
                       "matched_companies": ",".join(sorted(group.company_code.unique()))})
    return pd.DataFrame(result).sort_values("etf_code").reset_index(drop=True) if result else pd.DataFrame(
        columns=["theme_id", "etf_code", "direct_weight", "supply_weight", "matched_companies"])
