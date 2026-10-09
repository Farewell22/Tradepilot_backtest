# RS20 ETF Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independently viewable RS20-selected ETF strategy timed by 0AMV class-2 and class-3 gap signals.

**Architecture:** A new research runner will select the highest-RS20 ETF from the dynamically available continuation universe on each signal date and reuse the established single-position execution engine and exits. Dashboard artifacts expose one signal class and stage at a time; a Vue view renders the resulting portfolio statistics.

**Tech Stack:** Python, pandas, FastAPI/Pydantic, Vue 3, Naive UI, ECharts.

**Spec:** `workspace/feature/RS20ETF选股因子策略.md`

## Global Constraints

- Preserve the existing MA10 gap strategy and its API unchanged.
- Process class-2 and class-3 signals separately.
- Use the seven TRAIN-derived continuation ETFs and select dynamic-availability RS20 Top-1.
- Fall back to 510300 if no candidate can compute RS20; retain existing exit and overlapping-signal handling.

---

### Task 1: RS20 selection and artifact runner

**Files:**
- Create: `python/backtest/research_0amv_rs20_etf_rotation.py`
- Create: `python/tests/backtest/test_rs20_etf_rotation.py`

**Interfaces:**
- Produces `choose_rs20_candidate(candidates)`, `candidate_rs20(...)`, `build_selection_schedule(...)`, and `run_research(...)`.
- Writes `summary.csv`, `nav_{class}_{stage}.csv`, `annual_{class}_{stage}.csv`, `trades_{class}_{stage}.csv`, and `selections_{class}.csv`.

- [ ] Write failing tests for selecting the highest RS20, deterministic ties, and fallback when no candidate is available.
- [ ] Run the focused pytest module and observe the missing-module failure.
- [ ] Implement point-in-time RS20 selection and separate class-2/class-3 research runs by reusing the existing rotation execution engine.
- [ ] Run the focused pytest module and confirm it passes.

### Task 2: Dashboard contract

**Files:**
- Modify: `python/backtest_dashboard/schemas.py`
- Modify: `python/backtest_dashboard/service.py`
- Modify: `python/backtest_dashboard/api.py`
- Create: `python/tests/backtest/test_dashboard_rs20_rotation.py`

**Interfaces:**
- Produces `GET /api/v1/backtest/curves/rs20-etf-rotation/{stage}?signal_type=class_2|class_3`.

- [ ] Write a failing loader/API test using fixture CSV artifacts.
- [ ] Run the focused pytest module and observe the missing endpoint/loader failure.
- [ ] Add RS20 response models, artifact loading, validation, and route.
- [ ] Run the focused pytest module and confirm it passes.

### Task 3: Frontend strategy page

**Files:**
- Create: `web/src/components/backtest/EtfRs20RotationView.vue`
- Modify: `web/src/api/backtest.js`
- Modify: `web/src/views/Backtest.vue`

**Interfaces:**
- Consumes the RS20 dashboard route and exposes stage plus class-2/class-3 controls.

- [ ] Add the API client, visual view, and the independent Backtest tab without restoring the amount-ratio tab.
- [ ] Run `npm run build` from `web` and confirm production compilation succeeds.

### Task 4: End-to-end research verification

**Files:**
- Generated: `data/backtest_runs/etf_rs20_rotation_0amv/*`

- [ ] Run the RS20 research module with the repository data paths.
- [ ] Run all focused tests, the affected dashboard tests, and the frontend production build.
- [ ] Review generated report/summary and confirm four class-stage result rows plus RS20 selection metadata.
