// Copyright NGGT.LightKeeper. All Rights Reserved.

import { escHtml, percent } from './common.js';

// Chart.js.
// Read a theme color from the CSS variables, so the charts follow the light and dark themes.
export function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Draw a Chart.js chart on the canvas, replacing the previous one.
export function renderChart(canvas, config) {
  const previous = Chart.getChart(canvas);
  if (previous) {
    previous.destroy();
  }
  Chart.defaults.color = themeColor('--c-text-muted');
  Chart.defaults.borderColor = themeColor('--c-border');
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  return new Chart(canvas, config);
}


// HTML charts.
// Horizontal bars: items are {label, count, percent}.
export function barsHtml(items) {
  const max = Math.max(1, ...items.map(function count(item) {
    return item.count;
  }));
  return `<div class="bar-list">${items.map(function barItem(item) {
    return `
      <div>
        <div class="bar-item-head"><span>${escHtml(item.label)}</span><span>${item.count} · ${percent(item.percent)}</span></div>
        <div class="progress"><div class="progress-bar" style="width:${(item.count / max) * 100}%"></div></div>
      </div>`;
  }).join('')}</div>`;
}

// Columns of a scale distribution; eNPS columns get the colors of their groups.
export function histogramHtml(distribution, isEnps) {
  const max = Math.max(1, ...distribution.map(function count(item) {
    return item.count;
  }));
  return `<div class="histogram">${distribution.map(function column(item) {
    let group = '';
    if (isEnps) {
      group = item.value <= 6 ? 'detractor' : item.value <= 8 ? 'passive' : 'promoter';
    }
    const height = item.count ? Math.max(4, (item.count / max) * 100) : 0;
    return `
      <div class="histogram-col" title="${item.value}: ${item.count}">
        <span>${item.count || ''}</span>
        <div class="histogram-bar ${group}" style="height:${height}%"></div>
        <span>${item.value}</span>
      </div>`;
  }).join('')}</div>`;
}

// Split bar of promoters, passives and detractors with its legend.
export function enpsSplitHtml(summary) {
  const total = Math.max(1, summary.total);
  const parts = [
    ['--c-success', summary.promoters, 'Промоутеры (9–10)'],
    ['--c-neutral', summary.passives, 'Нейтралы (7–8)'],
    ['--c-danger', summary.detractors, 'Критики (0–6)']
  ];
  return `
    <div class="enps-split">${parts.map(function part(item) {
      return `<span style="width:${(item[1] / total) * 100}%;background:var(${item[0]})"></span>`;
    }).join('')}</div>
    <div class="enps-legend">${parts.map(function legend(item) {
      return `<span><span class="dot" style="background:var(${item[0]})"></span>${item[2]}: ${item[1]}</span>`;
    }).join('')}</div>`;
}

// Return the CSS class of an eNPS score: good above 30, bad below 0.
export function enpsClass(score) {
  if (score === null || score === undefined) {
    return '';
  }
  return score >= 30 ? 'kpi-good' : score < 0 ? 'kpi-bad' : '';
}
