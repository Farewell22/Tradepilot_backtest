<template>
  <div class="bt-page">
    <div class="bt-header">
      <h2>📈 回测分析</h2>
      <n-space>
        <n-tag :bordered="false" size="large" type="info">
          {{ allRuns.length }} 个回测运行
        </n-tag>
        <n-button size="small" @click="loadData(true)" :loading="loading">
          刷新
        </n-button>
        <n-spin :show="loading" size="small" />
      </n-space>
    </div>

    <n-tabs type="line" animated v-model:value="activeTab">
      <n-tab-pane name="overview" tab="📊 运行概览">
        <n-card :bordered="false" class="bt-card">
          <RunReportView
            :run-id="selectedRunId"
            :all-runs="allRuns"
            @update:run-id="selectedRunId = $event"
          />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="trades" tab="📋 交易明细">
        <n-card :bordered="false" class="bt-card">
          <TradesTable
            :run-id="selectedRunId"
            :all-runs="allRuns"
            :reasons="reasons"
            @update:run-id="selectedRunId = $event"
            @open-kline="onOpenKLine"
          />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="amv" tab="📈 0AMV买点">
        <n-card :bordered="false" class="bt-card">
          <AmvBuyPointView />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="etf" tab="📉 ETF交易图">
        <n-card :bordered="false" class="bt-card">
          <EtfTradeChart
            :run-id="selectedRunId"
            :all-runs="allRuns"
            @update:run-id="selectedRunId = $event"
          />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="etf-amv" tab="📌 ETF+0AMV卖点">
        <n-card :bordered="false" class="bt-card">
          <EtfAmvSignalView />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="etf-ma10-gap" tab="📍 MA10乖离策略">
        <n-card :bordered="false" class="bt-card">
          <EtfMa10GapStrategyView />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="etf-rs20-rotation" tab="🎯 RS20 ETF选股因子策略">
        <n-card :bordered="false" class="bt-card">
          <EtfRs20RotationView />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="etf-dividend-low-vol" tab="📍 红利低波ETF策略">
        <n-card :bordered="false" class="bt-card">
          <EtfMa10GapStrategyView
            symbol="510880.SH"
            strategy-label="红利低波ETF策略"
            :load-strategy="backtestApi.getDividendLowVolStrategy"
          />
        </n-card>
      </n-tab-pane>

      <n-tab-pane name="manage" tab="📁 记录管理">
        <n-card :bordered="false" class="bt-card">
          <RunManager @runs-changed="loadData(true)" />
        </n-card>
      </n-tab-pane>
    </n-tabs>

    <TradeKLineDialog
      v-model:show="klineDialog.show"
      :trade-id="klineDialog.tradeId"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { backtestApi } from '@/api/backtest'
import RunReportView from '@/components/backtest/RunReportView.vue'
import TradesTable from '@/components/backtest/TradesTable.vue'
import TradeKLineDialog from '@/components/backtest/TradeKLineDialog.vue'
import RunManager from '@/components/backtest/RunManager.vue'
import AmvBuyPointView from '@/components/backtest/AmvBuyPointView.vue'
import EtfTradeChart from '@/components/backtest/EtfTradeChart.vue'
import EtfAmvSignalView from '@/components/backtest/EtfAmvSignalView.vue'
import EtfMa10GapStrategyView from '@/components/backtest/EtfMa10GapStrategyView.vue'
import EtfRs20RotationView from '@/components/backtest/EtfRs20RotationView.vue'

const POLL_INTERVAL_MS = 10_000

const activeTab = ref('overview')
const loading = ref(true)
const allRuns = ref([])
const selectedRunId = ref('')
const reasons = ref([])
const klineDialog = ref({ show: false, tradeId: '' })
let pollTimer = null

async function loadData(showLoading = false) {
  if (showLoading) loading.value = true
  try {
    const [runs, rs] = await Promise.all([
      backtestApi.listRuns(),
      backtestApi.getAllReasons().catch(() => ({ reasons: [] })),
    ])
    allRuns.value = runs
    reasons.value = rs.reasons || []
    // 选中 run 被删除时自动切换到第一个可用 run
    const exists = runs.find(r => r.run_id === selectedRunId.value)
    if (!exists) {
      const first = runs.find(r => r.has_report)
      selectedRunId.value = first ? first.run_id : ''
    } else if (!selectedRunId.value) {
      const first = runs.find(r => r.has_report)
      if (first) selectedRunId.value = first.run_id
    }
  } catch (e) {
    console.error('Failed to load backtest data:', e)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadData(true)
  pollTimer = setInterval(() => loadData(false), POLL_INTERVAL_MS)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function onOpenKLine(tradeId) {
  klineDialog.value = { show: true, tradeId }
}
</script>

<style scoped>
.bt-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}
.bt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.bt-header h2 {
  margin: 0;
  font-size: 20px;
}
</style>
