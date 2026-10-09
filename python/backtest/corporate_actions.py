"""Record-date entitlements, ex-date receivables, payment cash and share splits."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from python.backtest.models import Portfolio


@dataclass(frozen=True)
class CorporateAction:
    code: str
    kind: Literal["dividend", "split"]
    record_date: pd.Timestamp
    ex_date: pd.Timestamp
    pay_date: pd.Timestamp | None = None
    cash_per_share: float = 0.0
    split_ratio: float = 1.0
    source_url: str = ""

    def __post_init__(self):
        for name in ("record_date", "ex_date", "pay_date"):
            value = getattr(self, name)
            if value is not None:
                parsed = pd.Timestamp(value).normalize()
                if pd.isna(parsed):
                    raise ValueError("corporate action date is missing")
                object.__setattr__(self, name, parsed)
        if not self.code or self.kind not in ("dividend", "split") or self.ex_date <= self.record_date:
            raise ValueError("corporate action requires a code and ex date after record date")
        if self.kind == "dividend" and (self.pay_date is None or self.pay_date < self.ex_date or not np.isfinite(self.cash_per_share) or self.cash_per_share <= 0):
            raise ValueError("dividend requires positive cash and a payment date on/after ex date")
        if self.kind == "split" and (not np.isfinite(self.split_ratio) or self.split_ratio <= 0):
            raise ValueError("split ratio must be positive")


def load_corporate_actions(path: Path) -> list[CorporateAction]:
    frame = pd.read_csv(path).fillna("")
    required = {"code", "kind", "record_date", "ex_date", "pay_date", "cash_per_share", "split_ratio", "source_url"}
    if not required.issubset(frame.columns):
        raise ValueError(f"corporate action table missing: {sorted(required - set(frame.columns))}")
    if frame.duplicated(["code", "kind", "ex_date"]).any() or (frame.source_url == "").any():
        raise ValueError("corporate action table has duplicates or missing sources")
    return [CorporateAction(row.code, row.kind, row.record_date, row.ex_date,
                            row.pay_date or None, float(row.cash_per_share or 0),
                            float(row.split_ratio or 1), row.source_url)
            for row in frame.itertuples(index=False)]


class CorporateActionBook:
    def __init__(self, portfolio: Portfolio, actions: list[CorporateAction]):
        self.portfolio = portfolio
        self.actions = actions
        keys = [(action.code, action.kind, action.ex_date) for action in actions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate corporate action")
        self.recorded: dict[int, set[int]] = {}
        self.split_applied: set[int] = set()
        self.claims: list[dict] = []

    def _log(self, date, action, stage, *, amount=0.0, quantity=0, episode_id="", holding_id=0):
        self.portfolio.corporate_action_ledger.append({
            "date": date.strftime("%Y%m%d"), "code": action.code, "kind": action.kind,
            "action": stage, "record_date": action.record_date.strftime("%Y%m%d"),
            "ex_date": action.ex_date.strftime("%Y%m%d"),
            "pay_date": action.pay_date.strftime("%Y%m%d") if action.pay_date is not None else "",
            "amount": amount, "quantity": quantity, "split_ratio": action.split_ratio,
            "episode_id": episode_id, "holding_id": holding_id, "source_url": action.source_url,
        })

    def on_open(self, date: pd.Timestamp) -> None:
        for index, action in enumerate(self.actions):
            if action.kind != "split" or date < action.ex_date or index in self.split_applied:
                continue
            for position in self.portfolio.positions:
                if position.holding_id not in self.recorded.get(index, set()):
                    continue
                quantity = position.buy_quantity * action.split_ratio
                if abs(quantity - round(quantity)) > 1e-8:
                    raise ValueError("fractional share split requires a cash-in-lieu model")
                self._log(date, action, "split", quantity=position.buy_quantity,
                          episode_id=position.episode_id, holding_id=position.holding_id)
                position.buy_quantity = round(quantity)
                position.buy_exec_price /= action.split_ratio
                position.buy_signal_price /= action.split_ratio
                position.last_close /= action.split_ratio
            self.split_applied.add(index)
        for claim in self.claims:
            action = claim["event"]
            if claim["accrued"] or date < action.ex_date:
                continue
            amount = claim["amount"]
            self.portfolio.dividend_receivable += amount
            self.portfolio.dividend_income_total += amount
            beneficiaries = [position for position in self.portfolio.positions if position.holding_id == claim["holding_id"]]
            beneficiaries += [trade for trade in self.portfolio.closed_trades
                              if trade.holding_id == claim["holding_id"] and pd.Timestamp(trade.sell_date) > action.record_date]
            total_quantity = sum(position.buy_quantity for position in beneficiaries)
            for position in beneficiaries:
                position.dividend_income += amount * position.buy_quantity / total_quantity
                if position.sell_date:
                    position.pnl = position.sell_proceeds + position.dividend_income - position.buy_cost
                    position.pnl_pct = position.pnl / position.buy_cost * 100
            claim["accrued"] = True
            self._log(date, action, "accrued", amount=amount, quantity=claim["quantity"],
                      episode_id=claim["episode_id"], holding_id=claim["holding_id"])

    def on_close(self, date: pd.Timestamp) -> dict[str, float]:
        for index, action in enumerate(self.actions):
            if date != action.record_date or index in self.recorded:
                continue
            positions = [position for position in self.portfolio.positions if position.code == action.code]
            self.recorded[index] = {position.holding_id for position in positions}
            if action.kind == "dividend":
                for position in positions:
                    amount = position.buy_quantity * action.cash_per_share
                    self.claims.append(dict(event=action, amount=amount, quantity=position.buy_quantity,
                                            holding_id=position.holding_id, episode_id=position.episode_id,
                                            accrued=False, paid=False))
                    self._log(date, action, "entitled", amount=amount, quantity=position.buy_quantity,
                              episode_id=position.episode_id, holding_id=position.holding_id)
        payments: dict[str, float] = {}
        for claim in self.claims:
            action = claim["event"]
            if claim["paid"] or not claim["accrued"] or date < action.pay_date:
                continue
            amount = claim["amount"]
            self.portfolio.cash += amount
            self.portfolio.dividend_receivable -= amount
            claim["paid"] = True
            payments[action.code] = payments.get(action.code, 0.0) + amount
            self._log(date, action, "paid", amount=amount, quantity=claim["quantity"],
                      episode_id=claim["episode_id"], holding_id=claim["holding_id"])
        return payments
