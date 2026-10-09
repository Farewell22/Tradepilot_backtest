<template>
  <div class="rating-table">
    <!-- Toolbar: search + column settings -->
    <div class="table-toolbar">
      <n-input
        v-model:value="searchQueryRaw"
        placeholder="搜索代码或名称..."
        clearable
        :style="{ width: '240px' }"
        size="small"
      >
        <template #prefix>
          <n-icon><SearchIcon /></n-icon>
        </template>
      </n-input>

      <n-popover trigger="click" placement="bottom-end" :width="180">
        <template #trigger>
          <n-button quaternary size="small">
            <template #icon>
              <n-icon><SettingsIcon /></n-icon>
            </template>
            列设置
          </n-button>
        </template>
        <n-checkbox-group v-model:value="visibleKeys">
          <n-space vertical :size="6">
            <n-checkbox
              v-for="col in allColumnMeta"
              :key="col.key"
              :value="col.key"
              :disabled="col.key === 'code'"
            >
              {{ col.title }}
            </n-checkbox>
          </n-space>
        </n-checkbox-group>
      </n-popover>

      <div class="score-filter">
        <span class="score-label">≥ {{ scoreThreshold }} 分</span>
        <n-slider v-model:value="scoreThreshold" :min="0" :max="100" :style="{ width: '120px' }" />
      </div>

      <n-button v-if="hasActiveFilters" quaternary size="small" type="warning" @click="resetAllFilters">
        清除筛选
      </n-button>
    </div>

    <n-data-table
      :columns="columns"
      :data="filteredData"
      :pagination="pagination"
      :bordered="false"
      :row-key="(row) => row.code || row.stock_code"
      size="small"
      striped
      :row-props="rowProps"
      :scroll-x="totalColumnWidth"
    />
  </div>
</template>

<script setup>
import { h, ref, computed, watch } from 'vue'
import { NTag, NButton, NSpace, NProgress, NInput, NSlider, NIcon, NPopover, NCheckboxGroup, NCheckbox, NTooltip } from 'naive-ui'
import {
  CheckOutlined, CloseOutlined, WarningOutlined, EditOutlined,
  SearchOutlined, SettingOutlined
} from '@vicons/antd'
import { useTableFilter } from '@/composables/useTableFilter'

const props = defineProps({
  data: { type: Array, default: () => [] },
  annotationMap: { type: Object, default: () => ({}) },
  showHoldingPoolAction: { type: Boolean, default: false }
})

const emit = defineEmits(['annotate', 'view-kline', 'addToHoldingPool'])

// ── Search (debounced) ──
const searchQueryRaw = ref('')
let searchTimer = null
watch(searchQueryRaw, (val) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { searchQuery.value = val }, 300)
}, { immediate: true })

// ── Column visibility ──
const allColumnMeta = [
  { key: 'code', title: '代码', locked: true },
  { key: 'name', title: '名称' },
  { key: 'total', title: '评分' },
  { key: 'verdict', title: '判定' },
  { key: 'annotation', title: '标注' },
  { key: 'signal', title: '信号' },
  { key: 'signalName', title: '信号名' },
  { key: 'industry', title: '行业' },
  { key: 'closePrice', title: '收盘价' },
  { key: 'changePct', title: '涨跌幅' },
  { key: 'rrRatio', title: '盈亏比' },
  { key: 'stopPrice', title: '止损' },
  { key: 'comment', title: '评语' },
]

function loadVisibleKeys() {
  try {
    const saved = localStorage.getItem('rating-table-columns')
    if (saved) {
      const parsed = JSON.parse(saved)
      // ensure 'code' is always included
      if (!parsed.includes('code')) parsed.unshift('code')
      // filter out deprecated 'grade' key (merged into 'total')
      return parsed.filter(k => k !== 'grade')
    }
  } catch {}
  return allColumnMeta.map(c => c.key)
}

const visibleKeys = ref(loadVisibleKeys())

watch(visibleKeys, (val) => {
  try {
    localStorage.setItem('rating-table-columns', JSON.stringify(val))
  } catch {}
}, { deep: true })

// ── Data mapping ──
const tableData = computed(() => {
  return props.data.map(item => ({
    ...item,
    code: item.code || item.stock_code || '',
    name: item.name || item.stock_name || '-',
    total: item.total || item.total_score || 0,
    grade: item.grade || '-',
    verdict: item.verdict || 'UNKNOWN',
    signal: item.signal_type || item.signal || '-',
    signalName: item.signal_name || '-',
    industry: item.industry || '-',
    closePrice: item.close_price || '-',
    changePct: item.change_pct || 0,
    rrRatio: item.rr_ratio || '-',
    stopPrice: item.stop_price || '-',
    comment: item.comment || '-',
    ann: props.annotationMap[item.code || item.stock_code] || null
  }))
})

// ── 搜索 + 分数筛选（composable，列筛选由 Naive UI 原生处理）──
const {
  searchQuery, scoreThreshold,
  hasActiveFilters, filteredData, resetAllFilters,
} = useTableFilter(tableData, {
  searchKeys: ['code', 'name'],
  enableScoreFilter: true,
})

// ── Column definitions (build each column with sorter/filter) ──
// ── Score cell renderer ──
function renderScoreCell(score) {
  const v = score || 0
  const color = v >= 80 ? '#00C853' : v >= 60 ? '#FF9800' : v >= 40 ? '#FF5722' : '#9E9E9E'
  return h('div', { class: 'rating-cell' }, [
    h(NProgress, { type: 'line', percentage: v, color, showIndicator: false, height: 5, railColor: 'rgba(255,255,255,0.08)' }),
    h('span', { class: 'font-mono', style: { color, fontWeight: 500, fontSize: '12px' } }, String(v)),
  ])
}

const columns = computed(() => {
  const all = [
    {
      title: '代码',
      key: 'code',
      width: 90,
      fixed: 'left',
      sorter: (a, b) => a.code.localeCompare(b.code),
      render: (row) => h('span', {
        class: 'font-mono font-bold kline-link',
        style: { cursor: 'pointer', color: '#42A5F5' },
        onClick: (e) => {
          e.stopPropagation()
          emit('view-kline', { code: row.code, name: row.name })
        }
      }, row.code)
    },
    {
      title: '名称',
      key: 'name',
      width: 110,
      ellipsis: { tooltip: true },
      sorter: (a, b) => a.name.localeCompare(b.name)
    },
    {
      title: '评分',
      key: 'total',
      width: 140,
      sorter: (a, b) => a.total - b.total,
      render: (row) => {
        const score = row.total || 0
        const grade = row.grade || '-'
        const color = score >= 75 ? '#00C853' : score >= 60 ? '#FF9800' : '#FF1744'
        return h('div', { class: 'rating-cell' }, [
          h(NProgress, {
            type: 'line',
            percentage: score,
            color,
            showIndicator: false,
            height: 6,
            railColor: 'rgba(255,255,255,0.1)'
          }),
          h('div', { class: 'rating-info' }, [
            h('span', { class: 'font-mono score', style: { color, fontWeight: 600 } }, score.toFixed(1)),
            grade !== '-' ? h(NTag, {
              type: grade === 'A' ? 'success' : grade === 'B' ? 'info' : 'warning',
              size: 'small',
              bordered: false,
              style: { marginLeft: '6px' }
            }, { default: () => grade }) : null
          ])
        ])
      }
    },
    {
      title: '判定',
      key: 'verdict',
      width: 90,
      sorter: (a, b) => {
        const order = { PASS: 0, WATCH: 1, FAIL: 2, UNKNOWN: 3 }
        return (order[a.verdict] ?? 99) - (order[b.verdict] ?? 99)
      },
      filter: (value, row) => {
        // Use startsWith to match "FAIL(总分不足)" etc.
        if (value === 'FAIL') return row.verdict?.startsWith('FAIL') ?? false
        if (value === 'WATCH') return row.verdict?.startsWith('WATCH') ?? false
        if (value === 'PASS') return row.verdict?.startsWith('PASS') ?? false
        return false
      },
      filterOptions: [
        { label: 'PASS', value: 'PASS' },
        { label: 'WATCH', value: 'WATCH' },
        { label: 'FAIL', value: 'FAIL' }
      ],
      filterMultiple: true,
      render: (row) => {
        const verdict = row.verdict || ''
        const prefix = verdict.startsWith('PASS') ? 'PASS'
          : verdict.startsWith('WATCH') ? 'WATCH'
          : verdict.startsWith('FAIL') ? 'FAIL'
          : verdict
        let type = 'default'
        let icon = null
        if (verdict.startsWith('PASS')) {
          type = 'success'; icon = CheckOutlined
        } else if (verdict.startsWith('WATCH')) {
          type = 'warning'; icon = WarningOutlined
        } else if (verdict.startsWith('FAIL')) {
          type = 'error'; icon = CloseOutlined
        }
        const tag = h(NTag, { type, size: 'small', bordered: false }, {
          default: () => prefix,
          icon: () => icon ? h(icon) : null
        })
        if (verdict !== prefix) {
          return h(NTooltip, { trigger: 'hover' }, {
            trigger: () => tag,
            default: () => verdict
          })
        }
        return tag
      }
    },
    {
      title: '标注',
      key: 'annotation',
      width: 90,
      sorter: (a, b) => {
        const val = (x) => x.ann?.is_successful === true ? 0 : x.ann?.is_successful === false ? 1 : 2
        return val(a) - val(b)
      },
      render: (row) => {
        const ann = row.ann
        let type = 'default'
        let text = '未标记'
        if (ann) {
          if (ann.is_successful === true) { type = 'success'; text = '成功' }
          else if (ann.is_successful === false) { type = 'error'; text = '失败' }
        }
        return h(NTag, {
          type,
          size: 'small',
          bordered: false,
          style: { cursor: 'pointer' },
          onClick: (e) => {
            e.stopPropagation()
            emit('annotate', row)
          }
        }, {
          default: () => text,
          icon: () => h(EditOutlined, { style: { fontSize: '12px' } })
        })
      }
    },
    {
      title: '信号',
      key: 'signal',
      width: 80,
      sorter: (a, b) => {
        const order = { B1: 0, B2: 1, '砖型图': 2 }
        return (order[a.signal] ?? 99) - (order[b.signal] ?? 99)
      },
      filter: (value, row) => {
        if (value === '-') return !row.signal || row.signal === '-' || row.signal === '无信号'
        return row.signal === value
      },
      filterOptions: [
        { label: 'B1', value: 'B1' },
        { label: 'B2', value: 'B2' },
        { label: '砖型图', value: '砖型图' },
        { label: '无信号', value: '-' }
      ],
      filterMultiple: true,
      render: (row) => {
        const signal = row.signal
        if (!signal || signal === '-' || signal === '无信号') {
          return h('span', { class: 'text-gray' }, '-')
        }
        const type = signal === 'B1' ? 'success' : signal === 'B2' ? 'info' : signal === '砖型图' ? 'warning' : 'default'
        return h(NTag, { type, size: 'small' }, { default: () => signal })
      }
    },
    {
      title: '信号名',
      key: 'signalName',
      width: 100,
      ellipsis: { tooltip: true },
      sorter: (a, b) => a.signalName.localeCompare(b.signalName),
      render: (row) => {
        const name = row.signalName
        if (!name || name === '-') return h('span', { class: 'text-gray' }, '-')
        return h('span', { class: 'text-xs' }, name)
      }
    },
    {
      title: '行业',
      key: 'industry',
      width: 90,
      ellipsis: { tooltip: true },
      sorter: (a, b) => a.industry.localeCompare(b.industry)
    },
    {
      title: '收盘价',
      key: 'closePrice',
      width: 90,
      sorter: (a, b) => {
        const pa = parseFloat(a.closePrice)
        const pb = parseFloat(b.closePrice)
        if (isNaN(pa)) return 1
        if (isNaN(pb)) return -1
        return pa - pb
      },
      render: (row) => h('span', { class: 'font-mono' }, row.closePrice)
    },
    {
      title: '涨跌幅',
      key: 'changePct',
      width: 90,
      sorter: (a, b) => a.changePct - b.changePct,
      render: (row) => {
        const change = row.changePct || 0
        const color = change > 0 ? '#00C853' : change < 0 ? '#FF1744' : '#9E9E9E'
        const sign = change > 0 ? '+' : ''
        return h('span', { class: 'font-mono', style: { color } }, `${sign}${change.toFixed(2)}%`)
      }
    },
    {
      title: '盈亏比',
      key: 'rrRatio',
      width: 80,
      sorter: (a, b) => {
        const ra = parseFloat(a.rrRatio)
        const rb = parseFloat(b.rrRatio)
        if (isNaN(ra)) return 1
        if (isNaN(rb)) return -1
        return ra - rb
      },
      render: (row) => {
        const ratio = row.rrRatio
        if (!ratio || ratio === '-') return h('span', { class: 'text-gray' }, '-')
        return h('span', { class: 'font-mono' }, ratio)
      }
    },
    {
      title: '止损',
      key: 'stopPrice',
      width: 90,
      sorter: (a, b) => {
        const pa = parseFloat(a.stopPrice)
        const pb = parseFloat(b.stopPrice)
        if (isNaN(pa)) return 1
        if (isNaN(pb)) return -1
        return pa - pb
      },
      render: (row) => {
        const stop = row.stopPrice
        if (!stop || stop === '-') return h('span', { class: 'text-gray' }, '-')
        return h('span', { class: 'font-mono text-warning' }, stop)
      }
    },
    {
      title: '评语',
      key: 'comment',
      width: 400,
      sorter: (a, b) => a.comment.localeCompare(b.comment)
    }
  ]

  // Add holding pool action column if enabled
  if (props.showHoldingPoolAction) {
    all.push({
      title: '暂存',
      key: 'holdingPool',
      width: 70,
      fixed: 'right',
      render: (row) => h(NButton, {
        size: 'small',
        quaternary: true,
        type: 'success',
        onClick: (e) => {
          e.stopPropagation()
          emit('addToHoldingPool', row)
        }
      }, { default: () => '+暂存' })
    })
  }

  return all.filter(col => col.key === 'holdingPool' || visibleKeys.value.includes(col.key))
})

// ── Horizontal scroll width ──
// Sum the widths of all visible columns so Naive UI enables horizontal scroll
const totalColumnWidth = computed(() => {
  let total = 0
  for (const col of columns.value) {
    total += col.width || 0
  }
  return total + 20
})

const pagination = {
  pageSize: 20,
  pageSizes: [10, 20, 50, 100],
  showSizePicker: true,
  showQuickJumper: true
}

function rowProps(row) {
  return { style: { cursor: 'pointer' } }
}
</script>

<style scoped>
.rating-table {
  border-radius: 8px;
  overflow-x: auto;
  overflow-y: visible;
}
.rating-table :deep(.n-data-table) { background: transparent; }
.rating-table :deep(.n-data-table-th) {
  background: var(--bg-sider);
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.rating-table :deep(.n-data-table-td) {
  background: transparent;
  border-bottom: 1px solid var(--table-border-strong);
  border-right: 1px solid var(--table-border);
}
.rating-table :deep(.n-data-table-td:last-child) {
  border-right: none;
}
.rating-table :deep(.n-data-table-th) {
  border-bottom: 2px solid var(--table-border);
  border-right: 1px solid var(--table-border);
}
.rating-table :deep(.n-data-table-th:last-child) {
  border-right: none;
}
.rating-table :deep(.n-data-table-tr:hover .n-data-table-td) {
  background: var(--gold-glow);
}
.score-cell { display: flex; flex-direction: column; gap: 4px; }
.rating-cell { display: flex; flex-direction: column; gap: 4px; }
.rating-info { display: flex; align-items: center; }
.font-mono { font-family: 'JetBrains Mono', 'Roboto Mono', monospace; }
.font-bold { font-weight: 600; }
.text-gray { color: var(--text-muted); }
.text-warning { color: #FF9800; }
.text-xs { font-size: 12px; }

/* Toolbar */
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 8px;
}

/* Score filter */
.score-filter {
  display: flex;
  align-items: center;
  gap: 8px;
}
.score-label {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  min-width: 60px;
}
</style>
