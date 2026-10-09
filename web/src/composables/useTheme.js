import { computed, ref, watch } from 'vue'

const STORAGE_KEY = 'tradepilot-theme'
const _isDark = ref(false)

function applyHtmlClass(dark) {
  if (typeof document === 'undefined') return
  const html = document.documentElement
  if (dark) html.classList.add('dark')
  else html.classList.remove('dark')
}

if (typeof window !== 'undefined') {
  const saved = localStorage.getItem(STORAGE_KEY)
  _isDark.value = saved === 'dark'
  applyHtmlClass(_isDark.value)
}

watch(_isDark, (v) => {
  if (typeof window !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, v ? 'dark' : 'light')
  }
  applyHtmlClass(v)
})

export function useTheme() {
  const isDark = computed(() => _isDark.value)

  const colors = computed(() => isDark.value ? {
    background: '#0A0E17',
    surface: '#141B2D',
    surfaceRaised: '#1A2332',
    surfaceHover: '#1E2739',
    border: '#2A3447',
    text: '#E8EDF3',
    textSecondary: '#B0B8C4',
    textMuted: '#7A8494',
    accent: '#D4AF37',
    accentBrand: '#D4AF37',
    accentLink: '#42A5F5',
  } : {
    background: '#F8F5EE',
    surface: '#FCFAF5',
    surfaceRaised: '#FFFFFF',
    surfaceHover: '#F3EFE5',
    border: '#E5DDC8',
    text: '#1A202C',
    textSecondary: '#4A5568',
    textMuted: '#718096',
    accent: '#2196F3',
    accentBrand: '#B8941F',
    accentLink: '#2196F3',
  })

  const echartsTheme = computed(() => isDark.value ? 'dark' : 'tradepilot-light')

  function setDark(v) { _isDark.value = v }
  function toggle() { _isDark.value = !_isDark.value }

  return { isDark, colors, echartsTheme, setDark, toggle }
}
