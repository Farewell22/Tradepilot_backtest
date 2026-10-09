# 0AMV Factor Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible offline experiment that evaluates 0AMV technical factors against future index returns and full-market breadth.

**Architecture:** A new `python.factor_research` package remains independent of the B1 trading backtest. It loads and validates source data, computes features and point-in-time labels, evaluates each factor/target pair, and writes immutable experiment artifacts through one CLI command.

**Tech Stack:** Python 3.12, pandas, numpy, pyarrow, PyYAML, pytest, existing `TencentSource`.

**Spec:** `docs/superpowers/specs/2026-08-31-0amv-factor-research-design.md`

## Global Constraints

- Features at `t` use only 0AMV observations dated on or before `t`; labels use the `h`th subsequent trading date.
- Default factors are MA gaps for 5/10/20/60 days and returns for 1/3/5/10 days; default horizons are 1/3/5/10 trading days and groups are quintiles.
- Breadth excludes stocks without valid positive prices at both endpoints; it must not silently substitute missing prices.
- Cache-first index retrieval is mandatory; `--refresh` is the only way to request a new download.
- New code must not import or call `TimingSignal`, portfolio, simulator, or B1 strategy modules.
- Execute tests using `/home/wang/python_env/B1_RATE/bin/python -m pytest` because the system `python` command and system pytest are unavailable.

---

### Task 1: Core factor and label primitives

**Files:**
- Create: `python/factor_research/__init__.py`
- Create: `python/factor_research/features.py`
- Create: `python/factor_research/labels.py`
- Test: `python/tests/factor_research/test_features.py`
- Test: `python/tests/factor_research/test_labels.py`

**Interfaces:**
- Produces `build_0amv_features(amv: pd.DataFrame, ma_windows: Sequence[int], return_windows: Sequence[int]) -> pd.DataFrame` with a unique normalized `date` plus `amv_ma_gap_{N}` and `amv_return_{N}` columns.
- Produces `build_forward_return_labels(prices: pd.DataFrame, horizons: Sequence[int], prefix: str) -> pd.DataFrame` with `{prefix}_forward_return_{h}` columns.
- Produces `build_breadth_labels(closes: pd.DataFrame, horizons: Sequence[int]) -> pd.DataFrame` with `advancers_{h}`, `decliners_{h}`, `unchanged_{h}`, `eligible_count_{h}`, and `advance_ratio_{h}` columns.

- [ ] **Step 1: Write failing feature tests**

```python
def test_build_0amv_features_uses_only_current_and_prior_values():
    amv = frame(date=["2024-01-02", "2024-01-03", "2024-01-04"], close=[10, 20, 30])
    actual = build_0amv_features(amv, ma_windows=[2], return_windows=[1])
    assert actual.loc[actual.date == "2024-01-03", "amv_ma_gap_2"].item() == 1 / 3
    assert actual.loc[actual.date == "2024-01-03", "amv_return_1"].item() == 1.0
```

- [ ] **Step 2: Run the feature test and verify it fails because the module is absent**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_features.py -q`

- [ ] **Step 3: Implement the minimal feature builder**

```python
def build_0amv_features(amv, ma_windows, return_windows):
    normalized = _normalize_close_frame(amv)
    for window in ma_windows:
        normalized[f"amv_ma_gap_{window}"] = normalized["close"] / normalized["close"].rolling(window).mean() - 1
    for window in return_windows:
        normalized[f"amv_return_{window}"] = normalized["close"].pct_change(window)
    return normalized
```

- [ ] **Step 4: Run the feature test and verify it passes**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_features.py -q`

- [ ] **Step 5: Write failing forward-return and breadth-label tests**

```python
def test_breadth_uses_hth_subsequent_date_and_excludes_missing_endpoints():
    closes = pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "AAA": [10, 11, 12], "BBB": [20, float("nan"), 19]})
    labels = build_breadth_labels(closes, horizons=[2])
    row = labels.loc[labels.date == "2024-01-02"].iloc[0]
    assert row["eligible_count_2"] == 2
    assert row["advancers_2"] == 1
    assert row["decliners_2"] == 1
```

- [ ] **Step 6: Run the label tests and verify they fail because label builders are absent**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_labels.py -q`

- [ ] **Step 7: Implement minimal date-position-based label builders**

Use `DataFrame.shift(-h)` for a normalized, ascending index series. For breadth, calculate each stock return against its `h`-row future value, then count only non-null returns and return null label values for the trailing `h` rows.

- [ ] **Step 8: Run both primitive test files and verify they pass**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_features.py python/tests/factor_research/test_labels.py -q`

### Task 2: Research data and cache layer

**Files:**
- Create: `python/factor_research/data.py`
- Test: `python/tests/factor_research/test_data.py`

**Interfaces:**
- Produces `load_amv_csv(path: Path) -> pd.DataFrame` with validated `date` and `close` columns.
- Produces `IndexCache(cache_root: Path, source_factory: Callable[[], TencentSource])` and `load(code: str, start_date: str, end_date: str, refresh: bool) -> pd.DataFrame`.
- Produces `load_market_close_panel(data_root: Path, start_date: str, end_date: str) -> pd.DataFrame` whose rows are dates and columns are stock codes.

- [ ] **Step 1: Write failing cache and CSV validation tests**

```python
def test_existing_index_cache_is_used_without_network(tmp_path):
    write_index_csv(tmp_path / "sh000001.csv")
    source_factory = Mock(side_effect=AssertionError("network should not run"))
    result = IndexCache(tmp_path, source_factory).load("sh000001", "20240101", "20240131", refresh=False)
    assert result["close"].tolist() == [3000.0]
```

- [ ] **Step 2: Run data tests and verify they fail because the data layer is absent**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_data.py -q`

- [ ] **Step 3: Implement input validation and cache-first index loading**

`IndexCache.load` reads the existing cache when `refresh` is false. Otherwise it initializes the existing Tencent source with `{"tencent": {}}`, calls `fetch_kline_raw`, validates non-empty OHLCV output, and writes a normalized CSV. If downloading fails but a cache existed, return that cache and emit a warning; with no cache raise `ResearchDataError`.

- [ ] **Step 4: Write the failing Parquet aggregation test**

Create a temporary daily Parquet input with two codes and two intraday bars per code; assert the returned panel has the final intraday close for each date/code.

- [ ] **Step 5: Implement the minimal Parquet close-panel loader**

Read only `code`, `date`, `trade_time`, and `close`; sort by `trade_time`, take each code's final close for a date, validate requested daily files exist, then pivot to a sorted date-by-code panel.

- [ ] **Step 6: Run data tests and verify they pass**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_data.py -q`

### Task 3: Evaluation and reproducible reporting

**Files:**
- Create: `python/factor_research/evaluators.py`
- Create: `python/factor_research/reporting.py`
- Test: `python/tests/factor_research/test_evaluators.py`
- Test: `python/tests/factor_research/test_reporting.py`

**Interfaces:**
- Produces `evaluate_factor(observations: pd.DataFrame, factor_name: str, target_name: str, groups: int) -> dict[str, object]`.
- Produces `evaluate_all(observations: pd.DataFrame, factor_columns: Sequence[str], target_columns: Sequence[str], horizons: Sequence[int], groups: int) -> pd.DataFrame`.
- Produces `write_experiment_artifacts(output_dir: Path, observations: pd.DataFrame, summary: pd.DataFrame, metadata: Mapping[str, object]) -> None`.

- [ ] **Step 1: Write failing evaluation tests**

```python
def test_evaluate_factor_reports_correlation_and_quintile_spread():
    observations = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=10), "factor": range(10), "target": range(10)})
    result = evaluate_factor(observations, "factor", "target", groups=5)
    assert result["pearson_correlation"] == pytest.approx(1.0)
    assert result["q5_minus_q1"] > 0
```

- [ ] **Step 2: Run evaluator tests and verify failure**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_evaluators.py -q`

- [ ] **Step 3: Implement minimal evaluation**

Drop rows missing either factor or target. Require at least `groups` distinct observations. Use `pd.qcut(..., duplicates="drop")`; if fewer than `groups` bins exist, return a non-evaluable record with a reason. For evaluable data calculate Pearson/Spearman, group sample counts/means/medians/positive rates, Q5-Q1, monotonic direction, and natural-year directional consistency.

- [ ] **Step 4: Write failing reporting tests**

Test that a fresh temporary output directory receives exactly `observations.csv`, `factor_summary.csv`, `metadata.json`, and `report.md`; assert a pre-existing output directory raises `FileExistsError`.

- [ ] **Step 5: Implement atomic artifact writer and Markdown renderer**

Write CSV and JSON with UTF-8, include all required metadata keys supplied by the runner, create an explicit methodology/data-quality section in `report.md`, and reject an existing output directory before writing anything.

- [ ] **Step 6: Run evaluator and reporting tests and verify they pass**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_evaluators.py python/tests/factor_research/test_reporting.py -q`

### Task 4: Configuration and CLI orchestration

**Files:**
- Create: `python/factor_research/run_experiment.py`
- Create: `python/config/factor_research_0amv.yaml`
- Test: `python/tests/factor_research/test_run_experiment.py`

**Interfaces:**
- CLI command: `python -m python.factor_research.run_experiment --config <path> [--refresh]`.
- Config keys: `sample.start_date`, `sample.end_date`, `paths.amv_csv`, `paths.market_data_root`, `paths.index_cache_root`, `paths.output_root`, `factors.ma_windows`, `factors.return_windows`, `evaluation.horizons`, `evaluation.groups`, and `indices` mapping `sh000001`/`sz399001`.

- [ ] **Step 1: Write a failing end-to-end CLI test**

Build a temporary YAML config, AMV CSV, index cache files, and two-day-per-stock Parquet inputs. Invoke `main(["--config", str(config)])`, assert exit code 0 and verify a single run directory includes all four artifacts and the Git commit metadata key.

- [ ] **Step 2: Run the CLI test and verify it fails because the runner is absent**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_run_experiment.py -q`

- [ ] **Step 3: Implement configuration parsing and runner orchestration**

Resolve data paths relative to the repository root, build factors, index labels, and breadth labels, left-join by date, evaluate all combinations, calculate SHA-256 for existing input files, obtain `git rev-parse HEAD` with a safe `"unknown"` fallback, generate `<UTC timestamp>-<config hash>` run IDs, and delegate artifact writing.

- [ ] **Step 4: Add the default YAML configuration**

Set current project-relative input paths and defaults defined in Global Constraints. Default output paths must remain under ignored `data/`.

- [ ] **Step 5: Run the CLI test and verify it passes**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research/test_run_experiment.py -q`

- [ ] **Step 6: Run the full test suite and verify it passes**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research -q`

### Task 5: Review and handoff

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the research command and output locations**

Add a short “0AMV 因子研究” section with the exact CLI command, cache refresh behavior, output artifact names, and statement that results are predictive-factor research rather than trading advice.

- [ ] **Step 2: Run final validation**

Run: `/home/wang/python_env/B1_RATE/bin/python -m pytest python/tests/factor_research -q`

- [ ] **Step 3: Inspect the final diff and report the test output**

Run: `git diff --check && git status --short`
