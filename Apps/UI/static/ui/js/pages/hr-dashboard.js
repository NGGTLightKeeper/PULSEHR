// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson } from '../api.js';
import { escHtml, formatDate, percent, toastError } from '../common.js';
import { enpsClass, renderChart, themeColor } from '../charts.js';

// Targets of the hackathon KPI, in percent.
const PUSH_RESPONSE_TARGET = 50;
const PUSH_COVERAGE_TARGET = 60;

// HR dashboard.
// KPI tiles, the eNPS trend, the departments of the latest eNPS survey and the channel funnel.
$(function initDashboardPage() {
  function kpiTile(label, value, note, valueClass) {
    return `
      <section class="card kpi">
        <span class="kpi-label">${label}</span>
        <span class="kpi-value ${valueClass || ''}">${value}</span>
        <span class="kpi-note">${note}</span>
      </section>`;
  }

  // Show a value against its target: green when reached.
  function targetNote(rate, target, details) {
    const reached = rate !== null && rate >= target;
    const mark = rate === null ? '' : reached ? '<span class="target-note kpi-good">цель достигнута</span>' : '<span class="target-note kpi-bad">ниже цели</span>';
    return `${details} · цель ≥ ${target}% ${mark}`;
  }

  function renderKpis(data) {
    const enps = data.enps;
    const pushResponse = data.push_response;
    const coverage = data.push_coverage;
    $('#kpis').html([
      kpiTile(
        'eNPS',
        enps ? (enps.score > 0 ? `+${enps.score}` : enps.score) : '—',
        enps ? `${escHtml(enps.title)} · ${enps.responses} отв.` : 'Нет опросов с eNPS',
        enps ? enpsClass(enps.score) : ''
      ),
      kpiTile(
        'Отклик на опросы',
        percent(data.participation.rate),
        `${data.participation.completed} из ${data.participation.invited} приглашённых`
      ),
      kpiTile(
        'Ответ ≤ 24 ч после push',
        percent(pushResponse.rate),
        targetNote(pushResponse.rate, PUSH_RESPONSE_TARGET, `${pushResponse.responded} из ${pushResponse.notified}`),
        pushResponse.rate !== null && pushResponse.rate >= PUSH_RESPONSE_TARGET ? 'kpi-good' : ''
      ),
      kpiTile(
        'Сотрудники с Web Push',
        percent(coverage.rate),
        targetNote(coverage.rate, PUSH_COVERAGE_TARGET, `${coverage.with_push} из ${coverage.users}`),
        coverage.rate !== null && coverage.rate >= PUSH_COVERAGE_TARGET ? 'kpi-good' : ''
      )
    ].join(''));
  }

  function renderTrend(trend) {
    const points = trend.filter(function hasScore(item) {
      return item.score !== null;
    });
    $('#trendEmpty').toggleClass('hidden', points.length > 0);
    $('#trendChart').parent().toggleClass('hidden', points.length === 0);
    if (!points.length) {
      return;
    }
    renderChart($('#trendChart')[0], {
      type: 'line',
      data: {
        labels: points.map(function label(item) {
          return item.date ? formatDate(item.date) : item.title;
        }),
        datasets: [{
          label: 'eNPS',
          data: points.map(function score(item) {
            return item.score;
          }),
          borderColor: themeColor('--c-accent'),
          backgroundColor: themeColor('--c-accent-soft'),
          fill: true,
          tension: 0.3,
          pointRadius: 5
        }]
      },
      options: {
        maintainAspectRatio: false,
        scales: { y: { suggestedMin: -100, suggestedMax: 100 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function tooltipTitle(items) {
                return points[items[0].dataIndex].title;
              }
            }
          }
        }
      }
    });
  }

  function renderDepartments(departments, latest) {
    const rows = departments.filter(function visible(row) {
      return !row.hidden && row.enps && row.enps.score !== null;
    });
    $('#departmentsSurvey').text(latest ? latest.title : '');
    $('#departmentsEmpty').toggleClass('hidden', rows.length > 0);
    $('#departmentsChart').parent().toggleClass('hidden', rows.length === 0);
    if (!rows.length) {
      return;
    }
    renderChart($('#departmentsChart')[0], {
      type: 'bar',
      data: {
        labels: rows.map(function name(row) {
          return row.name;
        }),
        datasets: [{
          label: 'eNPS',
          data: rows.map(function score(row) {
            return row.enps.score;
          }),
          backgroundColor: rows.map(function color(row) {
            return row.enps.score >= 0 ? themeColor('--c-success') : themeColor('--c-danger');
          }),
          borderRadius: 6
        }]
      },
      options: {
        indexAxis: 'y',
        maintainAspectRatio: false,
        scales: { x: { suggestedMin: -100, suggestedMax: 100 } },
        plugins: { legend: { display: false } }
      }
    });
  }

  function renderChannels(channels) {
    renderChart($('#channelsChart')[0], {
      type: 'bar',
      data: {
        labels: channels.map(function label(item) {
          return item.label;
        }),
        datasets: [
          { label: 'Отправлено', data: channels.map((item) => item.sent), backgroundColor: themeColor('--c-neutral'), borderRadius: 6 },
          { label: 'Открыли', data: channels.map((item) => item.clicked), backgroundColor: themeColor('--c-info'), borderRadius: 6 },
          { label: 'Прошли опрос', data: channels.map((item) => item.completed), backgroundColor: themeColor('--c-accent'), borderRadius: 6 }
        ]
      },
      options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }
    });
  }

  function renderActiveSurveys(items) {
    $('#activeSurveys').html(items.length
      ? items.map(function surveyRow(item) {
        return `
          <div class="feedback-item">
            <div class="row-between">
              <a href="/hr/surveys/${item.id}/"><strong>${escHtml(item.title)}</strong></a>
              <span class="muted small">${item.completed} / ${item.invited} · ${percent(item.rate)}</span>
            </div>
            <div class="progress" style="margin-top:8px"><div class="progress-bar" style="width:${item.rate || 0}%"></div></div>
            ${item.ends_at ? `<div class="muted small" style="margin-top:6px">до ${formatDate(item.ends_at)}</div>` : ''}
          </div>`;
      }).join('')
      : '<div class="empty">Нет идущих опросов. <a href="/hr/surveys/">Создать опрос</a></div>');
  }

  async function load() {
    try {
      const data = await getJson('/api/v1/hr/dashboard/');
      renderKpis(data);
      renderTrend(data.enps_trend);
      renderDepartments(data.departments, data.enps);
      renderChannels(data.channels);
      renderActiveSurveys(data.active_surveys);
      $('#feedbackNew').text(data.feedback_new);
    } catch (error) {
      toastError(error);
    }
  }

  load();
});
