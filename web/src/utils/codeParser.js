/**
 * Parse stock codes from user input text.
 * Supports formats:
 *   000423
 *   000423 东阿阿胶
 *   000423  东阿阿胶  (multiple spaces)
 *
 * @param {string} text - multiline input
 * @returns {Array<{code: string, name: string}>}
 */
export function parseStockCodes(text) {
  const lines = text.split('\n').filter(l => l.trim())
  const map = new Map()
  for (const line of lines) {
    const parts = line.trim().split(/\s+/)
    const code = parts[0]
    if (!/^\d{6}$/.test(code)) continue
    const name = parts.slice(1).join(' ') || ''
    if (!map.has(code)) map.set(code, name)
  }
  return Array.from(map, ([code, name]) => ({ code, name }))
}
