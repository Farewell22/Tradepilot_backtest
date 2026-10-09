/**
 * TradePilot 金融风格主题配置
 * 专业终端美学 - 深色主题、金色点缀、数据驱动
 */
import { darkTheme } from 'naive-ui'

export { darkTheme }

// 专业金融配色方案
const financialColors = {
  // 品牌色 - 金色系（象征价值与盈利）
  gold: {
    base: '#D4AF37',
    light: '#E5C158',
    dark: '#B8941F',
    bgSubtle: '#F5F0E0',        // 亮色：浅金悬浮底（按钮 hover）
    bgHover: '#EBE0BC',         // 亮色：按下/选中底
    gradient: 'linear-gradient(135deg, #D4AF37 0%, #F4E4A6 50%, #D4AF37 100%)'
  },
  // 涨跌色
  market: {
    up: '#00C853',      // 涨 - 绿
    upBg: 'rgba(0, 200, 83, 0.1)',
    down: '#FF1744',    // 跌 - 红
    downBg: 'rgba(255, 23, 68, 0.1)',
    flat: '#9E9E9E'
  },
  // 深色背景系
  dark: {
    background: '#0A0E17',      // 主背景 - 深夜蓝黑
    surface: '#141B2D',         // 卡片表面
    surfaceHover: '#1E2739',    // 悬浮状态
    border: '#2A3447',          // 边框
    divider: '#1F2937'          // 分割线
  },
  // 浅色背景系 - 象牙白系列（暖色低饱和，长时间观看舒适）
  light: {
    background: '#F8F5EE',      // 页面 - 象牙白
    surface: '#FCFAF5',         // 卡片 - 暖白
    surfaceRaised: '#FFFFFF',   // 浮起卡片
    surfaceHover: '#F3EFE5',    // 悬浮卡片
    surfaceSubtle: '#F5F0E0',   // 浅金悬浮（按钮）
    border: '#E5DDC8',          // 边框 - 米黄
    borderStrong: '#D4C9A8',    // 强边框
    divider: '#EDE7D4'          // 分割线
  },
  // 交互色
  interactive: {
    primary: '#2196F3',     // 主交互
    primaryHover: '#42A5F5',
    info: '#00BCD4',        // 信息
    warning: '#FF9800',     // 警告
    danger: '#F44336'       // 危险
  }
}

// 浅色主题覆盖 - 象牙白 + 金色品牌 + 蓝色交互
export const lightOverrides = {
  common: {
    primaryColor: financialColors.interactive.primary,
    primaryColorHover: financialColors.interactive.primaryHover,
    primaryColorPressed: '#1976D2',
    primaryColorSuppl: '#42A5F5',
    successColor: financialColors.market.up,
    warningColor: financialColors.interactive.warning,
    errorColor: financialColors.market.down,
    infoColor: financialColors.interactive.info,
    bodyColor: financialColors.light.background,
    cardColor: financialColors.light.surface,
    modalColor: financialColors.light.surface,
    popoverColor: financialColors.light.surface,
    tableColor: financialColors.light.surface,
    tableColorStriped: financialColors.light.background,
    inputColor: financialColors.light.surface,
    actionColor: financialColors.light.surfaceHover,
    hoverColor: financialColors.light.surfaceHover,
    textColorBase: '#1A202C',
    textColor1: '#1A202C',
    textColor2: '#4A5568',
    textColor3: '#718096',
    textColorDisabled: '#A0AEC0',
    placeholderColor: '#A0AEC0',
    iconColor: '#718096',
    iconColorHover: financialColors.gold.dark,
    dividerColor: financialColors.light.divider,
    borderColor: financialColors.light.border,
    borderRadius: '8px',
    fontSize: '14px',
    fontFamily: `'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
    monoFontFamily: `'JetBrains Mono', 'Roboto Mono', 'SF Mono', monospace`,
    boxShadow1: '0 1px 4px rgba(120, 95, 30, 0.06)',
    boxShadow2: '0 4px 12px rgba(120, 95, 30, 0.08)',
    boxShadow3: '0 8px 24px rgba(120, 95, 30, 0.10)'
  },
  Layout: {
    color: financialColors.light.background,
    siderColor: financialColors.light.surface,
    headerColor: financialColors.light.surface,
    textColor: '#1A202C',
    textColor1: '#1A202C',
    textColor2: '#4A5568',
    textColor3: '#718096',
    borderColor: financialColors.light.border
  },
  Card: {
    color: financialColors.light.surface,
    colorModal: financialColors.light.surface,
    colorEmbedded: financialColors.light.surfaceHover,
    borderColor: financialColors.light.border,
    titleTextColor: '#1A202C',
    textColor: '#4A5568'
  },
  Menu: {
    color: financialColors.light.surface,
    itemColorHover: financialColors.gold.bgSubtle,
    itemColorActive: financialColors.gold.bgHover,
    itemColorActiveHover: financialColors.gold.bgHover,
    itemTextColorHover: financialColors.gold.dark,
    itemTextColorActive: financialColors.gold.dark,
    itemTextColorActiveHover: financialColors.gold.dark,
    itemIconColorHover: financialColors.gold.dark,
    itemIconColorActive: financialColors.gold.dark,
    itemIconColorActiveHover: financialColors.gold.dark,
    borderColor: financialColors.light.border
  },
  Input: {
    color: financialColors.light.surface,
    colorFocus: financialColors.light.surface,
    border: '1px solid ' + financialColors.light.border,
    borderHover: '1px solid ' + financialColors.interactive.primary,
    borderFocus: '1px solid ' + financialColors.interactive.primary,
    boxShadowFocus: '0 0 0 2px rgba(33, 150, 243, 0.12)',
    textColor: '#1A202C',
    placeholderColor: '#A0AEC0'
  },
  Button: {
    // primary 按钮（蓝底白字）
    colorPrimary: financialColors.interactive.primary,
    colorPrimaryHover: financialColors.interactive.primaryHover,
    colorPrimaryPressed: '#1976D2',
    colorPrimaryFocus: financialColors.interactive.primaryHover,
    textColorPrimary: '#FFFFFF',
    textColorPrimaryHover: '#FFFFFF',
    textColorPrimaryPressed: '#FFFFFF',
    textColorPrimaryFocus: '#FFFFFF',
    borderPrimary: '1px solid ' + financialColors.interactive.primary,
    borderPrimaryHover: '1px solid ' + financialColors.interactive.primaryHover,
    borderPrimaryPressed: '1px solid #1976D2',
    borderPrimaryFocus: '1px solid ' + financialColors.interactive.primaryHover,
    // default / quaternary / tertiary（普通按钮）—— 修复白字 bug
    textColor: '#4A5568',
    textColorHover: '#1A202C',
    textColorPressed: financialColors.gold.dark,
    textColorFocus: '#1A202C',
    color: 'transparent',
    colorHover: financialColors.gold.bgSubtle,
    colorPressed: financialColors.gold.bgHover,
    colorFocus: financialColors.gold.bgSubtle,
    border: '1px solid ' + financialColors.light.border,
    borderHover: '1px solid ' + financialColors.gold.base,
    borderPressed: '1px solid ' + financialColors.gold.dark,
    borderFocus: '1px solid ' + financialColors.gold.base
  },
  DataTable: {
    thColor: financialColors.light.surfaceHover,
    thColorModal: financialColors.light.surfaceHover,
    thTextColor: '#4A5568',
    tdColor: financialColors.light.surface,
    tdColorModal: financialColors.light.surface,
    tdColorStriped: financialColors.light.background,
    tdColorStripedModal: financialColors.light.background,
    tdTextColor: '#1A202C',
    borderColor: financialColors.light.border,
    borderColorModal: financialColors.light.border
  },
  Tag: {
    color: financialColors.light.surfaceHover,
    textColor: '#4A5568',
    border: '1px solid ' + financialColors.light.border,
    colorCheckable: financialColors.light.surfaceHover,
    textColorCheckable: '#4A5568',
    colorChecked: financialColors.gold.base,
    colorCheckedHover: financialColors.gold.light,
    textColorChecked: '#1A202C'
  },
  Tabs: {
    tabTextColor: '#4A5568',
    tabTextColorActive: financialColors.gold.dark,
    tabTextColorHover: '#1A202C',
    barColor: financialColors.gold.base
  },
  Modal: {
    color: financialColors.light.surface
  },
  Dropdown: {
    color: financialColors.light.surface,
    optionColorHover: financialColors.gold.bgSubtle,
    optionTextColor: '#1A202C',
    optionTextColorHover: financialColors.gold.dark
  },
  Select: {
    peers: {
      InternalSelection: {
        color: financialColors.light.surface,
        border: '1px solid ' + financialColors.light.border,
        borderHover: '1px solid ' + financialColors.interactive.primary,
        borderActive: '1px solid ' + financialColors.interactive.primary,
        borderFocus: '1px solid ' + financialColors.interactive.primary
      }
    }
  },
  Scrollbar: {
    color: '#D4C9A8',
    colorHover: '#B8A878'
  },
  Switch: {
    railColorActive: financialColors.interactive.primary
  },
  Divider: {
    color: financialColors.light.divider
  }
}

// 深色主题覆盖 - 专业金融终端风格
export const darkOverrides = {
  common: {
    primaryColor: financialColors.gold.base,
    primaryColorHover: financialColors.gold.light,
    primaryColorPressed: financialColors.gold.dark,
    primaryColorSuppl: financialColors.gold.light,
    successColor: financialColors.market.up,
    warningColor: financialColors.interactive.warning,
    errorColor: financialColors.market.down,
    infoColor: financialColors.interactive.info,
    borderRadius: '8px',
    fontSize: '14px',
    fontFamily: `'Noto Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
    monoFontFamily: `'JetBrains Mono', 'Roboto Mono', 'SF Mono', monospace`
  },
  Layout: {
    color: financialColors.dark.background,
    siderColor: '#0F141F',
    headerColor: '#0F141F',
    textColor: '#E8EDF3',
    textColor1: '#E8EDF3',
    textColor2: '#B0B8C4',
    textColor3: '#7A8494',
    borderColor: financialColors.dark.border
  },
  Card: {
    color: financialColors.dark.surface,
    colorModal: financialColors.dark.surface,
    borderColor: financialColors.dark.border
  },
  Menu: {
    color: '#0F141F',
    itemColorHover: financialColors.dark.surfaceHover,
    itemIconColorHover: financialColors.gold.base,
    itemTextColorHover: financialColors.gold.base
  },
  Input: {
    color: financialColors.dark.surface,
    border: '1px solid ' + financialColors.dark.border,
    borderHover: '1px solid ' + financialColors.gold.base,
    borderFocus: '1px solid ' + financialColors.gold.base,
    colorFocus: '#1A2332',
    caretColor: '#E8EDF3',
    boxShadowFocus: '0 0 0 2px rgba(212, 175, 55, 0.15)',
    textColor: '#E8EDF3',
    placeholderColor: '#7A8494'
  },
  Button: {
    textColor: '#B0B8C4',
    textColorHover: '#D4AF37',
    textColorPressed: '#B8941F',
    textColorFocus: '#D4AF37',
    textColorPrimary: '#0A0E17',
    textColorPrimaryHover: '#0A0E17',
    textColorPrimaryPressed: '#0A0E17',
    textColorPrimaryFocus: '#0A0E17',
    colorPrimary: financialColors.gold.base,
    colorPrimaryHover: financialColors.gold.light,
    colorPrimaryPressed: financialColors.gold.dark
  },
  DataTable: {
    thColor: financialColors.dark.surface,
    thColorModal: financialColors.dark.surface,
    thTextColor: '#B0B8C4',
    tdColor: financialColors.dark.background,
    tdColorModal: financialColors.dark.background,
    tdColorStriped: financialColors.dark.surface,
    borderColor: financialColors.dark.border,
    thFontWeight: '600'
  },
  Progress: {
    textColorCard: financialColors.gold.base
  },
  Tag: {
    colorCheckable: financialColors.gold.base
  },
  Switch: {
    railColorActive: financialColors.gold.base
  },
  Select: {
    peers: '[data-n-id="n-menu"] { background: #141B2D !important; border: 1px solid #2A3447 !important; }'
  },
  Dropdown: {
    optionColorHover: financialColors.dark.surfaceHover
  },
  Modal: {
    color: financialColors.dark.surface
  }
}

// 导出颜色常量供组件使用
export const colors = financialColors

// 专用渐变效果
export const gradients = {
  gold: financialColors.gold.gradient,
  success: 'linear-gradient(135deg, #00C853 0%, #69F0AE 100%)',
  danger: 'linear-gradient(135deg, #FF1744 0%, #FF5252 100%)',
  dark: 'linear-gradient(180deg, #141B2D 0%, #0A0E17 100%)',
  card: 'linear-gradient(145deg, #1A2332 0%, #141B2D 100%)',
  glow: 'radial-gradient(ellipse at center, rgba(212, 175, 55, 0.08) 0%, transparent 70%)'
}

// 动画配置
export const animations = {
  duration: {
    fast: 150,
    base: 250,
    slow: 350
  },
  easing: {
    default: 'cubic-bezier(0.4, 0, 0.2, 1)',
    smooth: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)'
  }
}

// 阴影效果
export const shadows = {
  subtle: '0 2px 8px rgba(0, 0, 0, 0.3)',
  medium: '0 4px 16px rgba(0, 0, 0, 0.4)',
  large: '0 8px 32px rgba(0, 0, 0, 0.5)',
  glow: '0 0 20px rgba(212, 175, 55, 0.3)',
  glowSubtle: '0 0 12px rgba(212, 175, 55, 0.15)'
}
