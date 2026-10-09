<template>
  <n-config-provider :theme="isDark ? darkTheme : null" :theme-overrides="isDark ? darkOverrides : lightOverrides">
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <n-loading-bar-provider>
            <MainLayout />
          </n-loading-bar-provider>
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { darkTheme, lightOverrides, darkOverrides, colors, gradients } from '@/theme'
import { useTheme } from '@/composables/useTheme'
import MainLayout from '@/layouts/MainLayout.vue'

const { isDark } = useTheme()

if (typeof window !== 'undefined') {
  window.__TRADEPILOT_THEME__ = { colors, gradients }
}
</script>

<style>
:root {
  --color-gold: #D4AF37;
  --color-gold-light: #E5C158;
  --color-gold-dark: #B8941F;
  --color-up: #00C853;
  --color-down: #FF1744;

  --bg-primary: #F8F5EE;
  --bg-surface: #FCFAF5;
  --bg-surface-raised: #FFFFFF;
  --bg-surface-hover: #F3EFE5;
  --bg-surface-subtle: #F5F0E0;
  --bg-sider: #FCFAF5;
  --bg-header: #FCFAF5;

  --border-primary: #E5DDC8;
  --border-strong: #D4C9A8;

  --text-primary: #1A202C;
  --text-secondary: #4A5568;
  --text-muted: #718096;
  --text-label: #374151;

  --accent-primary: #2196F3;
  --accent-link: #2196F3;
  --accent-brand: #B8941F;

  --text-gold: #B8941F;
  --gold-gradient: linear-gradient(135deg, #D4AF37 0%, #E5C158 100%);
  --glass-bg: rgba(252, 250, 245, 0.85);
  --glass-border: rgba(184, 148, 31, 0.12);
  --card-gradient: linear-gradient(145deg, #FCFAF5 0%, #F8F5EE 100%);
  --shadow-subtle: 0 2px 8px rgba(120, 95, 30, 0.06);
  --shadow-medium: 0 4px 16px rgba(120, 95, 30, 0.08);
  --scrollbar-thumb: #D4C9A8;
  --scrollbar-hover: #B8A878;
  --gold-glow: rgba(212, 175, 55, 0.15);
  --accent-border: rgba(33, 150, 243, 0.25);
  --table-header-bg: #F3EFE5;
  --table-border: rgba(120, 95, 30, 0.10);
  --table-border-strong: rgba(120, 95, 30, 0.18);
}

html.dark {
  --bg-primary: #0A0E17;
  --bg-surface: #141B2D;
  --bg-surface-raised: #1A2332;
  --bg-surface-hover: #1E2739;
  --bg-surface-subtle: #1E2739;
  --bg-sider: #0F141F;
  --bg-header: #0F141F;

  --border-primary: #2A3447;
  --border-strong: #3A4457;

  --text-primary: #E8EDF3;
  --text-secondary: #B0B8C4;
  --text-muted: #7A8494;
  --text-label: #A8B2C2;

  --accent-primary: #D4AF37;
  --accent-link: #42A5F5;
  --accent-brand: #D4AF37;

  --text-gold: #D4AF37;
  --gold-gradient: linear-gradient(135deg, #D4AF37 0%, #F4E4A6 100%);
  --glass-bg: rgba(20, 27, 45, 0.8);
  --glass-border: rgba(255, 255, 255, 0.05);
  --card-gradient: linear-gradient(145deg, #1A2332 0%, #141B2D 100%);
  --shadow-subtle: 0 2px 8px rgba(0, 0, 0, 0.3);
  --shadow-medium: 0 4px 16px rgba(0, 0, 0, 0.4);
  --scrollbar-thumb: #2A3447;
  --scrollbar-hover: #3A4457;
  --gold-glow: rgba(212, 175, 55, 0.15);
  --accent-border: rgba(212, 175, 55, 0.3);
  --table-header-bg: #141B2D;
  --table-border: rgba(255, 255, 255, 0.08);
  --table-border-strong: rgba(255, 255, 255, 0.15);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  transition: background-color 0.2s ease, color 0.2s ease;
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-hover); }

.font-mono { font-family: 'JetBrains Mono', 'Roboto Mono', 'SF Mono', monospace; }
.text-up { color: var(--color-up); }
.text-down { color: var(--color-down); }
.bg-up { background-color: var(--color-up); }
.bg-down { background-color: var(--color-down); }
.text-gold { color: var(--text-gold); }

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in { animation: fadeIn 0.3s ease-out; }
.animate-slide-up { animation: slideUp 0.4s ease-out; }

.glass {
  background: var(--glass-bg);
  backdrop-filter: blur(10px);
  border: 1px solid var(--glass-border);
}

.data-card {
  background: var(--card-gradient);
  border: 1px solid var(--border-primary);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.3s ease;
}
.data-card:hover {
  border-color: var(--accent-primary);
  box-shadow: 0 0 20px var(--gold-glow);
}
</style>
