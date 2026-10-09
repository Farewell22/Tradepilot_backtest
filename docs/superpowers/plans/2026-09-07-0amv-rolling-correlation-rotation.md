# 0AMV Rolling Correlation Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a MA10 class-2/class-3 ETF rotation backtest that selects the highest positive point-in-time 30-session Pearson-correlated ETF after dynamic theme de-duplication.

**Architecture:** Add one research module for data loading, 30-day aligned-return ranking, theme de-duplication, signal scheduling, and artifacts. Reuse existing MA10 signal generators and the single-position rotation simulator so entry and risk rules do not change.

**Tech Stack:** Python 3.12, pandas, pytest, existing 60-minute ETF CSV data.

**Spec:** `/home/wang/workspace/factor-research/0AMV相关研究/0AMV滚动相关性研究.md`

## Global Constraints

- Use data through signal-day close only; execute next session open.
- Use exactly 30 aligned returns for Pearson30 and Spearman30.
- Deduplicate by normalized theme at each signal date, retaining the ETF with greatest prior-30-session mean amount.
- Choose only positive Pearson30; otherwise fall back to `510300.SH`.
- Preserve class-2/class-3 entries and current trend, low-momentum, 5% stop, and 7% trail exits.
- Generate TRAIN (2015--2023) and OOS (2024--2025) artifacts without frontend changes.

---

### Task 1: Point-in-time correlation selector

**Files:**

- Create: `python/backtest/research_0amv_rolling_correlation_rotation.py`
- Create: `python/tests/backtest/test_0amv_rolling_correlation_rotation.py`

**Interfaces:**

- `normalize_theme_name(name: str) -> str`
- `candidate_rolling_correlations(signal_date, amv_daily, candidate_daily) -> pd.DataFrame`
- `choose_correlation_candidate(candidates: pd.DataFrame) -> pd.Series | None`

- [ ] Write fixtures with an exactly positive-correlated ETF, a negative ETF, and two same-theme ETFs with different historical amounts.
- [ ] Write a failing test proving the selector uses 30 returns ending at signal day, returns the positive ETF, and calculates Pearson30 near 1.0.
- [ ] Write a failing test proving dynamic theme de-duplication retains only the highest prior mean-amount ETF, with code as the deterministic tie-breaker.
- [ ] Write a failing test proving no positive candidate returns `None`.
- [ ] Run `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/backtest/test_0amv_rolling_correlation_rotation.py -q`; expect import failure.
- [ ] Implement only the three interfaces: normalize provider suffixes from ETF names; align returns by date through signal date; require 30 observations; calculate Pearson/Spearman and prior mean amount; deduplicate by theme; rank positive Pearson descending then code ascending.
- [ ] Re-run the focused test file; expect PASS.
- [ ] Commit Task 1 with message `feat: add rolling correlation ETF selector`.

### Task 2: MA10 scheduling and rotation integration

**Files:**

- Modify: `python/backtest/research_0amv_rolling_correlation_rotation.py`
- Modify: `python/tests/backtest/test_0amv_rolling_correlation_rotation.py`

**Interfaces:**

- `build_selection_schedule(...) -> tuple[dict[pd.Timestamp, dict], pd.DataFrame]`
- `run_research(amv_path: Path, etf_dir: Path, reference_path: Path, output_dir: Path) -> pd.DataFrame`

- [ ] Write a failing schedule test with two MA10 signals: one selects the positive candidate at next session and one records fallback `510300.SH` when all values are non-positive.
- [ ] Assert each selection record contains `code`, `name`, `theme`, `pearson30`, `spearman30`, `observation_count`, `mean_amount30`, `candidate_count`, and `is_fallback`.
- [ ] Run the specific schedule test; expect missing-function failure.
- [ ] Load all readable ETF files once into daily/intraday maps. Restrict 0AMV entries to class_2 and class_3. Schedule at the next reference ETF session, add `510300.SH` maps for fallback, and pass existing trend/low-momentum schedules to `run_rotation_backtest` with default 5% stop and 7% trail.
- [ ] Write `selections.csv`, per-stage NAV/trades/annual files, and `summary.csv` from `run_research`.
- [ ] Run `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/backtest/test_0amv_rolling_correlation_rotation.py python/tests/backtest/test_rs20_etf_rotation.py python/tests/backtest/test_amount_ratio_etf_rotation.py -q`; expect PASS.
- [ ] Commit Task 2 with message `feat: backtest rolling correlation ETF rotation`.

### Task 3: Full-data run and research evidence

**Files:**

- Create: `data/backtest_runs/etf_rolling_correlation_rotation_0amv/` (ignored artifacts)
- Modify: `/home/wang/workspace/factor-research/0AMV相关研究/0AMV滚动相关性研究.md`

**Interfaces:**

- Consumes Task 2 `run_research` and baseline `etf_510300_ma10_above_ma30_gap_signal/summary.csv`.
- Produces selection, NAV, trade, annual, and summary CSV files plus research conclusions.

- [ ] Run the module with the 0AMV CSV, all ETF CSV directory, `510300.SH` reference data, and output directory `data/backtest_runs/etf_rolling_correlation_rotation_0amv`.
- [ ] Verify the output contains `summary.csv`, `selections.csv`, `nav_train.csv`, `nav_oos.csv`, `trades_train.csv`, `trades_oos.csv`, `annual_train.csv`, and `annual_oos.csv`.
- [ ] Append coverage, selected-theme concentration, fallback counts, TRAIN/OOS metrics, 510300 baseline comparison, and short-window/contemporaneous-correlation limitations to the external research document.
- [ ] Run `/home/wang/python_env/B1_RATE/bin/python -m pytest -q`; expect no failures.
- [ ] Commit repository code and tests only with message `docs: report rolling correlation rotation results`.

## Plan Self-Review

- Tasks 1--2 cover all point-in-time selection, de-duplication, fallback, MA10 execution, and unchanged-risk requirements.
- Task 3 covers every requested output and evidence requirement.
- Interface names and output records are consistent across all tasks; there are no unresolved placeholders.

## Execution Handoff

Execute inline in this session. Subagent-driven execution is unavailable because the current environment prohibits spawning subagents unless explicitly requested.
