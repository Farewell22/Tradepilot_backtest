/**
 * 格式化相对时间
 * @param {string} isoString - ISO 8601 日期字符串
 * @returns {string} 相对时间文本
 * - 1小时内: "X分钟前"
 * - 今天: "X小时前"
 * - 昨天: "昨天 HH:mm"
 * - 更早: "MM-DD HH:mm"
 */
export function formatRelativeTime(isoString) {
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)

  // 判断是否为今天
  const isToday = date.toDateString() === now.toDateString()

  // 判断是否为昨天
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  const isYesterday = date.toDateString() === yesterday.toDateString()

  // 1小时内
  if (diffMins < 60) {
    return `${diffMins}分钟前`
  }

  // 今天但超过1小时
  if (isToday) {
    return `${diffHours}小时前`
  }

  // 昨天
  if (isYesterday) {
    const hours = date.getHours().toString().padStart(2, '0')
    const mins = date.getMinutes().toString().padStart(2, '0')
    return `昨天 ${hours}:${mins}`
  }

  // 更早：MM-DD HH:mm
  const month = (date.getMonth() + 1).toString().padStart(2, '0')
  const day = date.getDate().toString().padStart(2, '0')
  const hours = date.getHours().toString().padStart(2, '0')
  const mins = date.getMinutes().toString().padStart(2, '0')
  return `${month}-${day} ${hours}:${mins}`
}

/**
 * 获取完整日期文本（用于 title 属性）
 * @param {string} isoString - ISO 8601 日期字符串
 * @returns {string} 完整日期文本
 */
export function formatFullTime(isoString) {
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}
