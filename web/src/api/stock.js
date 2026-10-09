/**
 * 股票评分相关 API（走 Python main.py :8081）
 */
import client from './client'

export const stockApi = {
  getNextRunID() {
    return client.get('/score/runs/next-id')
  },

  getRuns(params = {}) {
    return client.get('/score/runs', { params })
  },

  getRun(id) {
    return client.get(`/score/runs/${id}`)
  },

  deleteRun(id) {
    return client.delete(`/score/runs/${id}`)
  },

  renameRun(id, name) {
    return client.put(`/score/runs/${id}/rename`, null, { params: { name } })
  },

  getRatings(id) {
    return client.get(`/score/runs/${id}/ratings`)
  },

  /**
   * 提交评分：服务端会创建一次运行并持久化。
   * @param {Array<{code:string,name?:string,klines:Array}>} stocks 股票及其 K 线
   * @param {string} runId 运行 ID（由 getNextRunID 获取）
   * @param {string} runName 运行名称
   * @param {string} method b1 / brick
   * @param {string} mode aggressive / conservative
   */
  rateBatch(stocks, runId, runName = '', method = 'b1', mode = 'aggressive') {
    return client.post('/score/runs', {
      id: runId,
      name: runName,
      method,
      mode,
      stocks,
    })
  },

  loadConfig() {
    return client.get('/config/stock-rater')
  },

  saveConfig(config) {
    return client.put('/config/stock-rater', { config })
  },

  fetchKLine(codes, start, end) {
    return client.post('/fetch-kline', { codes, start, end })
  },

  computeZxLines(code, klines) {
    return client.post('/compute-zx-lines', { code, klines })
  },
}

export default stockApi
