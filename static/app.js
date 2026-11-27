'use strict';

const routes = {
  access: 'Доступ и аккаунт', payment: 'Оплата и возврат', schedule: 'Расписание занятий',
  materials: 'Учебные материалы', other: 'Вне очередей', manual: 'Ручной разбор',
};
const statuses = { new: 'Новое', review: 'На разборе', resolved: 'Направлено' };
const models = { v1: 'Исходная модель', rules: 'Правила', naive_bayes: 'Naive Bayes', logistic: 'Logistic Regression', svm: 'Linear SVM' };
const views = { inbox: 'Обращения', history: 'История', analytics: 'Аналитика', quality: 'Качество ИИ', economics: 'Экономика', about: 'О продукте' };
const reasons = {
  short: 'В сообщении мало информации. Выберите очередь вручную или уточните запрос.',
  other: 'Тема похожа на обращение вне четырёх очередей.',
  low_score: 'Оценка лучшей очереди ниже порога выдачи рекомендации.',
  close_scores: 'Оценки двух вариантов близки. Проверьте основное намерение.',
};
const eventNames = {
  created: 'Обращение сохранено', analyzed: 'Модель проанализировала текст', confirmed: 'Очередь подтверждена',
  rerouted: 'Оператор выбрал очередь', reviewed: 'Передано на ручной разбор', feedback: 'Добавлена обратная связь',
};
const feedbackNames = { helpful: 'Рекомендация полезна', unclear: 'Недостаточно информации', wrong: 'Рекомендация ошибочна' };
const sourceNames = { demo: 'Демо', manual: 'Ручной ввод', csv: 'Импорт CSV' };
const classShort = { access: 'Доступ', payment: 'Оплата', schedule: 'Расписание', materials: 'Материалы', other: 'Вне очередей', manual: 'Разбор' };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const formatter = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const rate = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
const money = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0, style: 'currency', currency: 'RUB' });
const dateTime = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const number = value => value == null ? '—' : formatter.format(value);
const percent = value => value == null ? '—' : rate.format(value);
const rub = value => value == null ? '—' : money.format(value);
const stamp = value => dateTime.format(new Date(value));
const portion = (value, total) => total ? value / total : null;

const state = { view: null, selected: null, offset: 0, limit: 12, total: 0, listRequest: 0, detailRequest: 0, pageRequest: 0 };
const filters = $('#filters');
for (const [key, label] of Object.entries(routes)) {
  if (key !== 'other') option(filters.elements.queue, key, label);
}
let filterTimer;
let noticeTimer;
let qualityData;
let qualityObserver;
let economicRequest = 0;

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function button(text, action, appearance = 'compact') {
  const item = element('button', text, 'button ' + appearance);
  item.type = 'button';
  item.addEventListener('click', action);
  return item;
}

function option(select, value, text) {
  const item = element('option', text);
  item.value = value;
  select.append(item);
}

function choices(labels, selected, ariaLabel) {
  const select = element('select');
  select.setAttribute('aria-label', ariaLabel);
  for (const [value, label] of Object.entries(labels)) option(select, value, label);
  select.value = selected;
  return select;
}

function table(headers, rows, highlight = -1) {
  const frame = element('div', null, 'table-scroll data-table');
  const grid = element('table');
  const head = grid.createTHead().insertRow();
  for (const label of headers) {
    const cell = element('th', label);
    cell.scope = 'col';
    head.append(cell);
  }
  const body = grid.createTBody();
  rows.forEach((values, index) => {
    const row = body.insertRow();
    if (index === highlight) row.className = 'highlight';
    for (const value of values) row.insertCell().textContent = value;
  });
  frame.append(grid);
  return frame;
}

function panel(title, ...children) {
  const pane = element('section', null, 'surface pane below');
  pane.append(element('h2', title), ...children);
  return pane;
}

function metrics(values) {
  const group = element('div', null, 'metric-grid');
  values.forEach(([label, value, context]) => {
    const cell = element('div', null, 'metric');
    cell.append(element('span', label), element('strong', value));
    if (context) cell.append(element('small', context));
    group.append(cell);
  });
  return group;
}

function definitions(rows) {
  const list = element('dl', null, 'definition-list');
  for (const [key, value] of rows) list.append(element('dt', key), element('dd', value));
  return list;
}

function showMessage(text) {
  clearTimeout(noticeTimer);
  $('#notice').textContent = text;
  $('#notice').hidden = false;
  noticeTimer = setTimeout(() => { $('#notice').hidden = true; }, 4800);
}

function showFieldError(selector, error) {
  const field = $(selector);
  field.textContent = error ? error.message : '';
  field.hidden = !error;
}

function serviceError(error) {
  $('#health').className = 'health failed';
  $('#health span').textContent = 'Нет соединения';
  $('#service-error-text').textContent = error.message;
  $('#service-error').hidden = false;
}

async function request(path, body) {
  try {
    const response = await fetch(path, body === undefined ? { signal: AbortSignal.timeout(12000) } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      signal: AbortSignal.timeout(12000),
    });
    const payload = await response.json();
    if (!response.ok) throw Object.assign(new Error(payload.error || 'Не удалось выполнить запрос.'), { status: response.status });
    $('#health').className = 'health ready';
    $('#health span').textContent = 'Локальный режим';
    $('#service-error').hidden = true;
    return payload;
  } catch (error) {
    if (!error.status) {
      const unavailable = new Error('Локальный сервер недоступен. Проверьте, запущено ли приложение.');
      serviceError(unavailable);
      throw unavailable;
    }
    throw error;
  }
}

function queryForList() {
  const query = new URLSearchParams(new FormData(filters));
  if (state.view === 'history') query.set('history', '1');
  return query;
}

function highlightSelection() {
  $$('#ticket-rows button').forEach(item => {
    const selected = Number(item.dataset.id) === state.selected;
    item.setAttribute('aria-pressed', String(selected));
    item.closest('tr').classList.toggle('selected', selected);
  });
}

function selectBadge(status) {
  return element('span', statuses[status], 'badge ' + status);
}

function renderRows(items) {
  const rows = items.map(ticket => {
    const row = element('tr');
    const opener = button('', () => openTicket(ticket.id, true), 'row-open');
    opener.className = 'row-open';
    opener.dataset.id = ticket.id;
    const meta = element('span', null, 'ticket-meta');
    meta.append(element('span', '#' + ticket.id), element('span', stamp(ticket.created_at)));
    if (ticket.source === 'demo') meta.append(element('span', 'Демо', 'badge demo'));
    opener.append(element('span', ticket.text, 'ticket-title'), meta);
    row.insertCell().append(opener);
    row.insertCell().append(selectBadge(ticket.status));
    const queue = row.insertCell();
    queue.className = 'queue-cell';
    queue.textContent = routes[ticket.operator_route || ticket.recommendation];
    return row;
  });
  $('#ticket-rows').replaceChildren(...rows);
  highlightSelection();
}

async function refreshList() {
  const generation = ++state.listRequest;
  const query = queryForList();
  $('#export-link').href = '/api/export?' + query;
  query.set('limit', state.limit);
  query.set('offset', state.offset);
  $('#list-state').textContent = 'Загрузка обращений…';
  $('#list-state').hidden = !$('#table-wrapper').hidden;
  try {
    const data = await request('/api/tickets?' + query);
    if (generation !== state.listRequest) return;
    if (data.total && !data.items.length && state.offset) {
      state.offset = Math.floor((data.total - 1) / state.limit) * state.limit;
      return refreshList();
    }
    state.total = data.total;
    renderRows(data.items);
    $('#table-wrapper').hidden = !data.items.length;
    $('#list-state').hidden = Boolean(data.items.length);
    $('#list-state').textContent = query.get('q') || query.get('status') || query.get('queue')
      ? 'По заданным фильтрам обращений нет.'
      : state.view === 'history' ? 'Решения оператора появятся здесь.' : 'Обращений пока нет. Создайте новое или загрузите демо.';
    $('#pagination').hidden = !data.items.length;
    $('#page-range').textContent = (state.offset + 1) + '–' + (state.offset + data.items.length) + ' из ' + data.total;
    $('#prev').disabled = state.offset === 0;
    $('#next').disabled = state.offset + state.limit >= state.total;
    if (state.view === 'inbox') {
      const summary = await request('/api/analytics?scope=' + query.get('scope'));
      if (generation !== state.listRequest) return;
      for (const [id, value] of Object.entries({ total: summary.received, new: summary.new, review: summary.review, resolved: summary.resolved })) {
        $('#count-' + id).textContent = number(value);
      }
    }
  } catch (error) {
    if (generation !== state.listRequest) return;
    $('#list-state').textContent = error.message;
    $('#list-state').hidden = false;
  }
}

function resetFilters(scope = filters.elements.scope.value) {
  filters.reset();
  filters.elements.scope.value = scope;
  state.offset = 0;
  updateSummarySelection();
}

function updateSummarySelection() {
  $$('[data-status]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.status === filters.elements.status.value)));
}

function clearDetail() {
  state.selected = null;
  state.detailRequest++;
  $('#detail').hidden = true;
  $('#detail-empty').hidden = false;
  $('.inspector').setAttribute('aria-labelledby', 'inspector-title');
  highlightSelection();
}

async function openTicket(id, focus = false) {
  const generation = ++state.detailRequest;
  state.selected = id;
  highlightSelection();
  $('#detail-empty').hidden = true;
  $('#detail').hidden = false;
  $('#detail').replaceChildren(element('p', 'Загрузка карточки…', 'table-state'));
  try {
    const ticket = await request('/api/tickets/' + id);
    if (generation !== state.detailRequest) return;
    renderTicket(ticket);
    if (focus) $('#ticket-heading').focus();
  } catch (error) {
    if (generation !== state.detailRequest) return;
    $('#detail').replaceChildren(element('p', error.message, 'table-state'), button('Повторить', () => openTicket(id, true)));
  }
}

function detailGroup(title, content) {
  const group = element('details');
  group.append(element('summary', title), content);
  return group;
}

function renderTicket(ticket) {
  const container = $('#detail');
  const oldOpen = new Set($$('details[open] summary', container).map(el => el.textContent));
  const heading = element('h2', 'Обращение #' + ticket.id);
  heading.id = 'ticket-heading';
  heading.tabIndex = -1;
  const head = element('header', null, 'panel-head detail-head');
  head.append(heading, selectBadge(ticket.status));

  const body = element('div', null, 'detail-body');
  body.append(element('div', sourceNames[ticket.source] + ' · ' + stamp(ticket.created_at), 'detail-meta'),
    element('p', ticket.text, 'ticket-message'));
  const prediction = ticket.prediction;
  const manual = prediction.route === 'manual';
  const recommendation = element('div', null, 'recommendation' + (manual ? ' manual' : ''));
  recommendation.append(element('span', manual ? 'Без рекомендации' : 'Рекомендация модели', 'eyebrow'),
    element('h3', routes[prediction.route]),
    element('p', (manual ? reasons[prediction.reason] + ' ' : '') +
      'Оценка ' + percent(prediction.confidence) + ' · порог ' + percent(prediction.threshold)));
  body.append(recommendation);

  const scoreLines = element('div');
  for (const [label, value] of Object.entries(prediction.scores).sort((a, b) => b[1] - a[1])) {
    const line = element('div', null, 'score-line');
    const meter = element('meter');
    meter.value = value;
    meter.min = 0;
    meter.max = 1;
    meter.setAttribute('aria-label', routes[label] + ' ' + percent(value));
    line.append(element('span', routes[label]), meter, element('span', percent(value)));
    scoreLines.append(line);
  }
  scoreLines.append(element('p', ticket.model_version, 'mono'));
  body.append(detailGroup('Оценки по очередям', scoreLines));

  const review = element('div', null, 'detail-section');
  review.append(element('h3', 'Решение оператора'));
  if (ticket.operator_route) review.append(element('p', routes[ticket.operator_route], 'muted'));
  const routeOpts = Object.fromEntries(Object.entries(routes).filter(([key]) => key !== 'other' && key !== 'manual'));
  const selected = ticket.operator_route !== 'manual' ? ticket.operator_route : null;
  const choice = choices({ '': 'Выберите очередь', ...routeOpts }, selected || '', 'Очередь оператора');
  review.append(choice);
  const actions = element('div', null, 'actions');
  const change = button('Сохранить очередь', () => updateDecision(ticket, choice.value, review));
  const syncChange = () => { change.disabled = !choice.value || choice.value === ticket.operator_route; };
  syncChange();
  choice.addEventListener('change', syncChange);
  if (!manual && ticket.operator_route !== prediction.route) {
    actions.append(button('Подтвердить подсказку', () => updateDecision(ticket, 'confirm', review), 'primary compact'));
  }
  actions.append(change);
  if (ticket.status !== 'review') actions.append(button('На ручной разбор', () => updateDecision(ticket, 'manual', review)));
  const error = element('p', '', 'field-error');
  error.setAttribute('role', 'alert');
  review.append(actions, error);
  body.append(review);

  const timeline = element('ol', null, 'event-list');
  ticket.events.forEach(event => {
    const item = element('li');
    item.append(element('div', eventNames[event.kind] + (event.route ? ' · ' + routes[event.route] : '')),
      element('time', stamp(event.occurred_at), 'muted'));
    timeline.append(item);
  });
  body.append(detailGroup('История действий', timeline));

  const feedback = element('form', null, 'feedback-form');
  const category = choices(feedbackNames, 'helpful', 'Оценка подсказки');
  const note = element('textarea');
  note.rows = 2;
  note.maxLength = 500;
  note.placeholder = 'Комментарий по желанию';
  note.setAttribute('aria-label', 'Комментарий к обратной связи');
  const send = element('button', 'Записать обратную связь', 'button compact');
  send.type = 'submit';
  const feedbackError = element('p', '', 'field-error');
  feedbackError.setAttribute('role', 'alert');
  feedback.append(category, note, send, feedbackError);
  if (ticket.feedback.length) {
    const entries = element('ul', null, 'event-list');
    ticket.feedback.forEach(item => entries.append(element('li',
      feedbackNames[item.kind] + ' · ' + stamp(item.occurred_at) + (item.note ? ' · ' + item.note : ''))));
    feedback.append(entries);
  }
  feedback.addEventListener('submit', async event => {
    event.preventDefault();
    send.disabled = true;
    feedbackError.textContent = '';
    try {
      const item = await request('/api/tickets/' + ticket.id + '/feedback', { kind: category.value, note: note.value });
      if (state.selected === ticket.id) {
        renderTicket(item);
        $('#ticket-heading').focus({ preventScroll: true });
      }
      showMessage('Обратная связь сохранена.');
    } catch (failure) {
      feedbackError.textContent = failure.message;
    } finally {
      send.disabled = false;
    }
  });
  body.append(detailGroup('Обратная связь', feedback));
  container.replaceChildren(head, body);
  $$('details', container).forEach(group => { group.open = oldOpen.has($('summary', group).textContent); });
  $('.inspector').setAttribute('aria-labelledby', heading.id);
}

async function updateDecision(ticket, route, region) {
  const controls = $$('button, select', region);
  const disabled = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  const field = $('.field-error', region);
  field.textContent = '';
  try {
    const current = await request('/api/tickets/' + ticket.id + '/decision', { route, revision: ticket.revision });
    if (state.selected === ticket.id) {
      renderTicket(current);
      $('#ticket-heading').focus({ preventScroll: true });
    }
    if (state.view === 'inbox' || state.view === 'history') await refreshList();
    showMessage(route === 'manual' ? 'Обращение передано на ручной разбор.' : 'Очередь сохранена.');
  } catch (error) {
    field.textContent = error.message;
    if (error.status === 409) region.append(button('Обновить карточку', () => openTicket(ticket.id, true)));
  } finally {
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
  }
}

async function refreshAnalytics() {
  const generation = ++state.pageRequest;
  const container = $('#analytics-content');
  container.replaceChildren(element('p', 'Загрузка аналитики…', 'muted'));
  try {
    const a = await request('/api/analytics?scope=' + $('#analytics-scope').value);
    if (generation !== state.pageRequest) return;
    if (!a.received) {
      container.replaceChildren(panel('Пока нет данных', element('p', 'Выберите другой источник или обработайте первое обращение.', 'muted')));
      return;
    }
    const top = metrics([
      ['Поступило', number(a.received)], ['Обработано', number(a.processed), 'Дошли до первой очереди'],
      ['На ручном разборе', percent(portion(a.review, a.received)), number(a.review) + ' сейчас'],
      ['Медиана до первой очереди', a.median_seconds == null ? '—' : number(a.median_seconds) + ' с', 'Включает ожидание'],
    ]);
    const actions = panel('Рекомендации и решения', definitions([
      ['Доля обращений с подсказкой', percent(portion(a.suggestions, a.received))],
      ['Модель предложила ручной разбор', percent(portion(a.manual_suggested, a.received))],
      ['Последнее решение совпало с подсказкой', percent(portion(a.confirmed, a.reviewed_suggestions))],
      ['Последнее решение изменило очередь', percent(portion(a.changed, a.reviewed_suggestions))],
      ['Среднее время до первой очереди', a.mean_seconds == null ? '—' : number(a.mean_seconds) + ' с'],
    ]), element('p', 'Доли решений считаются среди подсказок, которые рассмотрел оператор.', 'muted'));
    const bars = Object.entries(a.queues).map(([key, value]) => {
      const line = element('div', null, 'bar');
      const meter = element('meter');
      meter.max = Math.max(1, a.resolved);
      meter.value = value;
      meter.setAttribute('aria-label', routes[key] + ' ' + value);
      line.append(element('span', routes[key]), meter, element('strong', number(value)));
      return line;
    });
    const queues = panel('Направлено по очередям', ...bars);
    const sides = element('div', null, 'two-col');
    sides.append(actions, queues);
    const days = panel('Динамика по дням', table(['Дата, UTC', 'Поступило', 'Первая очередь'], a.daily.map(row =>
      [row.date, number(row.received), number(row.processed)])));
    container.replaceChildren(top, sides, days);
  } catch (error) {
    if (generation === state.pageRequest) container.replaceChildren(element('p', error.message, 'field-error'));
  }
}

function drawPlot(canvas, points, xTitle, yFormat) {
  const box = canvas.getBoundingClientRect();
  if (!box.width) return;
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.round(box.width * scale);
  canvas.height = Math.round(box.height * scale);
  const ctx = canvas.getContext('2d');
  ctx.scale(scale, scale);
  const { width, height } = box;
  const left = Math.min(width * .29, 59), right = width - 9, top = 14, bottom = height - 37;
  const min = Math.min(0, ...points.map(p => p[1]));
  const max = Math.max(...points.map(p => p[1]), min + .001);
  const y = value => bottom - (value - min) / (max - min) * (bottom - top);
  const x = value => left + value * (right - left);
  ctx.font = '10.5px sans-serif';
  ctx.strokeStyle = '#dce4f3';
  ctx.fillStyle = '#566680';
  ctx.textAlign = 'right';
  for (let index = 0; index <= 4; index++) {
    const value = min + (max - min) * index / 4;
    const yy = y(value);
    ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(right, yy); ctx.stroke();
    ctx.fillText(yFormat(value), left - 5, yy + 3);
  }
  ctx.textAlign = 'center';
  for (const value of [0, .5, 1]) ctx.fillText(percent(value), Math.min(right - 8, Math.max(left + 8, x(value))), bottom + 14);
  ctx.fillText(xTitle, (left + right) / 2, height - 5);
  ctx.strokeStyle = '#254dc3';
  ctx.fillStyle = '#254dc3';
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach(([xx, yy], index) => { if (index) ctx.lineTo(x(xx), y(yy)); else ctx.moveTo(x(xx), y(yy)); });
  ctx.stroke();
  for (const [xx, yy] of points) {
    ctx.beginPath(); ctx.arc(x(xx), y(yy), 2.2, 0, Math.PI * 2); ctx.fill();
  }
}

function qualityPlots(curves) {
  if (qualityObserver) qualityObserver.disconnect();
  const row = element('div', null, 'quality-plots');
  const plots = [
    ['Точность и охват', 'Охват', percent, curves.filter(r => r.precision != null).map(r => [r.coverage, r.precision]).sort((a, b) => a[0] - b[0])],
    ['Эффект в месяц', 'Порог', rub, curves.map(r => [r.threshold, r.net_month_rub])],
    ['Ручной разбор', 'Порог', percent, curves.map(r => [r.threshold, r.manual_share])],
  ];
  const redraw = new Map();
  qualityObserver = new ResizeObserver(entries => entries.forEach(({ target }) => redraw.get(target)()));
  for (const [name, axis, format, points] of plots) {
    const figure = element('figure', null, 'plot');
    const canvas = element('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', name + '. Значения приведены в таблице под графиками.');
    figure.append(element('figcaption', name), canvas);
    redraw.set(canvas, () => drawPlot(canvas, points, axis, format));
    qualityObserver.observe(canvas);
    row.append(figure);
  }
  return row;
}

async function getQuality() {
  if (!qualityData) qualityData = await request('/api/quality');
  return qualityData;
}

async function refreshQuality() {
  const generation = ++state.pageRequest;
  const container = $('#quality-content');
  container.replaceChildren(element('p', 'Загрузка результатов…', 'muted'));
  try {
    const data = await getQuality();
    if (generation !== state.pageRequest) return;
    const split = $('#quality-split').value;
    const comparison = data.comparison[split];
    const best = data.release.algorithm;
    const r = comparison[best];
    const interval = r.ci95_precision ? r.ci95_precision.map(percent).join('–') : '—';
    const top = metrics([
      ['Точность подсказок', percent(r.precision), r.correct + ' / ' + r.recommended + ' · 95% ДИ ' + interval],
      ['Охват', percent(r.coverage), r.recommended + ' / ' + r.n + ' обращений'],
      ['Ошибки в потоке', percent(r.wrong_share), number(r.wrong) + ' ошибочных подсказок'],
      ['Ручной разбор', percent(r.manual_share), r.manual + ' из ' + r.n],
    ]);
    const comparisons = Object.entries(comparison).map(([key, value]) =>
      [models[key] + (key === best ? ' · в приложении' : ''), percent(value.coverage), percent(value.precision),
        percent(value.wrong_share), percent(value.other_recall), number(value.macro_f1 * 100) + '%']);
    const modelPane = panel('Сравнение подходов',
      element('p', models[best] + ' · порог ' + percent(data.release.threshold) + ' · разница оценок от ' + percent(data.release.margin), 'muted'),
      table(['Подход', 'Охват', 'Точность подсказок', 'Ошибки в потоке', 'Отказ на other', 'Macro-F1'], comparisons,
        Object.keys(comparison).indexOf(best)));
    const decisions = panel('Матрица решений',
      element('p', 'Строки показывают эталон, столбцы показывают исход модели.', 'muted'),
      table(['Эталон', ...data.labels.map(label => classShort[label === 'other' ? 'manual' : label])],
        r.matrix.map((line, index) => [classShort[data.labels[index]], ...line.map(number)])));
    const sweepRows = data.curves.map(c => [percent(c.threshold), percent(c.coverage), percent(c.precision), percent(c.manual_share), rub(c.net_month_rub)]);
    const thresholdTable = detailGroup('Значения по порогам', table(['Порог', 'Охват', 'Точность', 'Ручной разбор', 'Эффект/мес.'], sweepRows));
    const policy = panel('Подбор порога на проверочной выборке',
      element('p', 'Эффект рассчитан по базовому экономическому сценарию. Порог выбирали по ожидаемому времени и допустимому риску ошибки.', 'muted'),
      qualityPlots(data.curves), thresholdTable);
    const tagRows = Object.entries(data.challenge_by_tag).map(([tag, values]) =>
      [{ negative: 'Отрицания', typo: 'Опечатки', mixed: 'Смешанные', vague: 'Мало информации', ood: 'Незнакомые темы',
        short: 'Короткие', long: 'Длинные', emotional: 'Эмоциональные', colloquial: 'Разговорные', irrelevant: 'Нерелевантные' }[tag],
      values.n, values.correct, values.wrong, values.manual]);
    const tags = panel('Стресс-тест по типам сообщений',
      table(['Тип', 'Всего', 'Верные советы', 'Ошибочные советы', 'Ручной разбор'], tagRows));
    container.replaceChildren(top, modelPane, decisions, ...(split === 'challenge' ? [tags] : []), policy);
  } catch (error) {
    if (generation === state.pageRequest) container.replaceChildren(element('p', error.message, 'field-error'));
  }
}

const economicFields = {
  volume: ['Обращения в месяц', 1, 1000000, 0],
  manual_seconds: ['Ручной выбор, с', 1, 86400, 1],
  accepted_seconds: ['Верная подсказка, с', .1, 86400, 0],
  correction_seconds: ['Исправление ошибки, с', .1, 86400, 0],
  abstention_seconds: ['Разбор после отказа, с', .1, 86400, 0],
  hourly_cost: ['Стоимость часа, ₽', .1, 1000000, 0],
  hours_per_fte: ['Часов на 1 FTE в месяц', .1, 744, 1],
  coverage: ['Охват модели, %', 'any', 100, 0, 100],
  precision: ['Точность подсказок, %', 'any', 100, 0, 100],
  monetized: ['Монетизация времени, %', 'any', 100, 0, 100],
  setup_cost: ['Внедрение, ₽', .1, 1000000000, 0],
  operation_cost: ['Эксплуатация в месяц, ₽', .1, 1000000000, 0],
  maintenance_cost: ['Сопровождение в месяц, ₽', .1, 1000000000, 0],
};

function fillEconomics(inputs) {
  const fields = Object.entries(economicFields).map(([key, [label, step, max, min, factor = 1]]) => {
    const wrapper = element('label', label, 'stack');
    const input = element('input');
    input.type = 'number';
    input.name = key;
    input.min = min;
    input.max = max;
    input.step = step;
    input.required = true;
    input.value = Number((inputs[key] * factor).toFixed(8));
    wrapper.append(input);
    return wrapper;
  });
  $('#economic-fields').replaceChildren(...fields);
}

function renderEconomics(r, entries) {
  const list = definitions([
    ['Время с подсказками', number(r.assisted_seconds) + ' с'],
    ['Сокращение времени', percent(r.time_reduction)],
    ['Высвобождаемое время', number(r.saved_hours) + ' ч/мес.'],
    ['Нагрузка до и после', number(r.current_fte) + ' / ' + number(r.target_fte) + ' FTE'],
    ['Высвобождаемая нагрузка', number(r.saved_fte * 100) + '% ставки'],
    ['Валовая стоимость времени', rub(r.gross_month_rub)],
    ['Монетизируемый эффект', rub(r.cash_month_rub)],
    ['Чистый эффект в месяц', rub(r.net_month_rub)],
    ['Чистый эффект первого года', rub(r.first_year_net_rub)],
    ['ROI первого года', percent(r.first_year_roi)],
    ['Окупаемость', r.payback_months == null ? 'Не окупается' : number(r.payback_months) + ' мес.'],
    ['Безубыточность в месяц', r.break_even_volume == null ? 'Недостижима' : number(r.break_even_volume) + ' обр./мес.'],
    ['Окупаемость за год при объёме', r.year_break_even_volume == null ? 'Недостижима' : number(r.year_break_even_volume) + ' обр./мес.'],
  ]);
  const info = element('p', 'Стоимость высвобожденного времени становится денежной экономией, если компания реально сокращает расходы или избегает найма.', 'muted');
  $('#economic-results').replaceChildren(list, info);
  $('#sensitivity').replaceChildren(table(['Изменение', 'Новое значение', 'На обращение', 'Чистый эффект/мес.', 'Разница'], entries.map(item =>
    [item.label, percent(item.value), number(item.seconds) + ' с', rub(item.net), rub(item.delta)])));
}

async function updateEconomics() {
  const generation = ++economicRequest;
  const form = $('#economics-form');
  const submit = $('button', form);
  const data = Object.fromEntries(new FormData(form));
  const inputs = Object.fromEntries(Object.entries(economicFields).map(([key, [, , , , factor = 1]]) => [key, Number(data[key]) / factor]));
  submit.disabled = true;
  showFieldError('#economic-error', null);
  try {
    const response = await request('/api/economics', { inputs });
    if (generation === economicRequest) renderEconomics(response.results, response.sensitivity);
  } catch (error) {
    if (generation === economicRequest) showFieldError('#economic-error', error);
  } finally {
    if (generation === economicRequest) submit.disabled = false;
  }
}

async function refreshEconomics() {
  const generation = ++state.pageRequest;
  $('#economic-results').replaceChildren(element('p', 'Загрузка сценария…', 'muted'));
  try {
    const data = await getQuality();
    if (generation !== state.pageRequest) return;
    const scenario = $('#scenario');
    if (scenario.value !== 'custom') fillEconomics(data.economics[scenario.value].inputs);
    if ($('#economics-form').checkValidity()) await updateEconomics();
    else $('#economic-results').replaceChildren(element('p', 'Проверьте входные параметры и пересчитайте сценарий.', 'muted'));
  } catch (error) {
    if (generation === state.pageRequest) $('#economic-results').replaceChildren(element('p', error.message, 'field-error'));
  }
}

function refreshPage() {
  if (state.view === 'analytics') return refreshAnalytics();
  if (state.view === 'quality') return refreshQuality();
  if (state.view === 'economics') return refreshEconomics();
  if (state.view === 'inbox' || state.view === 'history') return refreshList();
  return request('/api/health').catch(() => {});
}

function navigate() {
  const hash = location.hash.slice(1);
  if (hash === 'main') return;
  const view = Object.hasOwn(views, hash) ? hash : 'inbox';
  if (view === state.view) return;
  state.pageRequest++;
  state.listRequest++;
  clearDetail();
  state.view = view;
  const workspace = view === 'inbox' || view === 'history';
  for (const id of ['workspace', 'analytics', 'quality', 'economics', 'about']) {
    $('#' + id).hidden = id === 'workspace' ? !workspace : view !== id;
  }
  const history = view === 'history';
  $('#workspace-title').textContent = views[view];
  $('#workspace-description').textContent = history
    ? 'Обращения с сохранёнными решениями и журналом изменений.'
    : 'Проверьте рекомендацию модели и направьте обращение в очередь.';
  $('#list-title').textContent = history ? 'Решения оператора' : 'Входящие';
  $('#inbox-summary').hidden = history;
  $('#seed').hidden = history;
  $('#open-new').hidden = history;
  $('#open-import').hidden = history;
  $('#crumb').textContent = views[view];
  if (workspace) resetFilters();
  $$('[data-nav]').forEach(item => {
    if (item.dataset.nav === view) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  });
  refreshPage();
}

const keyFor = new Map();
function requestKey(kind, content) {
  const previous = keyFor.get(kind);
  if (previous?.content === content) return previous.key;
  const key = crypto.randomUUID();
  keyFor.set(kind, { content, key });
  return key;
}

function dialogForm(name, submitText, handler) {
  const dialog = $('#' + name + '-dialog');
  const form = $('form', dialog);
  const submit = $('button[type="submit"]', form);
  const controls = $$('input, textarea, button', form);
  const busy = active => {
    controls.forEach(control => { control.disabled = active; });
    submit.textContent = active ? 'Сохранение…' : submitText;
  };
  dialog.addEventListener('cancel', event => { if (submit.disabled) event.preventDefault(); });
  $$('[data-close]', dialog).forEach(close => close.addEventListener('click', () => dialog.close()));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    showFieldError('#' + name + '-error', null);
    busy(true);
    try {
      const afterClose = await handler();
      form.reset();
      dialog.close();
      if (afterClose) await afterClose();
    } catch (error) {
      showFieldError('#' + name + '-error', error);
    } finally {
      busy(false);
    }
  });
  return () => {
    showFieldError('#' + name + '-error', null);
    dialog.showModal();
  };
}

const newDialog = dialogForm('new', 'Сохранить и проанализировать', async () => {
  const value = $('#new-text').value.trim();
  if (!value) throw new Error('Введите текст обращения.');
  const item = await request('/api/tickets', { text: value, request_key: requestKey('new', value) });
  keyFor.delete('new');
  resetFilters('all');
  $('#text-count').textContent = '0 / 1000';
  return async () => {
    await refreshList();
    await openTicket(item.id, true);
    showMessage('Обращение #' + item.id + ' сохранено.');
  };
});

const importDialog = dialogForm('import', 'Импортировать', async () => {
  const file = $('#csv-file').files[0];
  if (!file || file.size > 590000) throw new Error('Выберите CSV-файл размером до 590 КБ.');
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let content;
  try { content = decoder.decode(await file.arrayBuffer()); }
  catch { throw new Error('Не удалось прочитать файл. Выберите CSV в UTF-8.'); }
  const data = await request('/api/import', { csv: content, request_key: requestKey('import', content) });
  keyFor.delete('import');
  resetFilters('all');
  await refreshList();
  showMessage('Импортировано обращений: ' + data.count + '.');
});

$('#open-new').addEventListener('click', newDialog);
$('#open-import').addEventListener('click', importDialog);
$('#new-text').addEventListener('input', event => {
  $('#text-count').textContent = event.target.value.length + ' / 1000';
  showFieldError('#new-error', null);
});
$('#seed').addEventListener('click', async event => {
  const seed = event.currentTarget;
  seed.disabled = true;
  try {
    const result = await request('/api/demo', {});
    resetFilters('demo');
    await refreshList();
    await openTicket(result.ids[1]);
    showMessage(result.created ? 'Загружено демо-обращений: ' + result.count + '.' : 'Демо-обращения уже есть в списке.');
  } catch (error) {
    if (error.status) $('#service-error-text').textContent = error.message;
    $('#service-error').hidden = false;
  } finally {
    seed.disabled = false;
  }
});
filters.addEventListener('submit', event => { event.preventDefault(); clearTimeout(filterTimer); state.offset = 0; refreshList(); });
filters.elements.q.addEventListener('input', () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => { state.offset = 0; refreshList(); }, 220);
});
filters.addEventListener('change', event => {
  if (event.target === filters.elements.q) return;
  clearTimeout(filterTimer);
  state.offset = 0;
  updateSummarySelection();
  refreshList();
});
$$('[data-status]').forEach(item => item.addEventListener('click', () => {
  filters.elements.status.value = item.dataset.status;
  state.offset = 0;
  updateSummarySelection();
  refreshList();
}));
$('#prev').addEventListener('click', () => { state.offset -= state.limit; refreshList(); });
$('#next').addEventListener('click', () => { state.offset += state.limit; refreshList(); });
$('#retry').addEventListener('click', async () => {
  try {
    await request('/api/health');
    await refreshPage();
    if (state.selected) await openTicket(state.selected);
  } catch { /* Ошибка уже показана. */ }
});
$('#analytics-scope').addEventListener('change', refreshAnalytics);
$('#quality-split').addEventListener('change', refreshQuality);
$('#scenario').addEventListener('change', refreshEconomics);
$('#economics-form').addEventListener('submit', event => { event.preventDefault(); updateEconomics(); });
$('#economics-form').addEventListener('input', () => {
  const scenario = $('#scenario');
  const custom = $('option[value="custom"]', scenario);
  custom.disabled = false;
  scenario.value = 'custom';
});
window.addEventListener('hashchange', navigate);
navigate();
