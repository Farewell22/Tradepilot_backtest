/**
 * 回测可视化 API 客户端
 * 走 vite proxy: /bt-api/* → http://localhost:8082/api/*
 */
import axios from 'axios'

const btClient = axios.create({
  baseURL: '/bt-api/v1',
  timeout: 60000  // K线请求可能慢（22s+），加大超时
})

btClient.interceptors.response.use(
  response => response.data,
  error => {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    console.error('[Backtest API]', msg)
    return Promise.reject(new Error(msg))
  }
)

export const backtestApi = {
  // 列出所有可用回测
  listRuns: () => btClient.get('/backtest/runs'),

  // 所有年度汇总
  getYearsSummary: () => btClient.get('/backtest/years/summary'),

  // 单次回测的 NAV 曲线
  getNav: (runId) => btClient.get(`/backtest/runs/${runId}/nav`),

  // ETF 日K线及每笔交易的买卖成对标记
  getEtfKLine: (runId) => btClient.get(`/backtest/runs/${runId}/etf-kline`),

  // 沪深300ETF 日K线及按日期对齐的 0AMV 卖点/极端风险预警
  getEtfAmvSignals: (startDate, endDate) =>
    btClient.get('/backtest/curves/etf-0amv-signals', {
      params: { start_date: startDate || undefined, end_date: endDate || undefined }
    }),

  // MA10乖离度二、三类组合策略的实际买卖点
  getEtfMa10GapStrategy: (stage) =>
    btClient.get(`/backtest/curves/etf-ma10-gap-strategy/${stage}`),

  // 红利低波ETF的同一 MA10乖离度策略实际买卖点
  getDividendLowVolStrategy: (stage) =>
    btClient.get(`/backtest/curves/dividend-low-vol-strategy/${stage}`),

  // 成交额低分位ETF轮动：动态候选池为默认主结果
  getAmountRatioRotation: (stage, universe = 'dynamic_universe') =>
    btClient.get(`/backtest/curves/amount-ratio-rotation/${stage}`, { params: { universe } }),

  // RS20 ETF选股因子轮动：按回测阶段和0AMV买点类别读取独立结果
  getRs20EtfRotation: (stage, signalType) =>
    btClient.get(`/backtest/curves/rs20-etf-rotation/${stage}`, {
      params: { signal_type: signalType }
    }),

  // 单次回测的 report（原文 + 结构化指标）
  getRunReport: (runId) => btClient.get(`/backtest/runs/${runId}/report`),

  // 单次回测的交易列表
  getTrades: (runId, params = {}) => btClient.get(`/backtest/runs/${runId}/trades`, { params }),

  // 所有止损原因（筛选用）
  getAllReasons: () => btClient.get('/backtest/trades/reasons'),

  // 读取真正生效的评分配置
  getConfig: () => btClient.get('/backtest/config'),

  // 单笔交易的 K 线（日K + 5min）
  getTradeKLine: (tradeId, range = 30) =>
    btClient.get(`/backtest/trades/${encodeURIComponent(tradeId)}/kline`, { params: { range } }),

  // ── 记录管理 ──
  deleteRun: (runId) => btClient.delete(`/backtest/runs/${runId}`),

  renameRun: (runId, newName) => btClient.put(`/backtest/runs/${runId}/rename`, { new_name: newName }),

  getRunMeta: (runId) => btClient.get(`/backtest/runs/${runId}/meta`),

  updateRunMeta: (runId, notes) => btClient.put(`/backtest/runs/${runId}/meta`, { notes }),

  // ── 曲线叠加 API ──

  // 仓位曲线
  getPositionCurve: (runId) => btClient.get(`/backtest/runs/${runId}/curves/position`),

  // 0AMV 活跃市值曲线
  get0AMVCurve: (startDate, endDate) =>
    btClient.get('/backtest/curves/0amv', { params: { start_date: startDate, end_date: endDate } }),

  // 0AMV 买点、均线和未来收益统计
  get0AMVBuyPoints: (startDate, endDate) =>
    btClient.get('/backtest/curves/0amv/buy-points', {
      params: { start_date: startDate || undefined, end_date: endDate || undefined }
    }),

  // 市场指数曲线（上证指数、深证成指等）
  getIndexCurve: (code, startDate, endDate) =>
    btClient.get('/backtest/curves/index', {
      params: { code, start_date: startDate, end_date: endDate }
    }),
}

export default btClient
