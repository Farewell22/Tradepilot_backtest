<template>
  <div class="config-editor">
    <n-tabs type="line" default-value="form">
      <n-tab-pane name="form" tab="参数配置">
        <n-space vertical :size="20">
          <!-- Data Source -->
          <n-card title="数据源" size="small" :bordered="false" class="config-section">
            <n-radio-group
              :value="getNested('data_source.type') || 'tencent'"
              @update:value="(v) => setNested('data_source.type', v)">
              <n-radio-button value="tencent">腾讯行情</n-radio-button>
              <n-radio-button value="tushare">Tushare</n-radio-button>
            </n-radio-group>
          </n-card>

          <!-- Score Weights -->
          <n-card title="评分权重" size="small" :bordered="false" class="config-section">
            <n-grid :cols="3" :x-gap="16" :y-gap="12">
              <n-gi v-for="field in weightFields" :key="field.key">
                <n-input-number
                  :value="getNested(field.key)"
                  :placeholder="field.label"
                  :precision="1"
                  :step="0.5"
                  :min="0"
                  :max="100"
                  @update:value="(v) => setNested(field.key, v)"
                  style="width: 100%"
                >
                  <template #prefix>{{ field.label }}</template>
                </n-input-number>
              </n-gi>
            </n-grid>
          </n-card>

          <!-- Thresholds -->
          <n-card title="判定阈值" size="small" :bordered="false" class="config-section">
            <n-grid :cols="2" :x-gap="16" :y-gap="12">
              <n-gi v-for="field in thresholdFields" :key="field.key">
                <n-input-number
                  :value="getNested(field.key)"
                  :placeholder="field.label"
                  :precision="1"
                  :step="1"
                  :min="0"
                  :max="100"
                  @update:value="(v) => setNested(field.key, v)"
                  style="width: 100%"
                >
                  <template #prefix>{{ field.label }}</template>
                </n-input-number>
              </n-gi>
            </n-grid>
          </n-card>

          <!-- N-Type Params -->
          <n-card title="N型参数" size="small" :bordered="false" class="config-section">
            <n-grid :cols="3" :x-gap="16" :y-gap="12">
              <n-gi v-for="field in ntypeFields" :key="field.key">
                <n-input-number
                  :value="getNested(field.key)"
                  :placeholder="field.label"
                  :precision="field.precision ?? 0"
                  :step="field.step ?? 1"
                  :min="0"
                  @update:value="(v) => setNested(field.key, v)"
                  style="width: 100%"
                >
                  <template #prefix>{{ field.label }}</template>
                </n-input-number>
              </n-gi>
            </n-grid>
          </n-card>

          <!-- Timing Filters -->
          <n-card title="择时过滤器" size="small" :bordered="false" class="config-section">
            <n-space vertical :size="12">
              <n-space>
                <n-switch
                  :value="getNested('timing.enabled') ?? true"
                  @update:value="(v) => setNested('timing.enabled', v)"
                >
                  <template #checked>择时总开关：开</template>
                  <template #unchecked>择时总开关：关</template>
                </n-switch>
                <n-switch
                  :value="getNested('timing.volume_pattern_enabled') ?? false"
                  @update:value="(v) => setNested('timing.volume_pattern_enabled', v)"
                >
                  <template #checked>绿肥红瘦：开</template>
                  <template #unchecked>绿肥红瘦：关</template>
                </n-switch>
                <n-switch
                  :value="getNested('timing.anti_s1_enabled') ?? false"
                  @update:value="(v) => setNested('timing.anti_s1_enabled', v)"
                >
                  <template #checked>防S1：开</template>
                  <template #unchecked>防S1：关</template>
                </n-switch>
              </n-space>
              <n-grid :cols="3" :x-gap="16" :y-gap="12">
                <n-gi v-for="field in timingFields" :key="field.key">
                  <n-input-number
                    :value="getNested(field.key)"
                    :placeholder="field.label"
                    :precision="field.precision ?? 0"
                    :step="field.step ?? 1"
                    :min="field.min ?? 0"
                    :max="field.max"
                    @update:value="(v) => setNested(field.key, v)"
                    style="width: 100%"
                  >
                    <template #prefix>{{ field.label }}</template>
                  </n-input-number>
                </n-gi>
              </n-grid>
            </n-space>
          </n-card>

          <n-space justify="end">
            <n-button @click="emit('reset')">重置为默认</n-button>
            <n-button @click="emit('restore')">从备份恢复</n-button>
            <n-button type="primary" @click="emit('save', localConfig)">保存配置</n-button>
          </n-space>
        </n-space>
      </n-tab-pane>

      <n-tab-pane name="raw" tab="原始 JSON">
        <n-input
          v-model:value="rawJSON"
          type="textarea"
          :rows="20"
          :input-props="{ style: 'font-family: monospace; font-size: 13px;' }"
        />
        <n-space justify="end" style="margin-top: 16px">
          <n-button @click="parseRawJSON">应用</n-button>
          <n-button type="primary" @click="emit('save', localConfig)">保存配置</n-button>
        </n-space>
      </n-tab-pane>
    </n-tabs>

    <!-- Backups restore modal -->
    <n-modal v-model:show="showBackups" preset="card" title="备份恢复" style="width: 560px">
      <n-data-table
        :columns="backupColumns"
        :data="backups"
        :pagination="{ pageSize: 5 }"
        size="small"
        :bordered="false"
      />
    </n-modal>
  </div>
</template>

<script setup>
import { h, ref, watch } from 'vue'
import { NButton, NSpace, NSwitch } from 'naive-ui'

const props = defineProps({
  config: { type: Object, default: () => ({}) },
  backups: { type: Array, default: () => [] }
})

const emit = defineEmits(['save', 'reset', 'restore', 'restore-backup'])

const localConfig = ref({})
const rawJSON = ref('{}')
const showBackups = ref(false)

watch(() => props.config, (val) => {
  localConfig.value = JSON.parse(JSON.stringify(val || {}))
  rawJSON.value = JSON.stringify(val || {}, null, 2)
}, { immediate: true, deep: true })

function getNested(key) {
  const parts = key.split('.')
  let obj = localConfig.value
  for (const p of parts) {
    if (obj == null) return undefined
    obj = obj[p]
  }
  return obj
}

function setNested(key, val) {
  const parts = key.split('.')
  let obj = localConfig.value
  for (let i = 0; i < parts.length - 1; i++) {
    if (!obj[parts[i]]) obj[parts[i]] = {}
    obj = obj[parts[i]]
  }
  obj[parts[parts.length - 1]] = val
  updateRaw()
}

function updateRaw() {
  rawJSON.value = JSON.stringify(localConfig.value, null, 2)
}

function parseRawJSON() {
  try {
    localConfig.value = JSON.parse(rawJSON.value)
  } catch {
    // ignore parse errors
  }
}

const weightFields = [
  { key: 'weights.trend', label: '趋势' },
  { key: 'weights.volume', label: '量能' },
  { key: 'weights.position', label: '位置' },
  { key: 'weights.abnormal', label: '异常' },
  { key: 'weights.n_type', label: 'N型' },
  { key: 'weights.chart_perfect', label: '形态完美' },
  { key: 'weights.rr', label: '盈亏比' },
  { key: 'weights.kdj', label: 'KDJ' }
]

const thresholdFields = [
  { key: 'thresholds.pass', label: 'PASS 阈值' },
  { key: 'thresholds.watch', label: 'WATCH 阈值' }
]

const ntypeFields = [
  { key: 'ntype.ma_short', label: '短期均线', precision: 0 },
  { key: 'ntype.ma_long', label: '长期均线', precision: 0 },
  { key: 'ntype.volume_ratio', label: '量比阈值', precision: 1, step: 0.1 },
  { key: 'ntype.max_position_pct', label: '最大位置%', precision: 0 },
  { key: 'ntype.min_volume_days', label: '最小缩量天数', precision: 0 },
  { key: 'ntype.max_volume_days', label: '最大缩量天数', precision: 0 }
]

const timingFields = [
  { key: 'timing.volume_pattern_window', label: '绿肥红瘦窗口(天)', precision: 0, step: 5, min: 5, max: 200 },
  { key: 'timing.volume_pattern_threshold', label: '阴量/阳量阈值', precision: 2, step: 0.05, min: 0, max: 2 },
  { key: 'timing.anti_s1_window', label: '防S1窗口(天)', precision: 0, step: 5, min: 5, max: 200 }
]

const backupColumns = [
  { title: '文件名', key: 'name', ellipsis: { tooltip: true } },
  { title: '大小', key: 'size', width: 80 },
  { title: '修改时间', key: 'modified', width: 160 },
  {
    title: '操作', key: 'actions', width: 100,
    render: (row) => {
      return h(NButton, {
        size: 'small', quaternary: true, type: 'primary',
        onClick: () => emit('restore-backup', row.path)
      }, { default: () => '恢复' })
    }
  }
]
</script>

<style scoped>
.config-editor {
  max-width: 900px;
}
.config-section {
  margin-bottom: 8px;
  border: 1px solid var(--border-primary);
  background: var(--card-gradient);
}
</style>
