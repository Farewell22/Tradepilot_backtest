import { ref, computed } from 'vue'

/**
 * 通用表格筛选 composable（搜索 + 分数阈值）
 *
 * 列筛选由 Naive UI DataTable 原生处理（onFilter + filterOptions），
 * 本 composable 只负责搜索文本和分数阈值过滤。
 *
 * @param {Ref<Array>|ComputedRef<Array>} data - 原始数据源
 * @param {Object} options
 * @param {string[]} options.searchKeys - 搜索匹配的字段列表
 * @param {boolean} [options.enableScoreFilter=false] - 是否启用分数阈值筛选
 */
export function useTableFilter(data, options = {}) {
  const { searchKeys = [], enableScoreFilter = false } = options

  const searchQuery = ref('')
  const scoreThreshold = ref(0)

  const hasActiveFilters = computed(() =>
    !!searchQuery.value.trim() || (enableScoreFilter && scoreThreshold.value > 0)
  )

  const resetAllFilters = () => {
    searchQuery.value = ''
    scoreThreshold.value = 0
  }

  const filteredData = computed(() => {
    let result = data.value || []

    const q = searchQuery.value.trim().toLowerCase()
    if (q && searchKeys.length) {
      result = result.filter(row =>
        searchKeys.some(key => (row[key] || '').toString().toLowerCase().includes(q))
      )
    }

    if (enableScoreFilter && scoreThreshold.value > 0) {
      result = result.filter(row => (row.total || 0) >= scoreThreshold.value)
    }

    return result
  })

  return { searchQuery, scoreThreshold, hasActiveFilters, filteredData, resetAllFilters }
}
