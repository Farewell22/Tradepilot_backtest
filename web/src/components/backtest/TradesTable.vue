<template>
  <div>
    <!-- 回测运行 + 筛选条 -->
    <n-space align="center" :wrap="false" style="margin-bottom: 12px;">
      <n-text depth="3" strong>回测运行：</n-text>
      <n-select
        v-model:value="localRunId"
        :options="runOptions"
        placeholder="选择回测运行"
        style="width: 260px;"
        filterable
        @update:value="onRunChange"
      />
      <n-text depth="3">代码:</n-text>
      <n-input
        v-model:value="filterCode"
        placeholder="如 603729"
        style="width: 120px;"
        clearable
      />
      <n-text depth="3">原因:</n-text>
      <n-select
        v-model:value="filterReason"
        :options="reasonOptions"
        placeholder="全部"
        style="width: 150px;"
        clearable
      />
      <n-text depth="3">盈亏:</n-text>
      <n-select
        v-model:value="filterWin"
        :options="winOptions"
        placeholder="全部"
        style="width: 80px;"
        clearable
      />
      <n-text v-if="allTrades.length" depth="3">共 {{ filteredTrades.length }} / {{ allTrades.length }} 笔</n-text>
    </n-space>

    <n-spin :show="loading">
      <n-empty v-if="!allTrades.length && !loading" description="该回测暂无交易记录" />
      <n-data-table v-else
        :columns="columns"
        :data="filteredTrades"
        :bordered="false"
        :single-line="false"
        size="small"
        :row-class-name="rowClass"
        max-height="600"
        virtual-scroll
        :row-props="rowProps"
      />
    </n-spin>
  </div>
</template>

<script setup>
import { ref, computed, watch, h } from 'vue'
import { backtestApi } from '@/api/backtest'
import { NDataTable, NSpin, NEmpty, NSpace, NText, NSelect, NInput } from 'naive-ui'

const props = defineProps({
  runId: { type: String, default: '' },
  allRuns: { type: Array, default: () => [] },
  reasons: { type: Array, default: () => [] },
})
const emit = defineEmits(['openKline', 'update:runId'])

const loading = ref(false)
const localRunId = ref(props.runId)
const allTrades = ref([])
const filterCode = ref('')
const filterReason = ref(null)
const filterWin = ref(null)

const runOptions = computed(() =>
  props.allRuns
    .filter(r => r.has_trades)
    .map(r => ({ label: r.label, value: r.run_id }))
)

const reasonOptions = computed(() =>
  props.reasons.map(r => ({ label: r, value: r }))
)

const winOptions = [
  { label: '盈利', value: 'win' },
  { label: '亏损', value: 'loss' },
]

const columns = [
  { title: '买入日', key: 'buy_date', width: 95, fixed: 'left' },
  { title: '代码', key: 'code', width: 120,
    render: (r) => r.score ? `${r.code} (${r.score})` : r.code },
  { title: '买入价', key: 'buy_price', width: 75,
    render: (r) => r.buy_exec_price.toFixed(2) },
  { title: '数量', key: 'buy_quantity', width: 55 },
  { title: '卖出日', key: 'sell_date', width: 95 },
  { title: '卖出价', key: 'sell_price', width: 75,
    render: (r) => r.sell_exec_price.toFixed(2) },
  { title: '盈亏%', key: 'pnl_pct', width: 80,
    render: (r) => h('span', {
      style: { color: r.pnl_pct >= 0 ? '#00C853' : '#FF1744', fontWeight: 'bold' }
    }, `${r.pnl_pct >= 0 ? '+' : ''}${r.pnl_pct.toFixed(2)}%`),
    sorter: (a, b) => a.pnl_pct - b.pnl_pct },
  { title: '金额', key: 'pnl', width: 80,
    render: (r) => {
      const v = r.pnl.toFixed(0)
      return h('span', { style: { color: r.pnl >= 0 ? '#00C853' : '#FF1744' } }, `${r.pnl >= 0 ? '+' : ''}${v}`)
    }},
  { title: '原因', key: 'sell_reason', width: 130 },
  { title: '持仓天', key: 'hold_days', width: 65 },
  { title: '', key: 'action', width: 50, fixed: 'right',
    render: (r) => h('a', {
      href: 'javascript:void(0)',
      style: { color: 'var(--n-color-target, #2196F3)', cursor: 'pointer' },
      onClick: () => emit('openKline', r.trade_id),
    }, 'K线') },
]

const filteredTrades = computed(() => {
  let list = allTrades.value
  if (filterCode.value) {
    const c = filterCode.value.toUpperCase()
    list = list.filter(t => t.code.includes(c))
  }
  if (filterReason.value) {
    list = list.filter(t => t.sell_reason === filterReason.value)
  }
  if (filterWin.value === 'win') {
    list = list.filter(t => t.pnl_pct >= 0)
  } else if (filterWin.value === 'loss') {
    list = list.filter(t => t.pnl_pct < 0)
  }
  return list
})

async function loadTrades(runId) {
  if (!runId) return
  loading.value = true
  allTrades.value = []
  try {
    allTrades.value = await backtestApi.getTrades(runId, { limit: 5000 })
  } catch (e) {
    console.error('Failed to load trades:', e)
  } finally {
    loading.value = false
  }
}

function onRunChange(id) {
  emit('update:runId', id)
  loadTrades(id)
}

function rowClass(row) {
  return row.pnl_pct >= 0 ? '' : 'trade-row-loss'
}

function rowProps(row) {
  return { style: 'cursor: pointer;' }
}

// 同步父组件的 runId
watch(() => props.runId, (id) => {
  if (id && id !== localRunId.value) {
    localRunId.value = id
    loadTrades(id)
  }
}, { immediate: true })
</script>

<style scoped>
:deep(.trade-row-loss) td {
  background: rgba(255, 23, 68, 0.03);
}
</style>
