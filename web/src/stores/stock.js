/**
 * 股票评分 Store（简化版：仅保留评分、历史、配置）
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { stockApi } from '@/api'

export const useStockStore = defineStore('stock', () => {
  const loading = ref(false)
  const error = ref(null)
  const currentRun = ref(null)
  const currentResults = ref([])
  const runHistory = ref([])
  const selectedRunId = ref(null)
  const config = ref(null)

  const hasResults = computed(() => currentResults.value.length > 0)
  const passCount = computed(() => currentResults.value.filter(r => r.verdict === 'PASS').length)
  const watchCount = computed(() => currentResults.value.filter(r => r.verdict === 'WATCH').length)
  const failCount = computed(() => currentResults.value.filter(r => r.verdict?.startsWith('FAIL')).length)

  async function rateStocks(stocks, method = 'b1', mode = 'aggressive', runName = '') {
    loading.value = true
    error.value = null
    try {
      const { id } = await stockApi.getNextRunID()
      const response = await stockApi.rateBatch(stocks, id, runName, method, mode)
      currentRun.value = response.run
      currentResults.value = response.ratings || []
      selectedRunId.value = id
      return response
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchRuns() {
    loading.value = true
    error.value = null
    try {
      const response = await stockApi.getRuns()
      runHistory.value = response.runs || []
      return response
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchRun(id) {
    loading.value = true
    error.value = null
    try {
      const response = await stockApi.getRun(id)
      currentRun.value = response.run
      if (response.ratings) currentResults.value = response.ratings
      selectedRunId.value = id
      return response
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function deleteRun(id) {
    await stockApi.deleteRun(id)
    runHistory.value = runHistory.value.filter(r => r.id !== id)
    if (selectedRunId.value === id) {
      selectedRunId.value = null
      currentRun.value = null
      currentResults.value = []
    }
  }

  async function renameRun(id, name) {
    await stockApi.renameRun(id, name)
    const run = runHistory.value.find(r => r.id === id)
    if (run) run.name = name
    if (currentRun.value?.id === id) currentRun.value.name = name
  }

  async function fetchConfig() {
    try {
      const response = await stockApi.loadConfig()
      config.value = response.config || {}
      return response
    } catch (e) {
      config.value = {}
    }
  }

  async function saveConfig(newConfig) {
    await stockApi.saveConfig(newConfig)
    config.value = { ...newConfig }
  }

  function clearResults() {
    currentRun.value = null
    currentResults.value = []
    error.value = null
  }

  return {
    loading, error, currentRun, currentResults, runHistory, selectedRunId, config,
    hasResults, passCount, watchCount, failCount,
    rateStocks, fetchRuns, fetchRun, deleteRun, renameRun,
    fetchConfig, saveConfig, clearResults,
  }
})
