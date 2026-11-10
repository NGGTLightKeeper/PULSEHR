// Copyright NGGT.LightKeeper. All Rights Reserved.

import { getJson, patchJson, postJson, putJson } from '../api.js';
import { confirmDialog, escHtml, openDialog, setBusy, toast, toastError } from '../common.js';
import { CHOICE_KINDS, NUMBER_KINDS, valueRange } from '../branching.js';
import { createSurveyRunner } from '../runner.js';

// Labels of question kinds, rule conditions, channels and statuses.
const KIND_LABELS = {
  single: 'Один вариант',
  multiple: 'Несколько вариантов',
  scale: 'Шкала',
  enps: 'eNPS (0–10)',
  text: 'Свободный ответ'
};
const OPERATOR_LABELS = {
  chosen: 'выбран вариант',
  not_chosen: 'не выбран вариант',
  range: 'оценка от … до …',
  answered: 'есть ответ',
  skipped: 'нет ответа',
  always: 'всегда'
};
const CHANNEL_LABELS = { push: 'Web Push', telegram: 'Telegram', email: 'E-mail' };
const ALL_CHANNELS = ['push', 'telegram', 'email'];
const STATUS_BADGES = { draft: '', scheduled: 'badge-info', active: 'badge-accent', closed: 'badge-success' };

// Survey builder.
// Edit the questions, their options and branch rules, the survey settings; preview and publish.
$(function initBuilderPage() {
  const surveyId = $('#builderPage').data('survey-id');
  const $questions = $('#questions');
  const $settings = $('#settingsForm');
  let survey = null;
  let questions = [];
  let departments = [];
  let editable = false;
  let dirty = false;
  let keyCounter = 0;


  // State helpers.
  function newKey(prefix) {
    keyCounter += 1;
    return `new-${prefix}-${keyCounter}`;
  }

  function markDirty() {
    dirty = true;
    $('#saveState').text('Есть несохранённые изменения');
  }

  // Return the operators that make sense for the question kind.
  function operatorsFor(kind) {
    if (CHOICE_KINDS.includes(kind)) {
      return ['chosen', 'not_chosen', 'answered', 'skipped', 'always'];
    }
    if (NUMBER_KINDS.includes(kind)) {
      return ['range', 'answered', 'skipped', 'always'];
    }
    return ['answered', 'skipped', 'always'];
  }

  function newQuestion(kind) {
    const question = {
      key: newKey('q'),
      kind,
      text: '',
      help_text: '',
      is_required: true,
      scale_min: 1,
      scale_max: 5,
      min_label: '',
      max_label: '',
      options: [],
      rules: []
    };
    if (CHOICE_KINDS.includes(kind)) {
      question.options = [{ key: newKey('o'), text: '' }, { key: newKey('o'), text: '' }];
    }
    if (kind === 'enps') {
      question.text = 'Насколько вероятно, что вы порекомендуете нашу компанию как место работы друзьям или знакомым?';
      question.min_label = 'Точно нет';
      question.max_label = 'Точно да';
    }
    if (kind === 'text') {
      question.is_required = false;
    }
    return question;
  }

  // Drop the rules that do not fit the question kind after it changed.
  function fitRulesToKind(question) {
    const allowed = operatorsFor(question.kind);
    question.rules = question.rules.filter(function fits(rule) {
      return allowed.includes(rule.operator);
    });
    if (CHOICE_KINDS.includes(question.kind) && question.options.length < 2) {
      while (question.options.length < 2) {
        question.options.push({ key: newKey('o'), text: '' });
      }
    }
  }

  function shortText(text, index) {
    const value = String(text || '').trim();
    const short = value.length > 50 ? `${value.slice(0, 50)}…` : value;
    return `${index + 1}. ${short || 'без текста'}`;
  }


  // Questions.
  function optionsHtml(question, qIndex) {
    if (!CHOICE_KINDS.includes(question.kind)) {
      return '';
    }
    const rows = question.options.map(function optionRow(option, oIndex) {
      return `
        <div class="option-row">
          <input class="input input-sm" data-q="${qIndex}" data-o="${oIndex}" data-field="option-text" value="${escHtml(option.text)}" placeholder="Вариант ${oIndex + 1}" maxlength="300">
          ${editable ? `<button type="button" class="btn btn-ghost btn-sm" data-q="${qIndex}" data-o="${oIndex}" data-action="remove-option" title="Удалить вариант">✕</button>` : ''}
        </div>`;
    });
    const add = editable ? `<button type="button" class="btn btn-ghost btn-sm" data-q="${qIndex}" data-action="add-option">+ Вариант</button>` : '';
    return `<div class="q-section"><div class="q-section-title">Варианты ответа</div>${rows.join('')}${add}</div>`;
  }

  function scaleHtml(question, qIndex) {
    if (!NUMBER_KINDS.includes(question.kind)) {
      return '';
    }
    const range = question.kind === 'scale'
      ? `<div class="row">
           <label class="small">От <input class="input input-sm rule-number" type="number" data-q="${qIndex}" data-field="scale_min" value="${question.scale_min}" min="-10" max="10"></label>
           <label class="small">до <input class="input input-sm rule-number" type="number" data-q="${qIndex}" data-field="scale_max" value="${question.scale_max}" min="-10" max="10"></label>
         </div>`
      : '<div class="muted small">Шкала 0–10: 0–6 — критики, 7–8 — нейтралы, 9–10 — промоутеры.</div>';
    return `
      <div class="q-section">
        <div class="q-section-title">Шкала</div>
        ${range}
        <div class="grid grid-2" style="margin-top:8px">
          <input class="input input-sm" data-q="${qIndex}" data-field="min_label" value="${escHtml(question.min_label)}" placeholder="Подпись минимума" maxlength="100">
          <input class="input input-sm" data-q="${qIndex}" data-field="max_label" value="${escHtml(question.max_label)}" placeholder="Подпись максимума" maxlength="100">
        </div>
      </div>`;
  }

  // Rules: the condition, its option or range, and the target among the later questions.
  function rulesHtml(question, qIndex) {
    const rows = question.rules.map(function ruleRow(rule, rIndex) {
      const operators = operatorsFor(question.kind).map(function operatorOption(operator) {
        return `<option value="${operator}" ${rule.operator === operator ? 'selected' : ''}>${OPERATOR_LABELS[operator]}</option>`;
      }).join('');

      let condition = '';
      if (rule.operator === 'chosen' || rule.operator === 'not_chosen') {
        condition = `<select class="select input-sm" data-q="${qIndex}" data-r="${rIndex}" data-field="rule-option">
          ${question.options.map(function optionChoice(option, oIndex) {
            const label = option.text || `Вариант ${oIndex + 1}`;
            return `<option value="${escHtml(option.key)}" ${String(rule.option) === String(option.key) ? 'selected' : ''}>${escHtml(label)}</option>`;
          }).join('')}
        </select>`;
      } else if (rule.operator === 'range') {
        const [low, high] = valueRange(question);
        condition = `
          <input class="input input-sm rule-number" type="number" data-q="${qIndex}" data-r="${rIndex}" data-field="rule-min" value="${rule.min ?? ''}" min="${low}" max="${high}" placeholder="${low}">
          <span class="muted">–</span>
          <input class="input input-sm rule-number" type="number" data-q="${qIndex}" data-r="${rIndex}" data-field="rule-max" value="${rule.max ?? ''}" min="${low}" max="${high}" placeholder="${high}">`;
      }

      const targetIsValid = rule.target === null || questions.findIndex((item) => String(item.key) === String(rule.target)) > qIndex;
      const targets = questions.slice(qIndex + 1).map(function targetOption(target, offset) {
        const selected = String(rule.target) === String(target.key) ? 'selected' : '';
        return `<option value="${escHtml(target.key)}" ${selected}>к вопросу ${escHtml(shortText(target.text, qIndex + 1 + offset))}</option>`;
      }).join('');

      return `
        <div class="rule-row">
          <span class="small muted">Если</span>
          <select class="select input-sm" data-q="${qIndex}" data-r="${rIndex}" data-field="rule-operator">${operators}</select>
          ${condition}
          <span class="rule-arrow">→</span>
          <select class="select input-sm" data-q="${qIndex}" data-r="${rIndex}" data-field="rule-target" data-rule-target>
            ${targets}
            <option value="" ${rule.target === null ? 'selected' : ''}>завершить опрос</option>
          </select>
          ${targetIsValid ? '' : '<span class="badge badge-danger">выберите переход заново</span>'}
          ${editable ? `<button type="button" class="btn btn-ghost btn-sm" data-q="${qIndex}" data-r="${rIndex}" data-action="remove-rule" title="Удалить условие">✕</button>` : ''}
        </div>`;
    });

    const add = editable ? `<button type="button" class="btn btn-ghost btn-sm" data-q="${qIndex}" data-action="add-rule">+ Условие перехода</button>` : '';
    return `
      <div class="q-section">
        <div class="q-section-title">Ветвление</div>
        ${rows.join('')}
        <div class="row-between">
          ${add}
          <span class="muted small">Если ни одно условие не подошло — следующий вопрос.</span>
        </div>
      </div>`;
  }

  function questionHtml(question, qIndex) {
    const kinds = Object.keys(KIND_LABELS).map(function kindOption(kind) {
      return `<option value="${kind}" ${question.kind === kind ? 'selected' : ''}>${KIND_LABELS[kind]}</option>`;
    }).join('');
    const tools = editable
      ? `<div class="q-tools">
           <button type="button" class="btn btn-ghost btn-icon" data-q="${qIndex}" data-action="up" title="Выше" ${qIndex === 0 ? 'disabled' : ''}>↑</button>
           <button type="button" class="btn btn-ghost btn-icon" data-q="${qIndex}" data-action="down" title="Ниже" ${qIndex === questions.length - 1 ? 'disabled' : ''}>↓</button>
           <button type="button" class="btn btn-ghost btn-icon" data-q="${qIndex}" data-action="remove" title="Удалить вопрос">✕</button>
         </div>`
      : '';

    return `
      <article class="q-card" data-key="${escHtml(question.key)}">
        <div class="q-head">
          <span class="q-number">${qIndex + 1}</span>
          <select class="select input-sm" data-q="${qIndex}" data-field="kind">${kinds}</select>
          ${tools}
        </div>
        <div class="q-body">
          <textarea class="textarea" rows="2" data-q="${qIndex}" data-field="text" placeholder="Текст вопроса" maxlength="500">${escHtml(question.text)}</textarea>
          <input class="input input-sm" data-q="${qIndex}" data-field="help_text" value="${escHtml(question.help_text)}" placeholder="Пояснение (необязательно)" maxlength="500">
          <label class="check small">
            <input type="checkbox" data-q="${qIndex}" data-field="is_required" ${question.is_required ? 'checked' : ''}>
            <span>Обязательный вопрос</span>
          </label>
          ${optionsHtml(question, qIndex)}
          ${scaleHtml(question, qIndex)}
          ${rulesHtml(question, qIndex)}
        </div>
      </article>`;
  }

  function renderQuestions() {
    $questions.html(questions.length
      ? questions.map(questionHtml).join('')
      : '<div class="card empty">Вопросов пока нет. Добавьте первый вопрос ниже.</div>');
    $('#addQuestion').toggleClass('hidden', !editable);
    if (!editable) {
      $questions.find('input, select, textarea').prop('disabled', true);
    }
  }

  // Update the target labels after a question text changed, without rebuilding the inputs.
  function refreshTargetLabels() {
    $questions.find('[data-rule-target] option[value!=""]').each(function updateLabel() {
      const index = questions.findIndex((item) => String(item.key) === String(this.value));
      if (index >= 0) {
        this.textContent = `к вопросу ${shortText(questions[index].text, index)}`;
      }
    });
  }


  // Settings.
  function toLocalInput(iso) {
    if (!iso) {
      return '';
    }
    const date = new Date(iso);
    const pad = (value) => String(value).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function fromLocalInput(value) {
    return value ? new Date(value).toISOString() : null;
  }

  function channelRowsHtml() {
    const ordered = survey.cascade_channels.concat(ALL_CHANNELS.filter((channel) => !survey.cascade_channels.includes(channel)));
    return ordered.map(function channelRow(channel, index) {
      const enabled = survey.cascade_channels.includes(channel);
      return `
        <div class="channel-row" data-channel="${channel}">
          <label class="check"><input type="checkbox" data-channel-toggle ${enabled ? 'checked' : ''}><span>${CHANNEL_LABELS[channel]}</span></label>
          <button type="button" class="btn btn-ghost btn-sm" data-channel-move="-1" ${index === 0 ? 'disabled' : ''}>↑</button>
          <button type="button" class="btn btn-ghost btn-sm" data-channel-move="1" ${index === ordered.length - 1 ? 'disabled' : ''}>↓</button>
        </div>`;
    }).join('');
  }

  function renderSettings() {
    const draft = survey.status === 'draft';
    const closed = survey.status === 'closed';
    const departmentChecks = departments.map(function departmentCheck(department) {
      const checked = survey.audience_departments.includes(department.id) ? 'checked' : '';
      return `<label class="check small" style="padding-left:${department.depth * 16}px">
        <input type="checkbox" data-department="${department.id}" ${checked}><span>${escHtml(department.name)}</span></label>`;
    }).join('') || '<span class="muted small">Подразделений пока нет.</span>';

    $settings.html(`
      <div class="field">
        <label for="sTitle">Название</label>
        <input class="input" id="sTitle" name="title" value="${escHtml(survey.title)}" maxlength="200" ${closed ? 'disabled' : ''}>
      </div>
      <div class="field">
        <label for="sDescription">Описание для сотрудников</label>
        <textarea class="textarea" id="sDescription" name="description" rows="3" ${closed ? 'disabled' : ''}>${escHtml(survey.description)}</textarea>
      </div>
      <div class="field">
        <span class="field-label">Режим</span>
        <label class="mode-option ${survey.mode === 'anonymous' ? 'selected' : ''}">
          <input type="radio" name="mode" value="anonymous" ${survey.mode === 'anonymous' ? 'checked' : ''} ${draft ? '' : 'disabled'}>
          <span><strong>Анонимный</strong><br><span class="muted small">Ответы не связаны с сотрудником, итоги видны от порога ответов.</span></span>
        </label>
        <label class="mode-option ${survey.mode === 'identified' ? 'selected' : ''}">
          <input type="radio" name="mode" value="identified" ${survey.mode === 'identified' ? 'checked' : ''} ${draft ? '' : 'disabled'}>
          <span><strong>Идентифицированный</strong><br><span class="muted small">HR видит ответы вместе с именем пользователя.</span></span>
        </label>
        <span class="field-hint">После публикации режим не меняется.</span>
      </div>
      <div class="field ${survey.mode === 'anonymous' ? '' : 'hidden'}" id="thresholdField">
        <label for="sThreshold">Порог анонимности</label>
        <input class="input" id="sThreshold" name="min_group_size" type="number" min="1" max="50" value="${survey.min_group_size}" ${draft ? '' : 'disabled'}>
        <span class="field-hint">Итоги опроса и подразделения показываются, только когда ответов не меньше этого числа.</span>
      </div>
      <div class="field">
        <span class="field-label">Кому</span>
        <label class="check"><input type="radio" name="audience" value="all" ${survey.audience_all ? 'checked' : ''} ${draft ? '' : 'disabled'}><span>Всем сотрудникам</span></label>
        <label class="check"><input type="radio" name="audience" value="departments" ${survey.audience_all ? '' : 'checked'} ${draft ? '' : 'disabled'}><span>Выбранным подразделениям</span></label>
        <div class="department-checks ${survey.audience_all ? 'hidden' : ''}" id="departmentChecks">${departmentChecks}</div>
        <span class="field-hint">Вложенные подразделения входят в выбранные.</span>
      </div>
      <div class="grid grid-2">
        <div class="field">
          <label for="sStarts">Начало</label>
          <input class="input input-sm" id="sStarts" name="starts_at" type="datetime-local" value="${toLocalInput(survey.starts_at)}" ${draft ? '' : 'disabled'}>
        </div>
        <div class="field">
          <label for="sEnds">Окончание</label>
          <input class="input input-sm" id="sEnds" name="ends_at" type="datetime-local" value="${toLocalInput(survey.ends_at)}" ${closed ? 'disabled' : ''}>
        </div>
      </div>
      <span class="field-hint" style="margin-top:-8px">Без даты начала опрос стартует при публикации.</span>
      <div class="field">
        <span class="field-label">Каскад уведомлений</span>
        <div id="channelRows">${channelRowsHtml()}</div>
        <label class="small" for="sDelay">Пауза перед следующим каналом, минут</label>
        <input class="input input-sm" id="sDelay" name="cascade_delay_minutes" type="number" min="1" max="10080" value="${survey.cascade_delay_minutes}" ${draft ? '' : 'disabled'}>
        <span class="field-hint">Если сотрудник не открыл опрос, через паузу приходит следующий канал. Недоступные каналы пропускаются.</span>
      </div>`);

    if (!draft) {
      $settings.find('#channelRows input, #channelRows button, #departmentChecks input').prop('disabled', true);
    }
  }

  // Read the cascade order and the enabled channels from the settings form.
  function readChannels() {
    return $settings.find('.channel-row').filter(function enabled() {
      return $(this).find('[data-channel-toggle]').prop('checked');
    }).map(function channel() {
      return $(this).data('channel');
    }).get();
  }

  // Return the settings to save; a published survey sends only what can still change.
  function collectSettings() {
    const data = {
      title: String($('#sTitle').val() || '').trim() || 'Без названия',
      description: String($('#sDescription').val() || ''),
      ends_at: fromLocalInput($('#sEnds').val())
    };
    if (survey.status !== 'draft') {
      return data;
    }
    return Object.assign(data, {
      mode: $settings.find('[name=mode]:checked').val(),
      min_group_size: Number($('#sThreshold').val() || 5),
      audience_all: $settings.find('[name=audience]:checked').val() !== 'departments',
      audience_departments: $settings.find('[data-department]:checked').map(function departmentId() {
        return Number($(this).data('department'));
      }).get(),
      starts_at: fromLocalInput($('#sStarts').val()),
      cascade_channels: readChannels(),
      cascade_delay_minutes: Number($('#sDelay').val() || 120)
    });
  }


  // Page state.
  function renderHeader() {
    const draft = survey.status === 'draft';
    $('#surveyTitle').text(survey.title);
    $('#statusBadge').attr('class', `badge ${STATUS_BADGES[survey.status]}`).text(survey.status_label);
    $('#publishBtn').toggleClass('hidden', !draft);
    $('#saveBtn').toggleClass('hidden', survey.status === 'closed');
    $('#resultsLink').toggleClass('hidden', draft).attr('href', `/hr/surveys/${surveyId}/`);
    $('#closeBtn').toggleClass('hidden', !['active', 'scheduled'].includes(survey.status));
    $('#builderNotes').html(draft ? '' : `
      <div class="alert"><div>Опрос опубликован: вопросы, режим и аудитория больше не меняются.
      Можно изменить название, описание и дату окончания или сделать копию.</div></div>`);
  }

  function showStructureErrors(error) {
    const errors = (error.data && error.data.errors) || {};
    const list = Array.isArray(errors.questions) ? errors.questions : [];
    $('#builderNotes').html(list.length
      ? `<div class="form-error" role="alert"><strong>Исправьте вопросы:</strong><ul>${list.map((item) => `<li>${escHtml(item)}</li>`).join('')}</ul></div>`
      : '');
    if (!list.length) {
      toastError(error);
    }
  }

  // Questions in the form the API expects; options go only with choice questions.
  function structurePayload() {
    return questions.map(function questionPayload(question) {
      const isChoice = CHOICE_KINDS.includes(question.kind);
      return {
        key: String(question.key),
        kind: question.kind,
        text: question.text,
        help_text: question.help_text,
        is_required: question.is_required,
        scale_min: Number(question.scale_min),
        scale_max: Number(question.scale_max),
        min_label: question.min_label,
        max_label: question.max_label,
        options: isChoice ? question.options.map((option) => ({ key: String(option.key), text: option.text })) : [],
        rules: question.rules.map(function rulePayload(rule) {
          const withOption = rule.operator === 'chosen' || rule.operator === 'not_chosen';
          return {
            operator: rule.operator,
            option: withOption ? String(rule.option) : null,
            min: rule.operator === 'range' ? rule.min : null,
            max: rule.operator === 'range' ? rule.max : null,
            target: rule.target === null ? null : String(rule.target)
          };
        })
      };
    });
  }

  // Save the settings and, for a draft, the questions. Return whether everything was saved.
  async function save() {
    const $button = $('#saveBtn');
    setBusy($button, true);
    try {
      survey = await patchJson(`/api/v1/hr/surveys/${surveyId}/`, collectSettings());
      if (editable) {
        const structure = await putJson(`/api/v1/hr/surveys/${surveyId}/structure/`, { questions: structurePayload() });
        questions = structure.questions;
      }
      dirty = false;
      $('#saveState').text('Сохранено');
      renderHeader();
      renderQuestions();
      renderSettings();
      return true;
    } catch (error) {
      showStructureErrors(error);
      return false;
    } finally {
      setBusy($button, false);
    }
  }

  async function load() {
    try {
      const [surveyData, structure, departmentList] = await Promise.all([
        getJson(`/api/v1/hr/surveys/${surveyId}/`),
        getJson(`/api/v1/hr/surveys/${surveyId}/structure/`),
        getJson('/api/v1/departments/')
      ]);
      survey = surveyData;
      questions = structure.questions;
      editable = structure.editable;
      departments = departmentList;
      document.title = `${survey.title} · PULSEHR`;
      renderHeader();
      renderQuestions();
      renderSettings();
    } catch (error) {
      $questions.html(`<div class="card empty">${escHtml(error.message)}</div>`);
    }
  }


  // Question events.
  $questions.on('input change', '[data-field]', function onField(event) {
    const $input = $(this);
    const question = questions[Number($input.data('q'))];
    const field = $input.data('field');
    const value = $input.is(':checkbox') ? $input.prop('checked') : $input.val();

    switch (field) {
      case 'text':
        question.text = String(value);
        refreshTargetLabels();
        break;
      case 'help_text':
      case 'min_label':
      case 'max_label':
        question[field] = String(value);
        break;
      case 'is_required':
        question.is_required = Boolean(value);
        break;
      case 'scale_min':
      case 'scale_max':
        question[field] = value === '' ? question[field] : Number(value);
        break;
      case 'option-text':
        question.options[Number($input.data('o'))].text = String(value);
        break;
      case 'rule-min':
      case 'rule-max':
        question.rules[Number($input.data('r'))][field === 'rule-min' ? 'min' : 'max'] = value === '' ? null : Number(value);
        break;
      case 'rule-option':
        question.rules[Number($input.data('r'))].option = String(value);
        break;
      case 'rule-target':
        question.rules[Number($input.data('r'))].target = value === '' ? null : String(value);
        if (event.type === 'change') {
          renderQuestions();
        }
        break;
      case 'rule-operator':
        if (event.type === 'change') {
          const rule = question.rules[Number($input.data('r'))];
          rule.operator = String(value);
          rule.option = question.options.length ? String(question.options[0].key) : null;
          rule.min = null;
          rule.max = null;
          renderQuestions();
        }
        break;
      case 'kind':
        if (event.type === 'change') {
          question.kind = String(value);
          fitRulesToKind(question);
          renderQuestions();
        }
        break;
      default:
        return;
    }
    markDirty();
  });

  $questions.on('click', '[data-action]', function onAction() {
    const $button = $(this);
    const qIndex = Number($button.data('q'));
    const question = questions[qIndex];

    switch ($button.data('action')) {
      case 'up':
      case 'down': {
        const target = $button.data('action') === 'up' ? qIndex - 1 : qIndex + 1;
        [questions[qIndex], questions[target]] = [questions[target], questions[qIndex]];
        break;
      }
      case 'remove': {
        const key = String(question.key);
        questions.splice(qIndex, 1);
        questions.forEach(function dropRulesToRemoved(item) {
          item.rules = item.rules.filter((rule) => String(rule.target) !== key);
        });
        break;
      }
      case 'add-option':
        question.options.push({ key: newKey('o'), text: '' });
        break;
      case 'remove-option': {
        const option = question.options[Number($button.data('o'))];
        question.options.splice(Number($button.data('o')), 1);
        question.rules = question.rules.filter((rule) => String(rule.option) !== String(option.key));
        break;
      }
      case 'add-rule': {
        const operator = operatorsFor(question.kind)[0];
        const next = questions[qIndex + 1];
        question.rules.push({
          operator,
          option: question.options.length ? String(question.options[0].key) : null,
          min: null,
          max: null,
          target: next ? String(next.key) : null
        });
        break;
      }
      case 'remove-rule':
        question.rules.splice(Number($button.data('r')), 1);
        break;
      default:
        return;
    }
    markDirty();
    renderQuestions();
  });

  $('#addQuestion').on('click', '[data-add]', function onAdd() {
    questions.push(newQuestion(String($(this).data('add'))));
    markDirty();
    renderQuestions();
    $questions.find('.q-card').last()[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
  });


  // Settings events.
  $settings.on('input change', 'input, textarea, select', function onSetting() {
    markDirty();
  });

  $settings.on('change', '[name=mode]', function onMode() {
    $settings.find('.mode-option').removeClass('selected');
    $(this).closest('.mode-option').addClass('selected');
    $('#thresholdField').toggleClass('hidden', this.value !== 'anonymous');
  });

  $settings.on('change', '[name=audience]', function onAudience() {
    $('#departmentChecks').toggleClass('hidden', this.value !== 'departments');
  });

  $settings.on('click', '[data-channel-move]', function onMoveChannel() {
    const $row = $(this).closest('.channel-row');
    if (Number($(this).data('channel-move')) < 0) {
      $row.insertBefore($row.prev());
    } else {
      $row.insertAfter($row.next());
    }
    survey.cascade_channels = readChannels();
    $('#channelRows').html(channelRowsHtml());
    markDirty();
  });

  $settings.on('change', '[data-channel-toggle]', function onToggleChannel() {
    survey.cascade_channels = readChannels();
  });


  // Page actions.
  $('#saveBtn').on('click', async function onSave() {
    if (await save()) {
      toast('Сохранено.', 'success');
    }
  });

  $('#previewBtn').on('click', function onPreview() {
    const $body = $('<div><div class="alert" style="margin-bottom:16px">Предпросмотр: ответы не сохраняются.</div><div id="previewRunner"></div></div>');
    const dialog = openDialog({ title: survey.title, $body, wide: true });
    createSurveyRunner($body.find('#previewRunner'), JSON.parse(JSON.stringify(structurePayload())), {
      submitText: 'Завершить предпросмотр',
      onSubmit: async function finishPreview() {
        dialog.close();
        toast('Предпросмотр завершён. Ответы не сохранены.');
      }
    });
  });

  $('#publishBtn').on('click', async function onPublish() {
    if (!(await save())) {
      return;
    }
    const channels = survey.cascade_channels.map((channel) => CHANNEL_LABELS[channel]).join(' → ') || 'без уведомлений';
    const mode = survey.mode === 'anonymous' ? 'анонимный' : 'идентифицированный';
    const confirmed = await confirmDialog({
      title: 'Опубликовать опрос?',
      message: `Режим: ${mode}. После публикации вопросы, режим и аудиторию изменить нельзя.\nУведомления: ${channels}.`,
      confirmText: 'Опубликовать'
    });
    if (!confirmed) {
      return;
    }
    const $button = $(this);
    setBusy($button, true);
    try {
      await postJson(`/api/v1/hr/surveys/${surveyId}/publish/`);
      dirty = false;
      window.location.href = `/hr/surveys/${surveyId}/`;
    } catch (error) {
      setBusy($button, false);
      showStructureErrors(error);
    }
  });

  $('#closeBtn').on('click', async function onClose() {
    const confirmed = await confirmDialog({
      title: 'Завершить опрос?',
      message: 'Сотрудники больше не смогут отвечать, неотправленные напоминания будут отменены.',
      confirmText: 'Завершить',
      danger: true
    });
    if (!confirmed) {
      return;
    }
    try {
      await postJson(`/api/v1/hr/surveys/${surveyId}/close/`);
      window.location.href = `/hr/surveys/${surveyId}/`;
    } catch (error) {
      toastError(error);
    }
  });

  $(window).on('beforeunload', function onLeave(event) {
    if (dirty) {
      event.preventDefault();
      return '';
    }
    return undefined;
  });

  load();
});
