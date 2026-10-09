export const echartsLightTheme = {
  color: ['#2196F3', '#FF9800', '#9C27B0', '#00BCD4', '#4CAF50', '#FF5722'],
  backgroundColor: 'transparent',
  textStyle: { color: '#1A202C' },
  title: {
    textStyle: { color: '#1A202C' },
    subtextStyle: { color: '#718096' },
  },
  line: {
    itemStyle: { borderWidth: 1 },
    lineStyle: { width: 2 },
    symbolSize: 4,
  },
  candlestick: {
    itemStyle: {
      color: '#FF1744',
      color0: '#00C853',
      borderColor: '#FF1744',
      borderColor0: '#00C853',
    },
  },
  categoryAxis: {
    axisLine: { show: true, lineStyle: { color: '#E5DDC8' } },
    axisTick: { show: false },
    axisLabel: { color: '#718096' },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#718096' },
    splitLine: { lineStyle: { color: '#EDE7D4' } },
  },
  tooltip: {
    backgroundColor: 'rgba(252, 250, 245, 0.95)',
    borderColor: '#E5DDC8',
    textStyle: { color: '#1A202C' },
    extraCssText: 'box-shadow: 0 4px 12px rgba(120, 95, 30, 0.08);',
  },
  legend: {
    textStyle: { color: '#4A5568' },
  },
  dataZoom: {
    backgroundColor: '#F3EFE5',
    dataBackgroundColor: 'rgba(33, 150, 243, 0.08)',
    fillerColor: 'rgba(33, 150, 243, 0.12)',
    handleColor: '#2196F3',
    handleSize: '100%',
    textStyle: { color: '#718096' },
  },
}
