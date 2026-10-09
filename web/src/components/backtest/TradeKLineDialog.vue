<template>
  <n-drawer :show="show" :width="drawerWidth" placement="right" @update:show="onUpdateShow">
    <n-drawer-content :native-scrollbar="false">
      <template #header>
        <div class="dwr-hdr">
          <span>{{ klineData?.code || '加载中...' }}</span>
          <n-tag v-if="klineData" :type="klineData.pnl_pct >= 0 ? 'success' : 'error'" size="small">
            {{ klineData.pnl_pct >= 0 ? '+' : '' }}{{ klineData.pnl_pct?.toFixed(2) }}%
          </n-tag>
        </div>
      </template>

      <n-spin :show="loading">
        <div v-if="error" class="err-msg">{{ error }}</div>
        <div v-else-if="klineData">
          <!-- 交易信息卡片 -->
          <n-descriptions bordered size="small" :column="2" label-placement="left">
            <n-descriptions-item label="买入日">{{ klineData.buy_date }}</n-descriptions-item>
            <n-descriptions-item label="卖出日">{{ klineData.sell_date }}</n-descriptions-item>
            <n-descriptions-item label="买入价">{{ klineData.buy_exec_price?.toFixed(2) }}</n-descriptions-item>
            <n-descriptions-item label="卖出价">{{ klineData.sell_exec_price?.toFixed(2) }}</n-descriptions-item>
            <n-descriptions-item label="止损原因">{{ klineData.sell_reason }}</n-descriptions-item>
          </n-descriptions>

          <!-- 日K线 -->
          <div class="chart-title">日K线 (±30天)</div>
          <div ref="dailyChartRef" class="kline-chart"></div>

          <!-- 5min 详细图：单个div + watch 切换 -->
          <div class="chart-title" style="margin-top: 16px;">
            <n-tabs type="segment" size="small" animated v-model:value="minChartTab">
              <n-tab-pane name="buy" :tab="`买入日 (${klineData.buy_date})`" />
              <n-tab-pane name="sell" :tab="`卖出日 (${klineData.sell_date})`" v-if="klineData.sell_date" />
            </n-tabs>
          </div>
          <div ref="minChartRef" class="kline-chart"></div>
        </div>
      </n-spin>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup>
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { useTheme } from '@/composables/useTheme'
import { backtestApi } from '@/api/backtest'
import { NDrawer, NDrawerContent, NTag, NSpin, NDescriptions, NDescriptionsItem, NTabs, NTabPane } from 'naive-ui'

const props = defineProps({
  show: { type: Boolean, default: false },
  tradeId: { type: String, default: '' },
})
const emit = defineEmits(['update:show'])

const { isDark, colors, echartsTheme } = useTheme()

const loading = ref(false)
const error = ref('')
const klineData = ref(null)

const dailyChartRef = ref(null)
const minChartRef = ref(null)
const minChartTab = ref('buy')   // ← 5min 切换由 watch 接管

let dailyChart = null
let minChart = null              // ← 单一 chart 实例

const drawerWidth = computed(() => Math.min(window.innerWidth * 0.75, 900))

function onUpdateShow(v) {
  emit('update:show', v)
}

async function load() {
  if (!props.tradeId || !props.show) return
  loading.value = true
  error.value = ''
  klineData.value = null
  minChartTab.value = 'buy'      // 每次打开默认买入日
  try {
    klineData.value = await backtestApi.getTradeKLine(props.tradeId, 30)
    await nextTick()
    buildDailyChart()
    buildMinChart()              // 默认选中 'buy'
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

// ── 日K 图 ──
function buildDailyChart() {
  if (!dailyChartRef.value || !klineData.value) return
  if (dailyChart) dailyChart.dispose()

  const d = klineData.value
  dailyChart = echarts.init(dailyChartRef.value, echartsTheme.value)

  const ohlc = d.daily.map(bar => [bar.open, bar.close, bar.low, bar.high])
  const dates = d.daily.map(bar => {
    const dt = bar.date
    return dt.length === 8 ? `${dt.slice(0,4)}-${dt.slice(4,6)}-${dt.slice(6,8)}` : dt
  })

  const markPoints = []
  if (d.buy_marker_index >= 0 && d.buy_marker_index < dates.length) {
    markPoints.push({
      name: '买入', coord: [dates[d.buy_marker_index], d.buy_exec_price],
      value: `买 ${d.buy_exec_price.toFixed(2)}`,
      symbol: 'triangle', symbolSize: 14, symbolRotate: 180,
      itemStyle: { color: '#00C853' },
      label: { show: true, position: 'top', fontSize: 11 },
    })
  }
  if (d.sell_marker_index >= 0 && d.sell_marker_index < dates.length) {
    markPoints.push({
      name: '卖出', coord: [dates[d.sell_marker_index], d.sell_exec_price],
      value: `卖 ${d.sell_exec_price.toFixed(2)}`,
      symbol: 'triangle', symbolSize: 14,
      itemStyle: { color: '#FF1744' },
      label: { show: true, position: 'bottom', fontSize: 11 },
    })
  }

  dailyChart.setOption({
    title: { text: d.code, left: 'center', top: 4, textStyle: { fontSize: 13 } },
    tooltip: {
      trigger: 'axis',
      formatter: p => {
        if (!p || p.length === 0) return ''
        const item = p[0]
        const vals = item.data
        if (!Array.isArray(vals) || vals.length < 4) return `${item.axisValue}`
        return `${item.axisValue}<br/>开: ${vals[1].toFixed(2)} 收: ${vals[2].toFixed(2)}<br/>低: ${vals[3].toFixed(2)} 高: ${vals[4].toFixed(2)}`
      },
    },
    grid: { left: 60, right: 20, top: 40, bottom: 20 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: colors.value.border } } },
    series: [{
      type: 'candlestick', data: ohlc,
      markPoint: { data: markPoints, animation: false },
    }],
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 0 }],
  })
}

// ── 5min 图（单一 div + watch 切换重建） ──
function buildMinChart() {
  const refEl = minChartRef.value
  if (!refEl || !klineData.value) return
  if (minChart) minChart.dispose()

  const dayType = minChartTab.value
  const d = klineData.value
  const bars = dayType === 'sell' ? d.sell_5min : d.buy_5min
  if (!bars || bars.length === 0) return

  minChart = echarts.init(refEl, echartsTheme.value)

  const dates = bars.map(b => {
    const t = b.trade_time
    return t.length >= 16 ? t.slice(11, 16) : t
  })
  const ohlc = bars.map(b => [b.open, b.close, b.low, b.high])

  const triggerTime = dayType === 'sell'
    ? (d.sell_time?.length >= 16 ? d.sell_time.slice(11, 16) : '')
    : (d.buy_time?.length >= 16 ? d.buy_time.slice(11, 16) : '')

  const markLines = triggerTime ? [{
    name: dayType === 'sell' ? '止损' : '买入',
    xAxis: triggerTime,
    lineStyle: { color: dayType === 'sell' ? '#FF1744' : '#00C853', type: 'dashed', width: 2 },
    label: { show: true, formatter: dayType === 'sell' ? '止损' : '买入' },
  }] : []

  minChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 10, bottom: 20 },
    xAxis: { type: 'category', data: dates, axisLabel: { rotate: 45, fontSize: 9, interval: 9 } },
    yAxis: { type: 'value', scale: true },
    series: [{
      type: 'candlestick', data: ohlc,
      markLine: { silent: true, symbol: 'none', data: markLines },
    }],
    dataZoom: [{ type: 'inside' }],
  })
}

// ── 切换 5min tab → 重建图表 ──
watch(minChartTab, () => nextTick(buildMinChart))

// ── 主题切换 → 重建所有图表 ──
watch(echartsTheme, () => {
  if (dailyChart) nextTick(buildDailyChart)
  if (minChart) nextTick(buildMinChart)
})

// 打开弹窗 → 加载数据
watch(() => [props.show, props.tradeId], () => {
  if (props.show && props.tradeId) load()
})

onUnmounted(() => {
  dailyChart?.dispose()
  minChart?.dispose()
})
</script>

<style scoped>
.dwr-hdr { display: flex; align-items: center; gap: 12px; }
.chart-title { font-size: 13px; font-weight: 600; margin: 16px 0 8px; color: var(--n-text-color); }
.kline-chart { width: 100%; height: 320px; }
.err-msg { color: #FF1744; padding: 24px; text-align: center; }
</style>
