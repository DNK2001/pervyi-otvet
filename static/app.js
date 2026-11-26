const labels = {
  access: 'Доступ и аккаунт',
  payment: 'Оплата и возврат',
  schedule: 'Расписание занятий',
  materials: 'Учебные материалы',
  manual: 'Ручной разбор',
};

const examples = {
  access: 'Не получается войти в личный кабинет, забыл пароль.',
  payment: 'Хочу вернуть деньги за оплату курса.',
  schedule: 'Когда будет следующее занятие и где посмотреть расписание?',
  materials: 'Где найти запись урока и презентацию?',
  other: 'Здравствуйте! Хотелось бы обсудить партнёрство с вашей школой.',
};

const percent = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
const form = document.querySelector('#request-form');
const message = document.querySelector('#message');
const counter = document.querySelector('#counter');
const requestError = document.querySelector('#request-error');
const classify = document.querySelector('#classify');
const actionText = classify.querySelector('span');
const exampleButtons = document.querySelectorAll('[data-example]');
const result = document.querySelector('#result');
const emptyResult = document.querySelector('#empty-result');
const predictionStatus = document.querySelector('#prediction-status');
const recommendation = document.querySelector('#recommendation');
const recommendationLabel = document.querySelector('#recommendation-label');
const recommendedRoute = document.querySelector('#recommended-route');
const recommendationDetail = document.querySelector('#recommendation-detail');
const scoreList = document.querySelector('#score-list');
const decisionForm = document.querySelector('#decision-form');
const decision = document.querySelector('#decision');
const decisionStatus = document.querySelector('#decision-status');

function clearResult() {
  result.hidden = true;
  emptyResult.hidden = false;
  predictionStatus.textContent = '';
  decisionStatus.textContent = '';
}

function showError(description) {
  requestError.textContent = description;
  requestError.hidden = !description;
}

function updateMessage() {
  counter.textContent = `${message.value.length} / ${message.maxLength}`;
  message.removeAttribute('aria-invalid');
  showError('');
  clearResult();
}

function setBusy(busy) {
  classify.disabled = busy;
  message.readOnly = busy;
  actionText.textContent = busy ? 'Анализируем обращение…' : 'Определить очередь';
  for (const button of exampleButtons) button.disabled = busy;
}

function scoreRow(route, score) {
  const row = document.createElement('li');
  const description = document.createElement('div');
  description.className = 'score-text';
  const name = document.createElement('span');
  name.textContent = labels[route];
  const amount = document.createElement('span');
  amount.className = 'score-amount';
  amount.textContent = percent.format(score);
  description.append(name, amount);

  const track = document.createElement('div');
  track.className = 'score-track';
  track.setAttribute('aria-hidden', 'true');
  const fill = document.createElement('span');
  fill.className = 'score-fill';
  fill.style.width = `${score * 100}%`;
  track.append(fill);
  row.append(description, track);
  return row;
}

function showPrediction(prediction) {
  const needsReview = prediction.route === 'manual';
  const confidence = percent.format(prediction.confidence);
  const candidateName = labels[prediction.candidate];

  recommendation.classList.toggle('manual', needsReview);
  recommendationLabel.textContent = needsReview ? 'Требуется проверка' : 'Предложенная очередь';
  recommendedRoute.textContent = labels[prediction.route];
  recommendationDetail.textContent = needsReview
    ? `Наибольшая оценка ${confidence} у очереди «${candidateName}». Порог выбора ${percent.format(prediction.threshold)}.`
    : `Оценка модели ${confidence}.`;

  const scores = Object.entries(prediction.scores)
    .sort((first, second) => second[1] - first[1]);
  scoreList.replaceChildren(...scores.map(([route, score]) => scoreRow(route, score)));
  decision.value = prediction.route;
  emptyResult.hidden = true;
  result.hidden = false;
  predictionStatus.textContent = `${recommendationLabel.textContent} — ${recommendedRoute.textContent}.`;
}

message.addEventListener('input', updateMessage);

for (const button of exampleButtons) {
  button.addEventListener('click', () => {
    message.value = examples[button.dataset.example];
    updateMessage();
    message.focus();
  });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = message.value.trim();
  if (!text) {
    message.setAttribute('aria-invalid', 'true');
    showError('Введите текст обращения.');
    message.focus();
    return;
  }

  showError('');
  clearResult();
  setBusy(true);
  try {
    const response = await fetch('/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const prediction = await response.json();
    if (!response.ok) {
      showError(prediction.error);
      return;
    }
    showPrediction(prediction);
  } catch {
    showError('Не удалось получить рекомендацию. Проверьте, запущен ли локальный сервер.');
  } finally {
    setBusy(false);
  }
});

decision.addEventListener('change', () => { decisionStatus.textContent = ''; });

decisionForm.addEventListener('submit', (event) => {
  event.preventDefault();
  decisionStatus.textContent = decision.value === 'manual'
    ? 'Выбран ручной разбор.'
    : `Выбрана очередь «${labels[decision.value]}».`;
});

updateMessage();
