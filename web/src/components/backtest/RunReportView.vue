<template>
  <div>
    <!-- 回测运行选择器 -->
    <n-space align="center" style="margin-bottom: 16px;">
      <n-text depth="3" strong>回测运行：</n-text>
      <n-select
        v-model:value="selRunId"
        :options="runOptions"
        placeholder="选择回测运行"
        style="width: 360px;"
        filterable
        @update:value="loadRun"
      />
      <n-tag v-if="selectedRun" :bordered="false" type="info" size="small">
        {{ selectedRun.has_nav ? '有NAV' : '' }}
        {{ selectedRun.has_trades ? '有交易' : '' }}
        {{ selectedRun.has_report ? '有报告' : '' }}
      </n-tag>
    </n-space>

    <n-spin :show="loading">
      <template v-if="metrics || reportText">
        <!-- 报告摘要卡片 -->
        <n-grid :cols="4" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="总收益" :value="fmtPct(metrics?.total_return_pct)">
                <template #suffix>
                  <n-text :type="(metrics?.total_return_pct ?? 0) >= 0 ? 'success' : 'error'" depth="bold">
                    {{ (metrics?.total_return_pct ?? 0) >= 0 ? '↑' : '↓' }}
                  </n-text>
                </template>
              </n-statistic>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="年化收益" :value="fmtPct(metrics?.annualized_return_pct)" />
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="最大回撤" :value="fmtPct(metrics?.max_drawdown_pct)">
                <template #suffix>
                  <n-text type="error">↓</n-text>
                </template>
              </n-statistic>
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="夏普比率" :value="metrics?.sharpe_ratio?.toFixed(2) ?? '-'" />
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="初始资金" :value="fmtCurrency(metrics?.initial_cash)" />
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="期末净值" :value="fmtCurrency(metrics?.final_nav)" />
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="胜率" :value="fmtPct(metrics?.win_rate_pct)" />
            </n-card>
          </n-gi>
          <n-gi>
            <n-card size="small" :bordered="true">
              <n-statistic label="盈亏比" :value="metrics?.profit_loss_ratio?.toFixed(2) ?? '-'" />
            </n-card>
          </n-gi>
        </n-grid>

        <!-- 额外指标详情 -->
        <n-descriptions bordered size="small" :column="4" label-placement="left" style="margin-bottom: 16px;">
          <n-descriptions-item label="交易次数">{{ metrics?.n_trades }} (赢{{ metrics?.n_wins }}/输{{ metrics?.n_losses }})</n-descriptions-item>
          <n-descriptions-item label="平均盈利">{{ fmtPct(metrics?.avg_win_pct) }}</n-descriptions-item>
          <n-descriptions-item label="平均亏损">{{ fmtPct(metrics?.avg_loss_pct) }}</n-descriptions-item>
          <n-descriptions-item label="平均持仓">{{ metrics?.avg_hold_days?.toFixed(1) }} 天</n-descriptions-item>
          <n-descriptions-item label="交易日">{{ metrics?.n_trading_days }}</n-descriptions-item>
        </n-descriptions>

        <!-- 曲线选择器 -->
        <n-space v-if="navData.length" align="center" style="margin-bottom: 8px;">
          <n-text depth="3" style="font-size: 12px;">曲线叠加：</n-text>
          <n-checkbox-group v-model:value="selectedCurves" :size="'small'">
            <n-space :size="8">
              <n-checkbox value="nav" label="净值" />
              <n-checkbox value="returns" label="累计收益%" />
              <n-checkbox value="position" label="仓位%" />
              <n-checkbox value="0amv" label="0AMV" />
              <n-checkbox value="index" label="上证指数" />
            </n-space>
          </n-checkbox-group>
        </n-space>

        <!-- NAV 曲线 -->
        <div v-if="navData.length" ref="navChartRef" class="nav-chart"></div>

        <!-- 报告原文折叠面板 -->
        <n-collapse style="margin-top: 16px;">
          <n-collapse-item title="📄 报告原文" name="report">
            <pre class="report-text">{{ reportText }}</pre>
          </n-collapse-item>
          <n-collapse-item title="⚙️ 当前评分配置" name="config">
            <n-spin :show="configLoading" size="small">
              <n-empty v-if="!configData" description="加载失败" />
              <pre v-else class="report-text">{{ configText }}</pre>
            </n-spin>
          </n-collapse-item>
        </n-collapse>
      </template>
      <n-empty v-else-if="!loading" description="请选择一个回测运行" style="margin-top: 48px;" />
    </n-spin>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useTheme } from '@/composables/useTheme'
import { backtestApi } from '@/api/backtest'
import { NEmpty, NSpin, NSpace, NText, NSelect, NTag, NGrid, NGi, NCard, NStatistic, NDescriptions, NDescriptionsItem, NCollapse, NCollapseItem, NCheckboxGroup, NCheckbox } from 'naive-ui'

const props = defineProps({
  runId: { type: String, default: '' },
  allRuns: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:runId'])

const { isDark, colors, echartsTheme } = useTheme()

const selRunId = ref(props.runId || (props.allRuns[0]?.run_id ?? ''))
const selectedRun = computed(() => props.allRuns.find(r => r.run_id === selRunId.value))

const loading = ref(false)
const metrics = ref(null)
const reportText = ref('')
const navData = ref([])
const navChartRef = ref(null)
let navChart = null

// 曲线叠加数据
const selectedCurves = ref(['nav'])
const positionData = ref([])
const amvData = ref([])
const indexData = ref([])

// Config 展示（F-06）
const configLoading = ref(false)
const configData = ref(null)
const configText = computed(() => {
  if (!configData.value) return ''
  return JSON.stringify(configData.value, null, 2)
})

const runOptions = computed(() =>
  props.allRuns.map(r => ({
    label: `${r.label} ${r.has_report ? '' : '(无报告)'}`,
    value: r.run_id,
    disabled: !r.has_report,
  }))
)

async function loadRun(runId) {
  if (!runId) return
  loading.value = true
  navData.value = []
  metrics.value = null
  reportText.value = ''
  positionData.value = []
  amvData.value = []
  indexData.value = []
  try {
    const [report, nav] = await Promise.all([
      backtestApi.getRunReport(runId),
      backtestApi.getNav(runId).catch(() => []),
    ])
    metrics.value = report.metrics
    reportText.value = report.text
    navData.value = nav || []

    // 加载曲线叠加数据
    await loadCurves(runId)

    await nextTick()
    buildNavChart()
  } catch (e) {
    if (e?.response?.status === 404) {
      // run 已被删除，emit 清空让父组件切换
      emit('update:runId', '')
    }
    console.error('Failed to load run:', e)
  } finally {
    loading.value = false
  }
}

function buildNavChart() {
  if (!navChartRef.value || !navData.value.length) return
  if (navChart) navChart.dispose()
  navChart = echarts.init(navChartRef.value, echartsTheme.value)

  const dates = navData.value.map(p => {
    const d = p.date
    return d.length === 8 ? `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}` : d
  })

  const series = []
  const legend = []
  const yAxis = []
  let yAxisIndex = 0

  // 净值曲线
  if (selectedCurves.value.includes('nav')) {
    const nav = navData.value.map(p => +p.nav.toFixed(2))
    series.push({
      name: '净值',
      type: 'line',
      data: nav,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2, color: '#2196F3' },
      areaStyle: { color: 'rgba(33,150,243,0.1)' },
      yAxisIndex: 0
    })
    legend.push('净值')
  }

  // 累计收益曲线
  if (selectedCurves.value.includes('returns')) {
    const returns = navData.value.map(p => +p.return_pct.toFixed(2))
    series.push({
      name: '累计收益%',
      type: 'line',
      data: returns,
      smooth: true,
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { width: 2, color: '#4CAF50' },
      yAxisIndex: 0
    })
    legend.push('累计收益%')
  }

  // 仓位曲线
  if (selectedCurves.value.includes('position')) {
    const position = positionData.value.map(p => +p.position_pct.toFixed(2))
    series.push({
      name: '仓位%',
      type: 'line',
      data: position,
      smooth: true,
      symbol: 'circle',
      symbolSize: 4,
      lineStyle: { width: 2, color: '#FF9800' },
      areaStyle: { color: 'rgba(255,152,0,0.15)' },
      yAxisIndex: 1
    })
    legend.push('仓位%')
  }

  // 0AMV 曲线
  if (selectedCurves.value.includes('0amv')) {
    const amv = amvData.value.map(p => +p.value.toFixed(2))
    series.push({
      name: '0AMV',
      type: 'line',
      data: amv,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2, color: '#9C27B0' },
      yAxisIndex: 2
    })
    legend.push('0AMV')
  }

  // 指数曲线
  if (selectedCurves.value.includes('index')) {
    const idx = indexData.value.map(p => +p.close.toFixed(2))
    series.push({
      name: '上证指数',
      type: 'line',
      data: idx,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2, color: '#00BCD4', type: 'dashed' },
      yAxisIndex: 2
    })
    legend.push('上证指数')
  }

  // Y 轴配置
  yAxis.push(
    {
      type: 'value',
      name: '净值',
      position: 'left',
      axisLabel: { formatter: '{value}' }
    }
  )

  // 如果有仓位曲线，添加百分比 Y 轴
  if (selectedCurves.value.includes('position') || selectedCurves.value.includes('returns')) {
    yAxis.push({
      type: 'value',
      name: '%',
      position: 'right',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%' }
    })
  }

  // 如果有 0AMV 或指数曲线，添加指数 Y 轴
  if (selectedCurves.value.includes('0amv') || selectedCurves.value.includes('index')) {
    yAxis.push({
      type: 'value',
      name: '指数',
      position: 'right',
      axisLabel: { formatter: '{value}' }
    })
  }

  navChart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: legend,
      top: 0,
      left: 'center'
    },
    grid: {
      left: 60,
      right: 80,
      top: 40,
      bottom: 60
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { rotate: 45, fontSize: 10 }
    },
    yAxis: yAxis,
    series: series,
    dataZoom: [
      { type: 'inside' },
      { type: 'slider', bottom: 10 }
    ]
  })
}

function loadConfig() {
  configLoading.value = true
  backtestApi.getConfig()
    .then(d => configData.value = d)
    .catch(() => {})
    .finally(() => configLoading.value = false)
}

// 加载曲线叠加数据
async function loadCurves(runId) {
  const nav = navData.value
  if (!nav.length) return

  const startDate = nav[0].date
  const endDate = nav[nav.length - 1].date

  // 并行加载所有曲线
  const [pos, amv, idx] = await Promise.all([
    backtestApi.getPositionCurve(runId).catch(() => []),
    backtestApi.get0AMVCurve(startDate, endDate).catch(() => []),
    backtestApi.getIndexCurve('000001.SH', startDate, endDate).catch(() => [])
  ])

  positionData.value = pos
  amvData.value = amv
  indexData.value = idx
}

function fmtPct(v) {
  if (v === null || v === undefined) return '-'
  const n = parseFloat(v)
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function fmtCurrency(v) {
  if (!v) return '-'
  return `${parseFloat(v).toLocaleString()} 元`
}

watch(selRunId, (id) => {
  emit('update:runId', id)
  if (id) loadRun(id)
})

watch(() => props.runId, (id) => {
  if (id && id !== selRunId.value) {
    selRunId.value = id
  }
})

// 初始化
onMounted(() => {
  if (selRunId.value) loadRun(selRunId.value)
})

// 主题切换 → 重建 NAV 图表
watch(echartsTheme, () => {
  if (navChart) nextTick(buildNavChart)
})

// 曲线选择变化 → 重建图表
watch(selectedCurves, () => {
  if (navChart && navData.value.length) buildNavChart()
})

onUnmounted(() => navChart?.dispose())
</script>

<style scoped>
.nav-chart { width: 100%; height: 400px; margin-top: 8px; }
.report-text {
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  max-height: 400px;
  overflow-y: auto;
  background: var(--n-color, rgba(255,255,255,0.04));
  padding: 12px;
  border-radius: 4px;
}
</style>
