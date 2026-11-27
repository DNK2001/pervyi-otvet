import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const buildRoot = path.join(root, '.tmp', 'slides');
await fs.mkdir(buildRoot, { recursive: true });
const temporary = await fs.mkdtemp(path.join(buildRoot, 'run-'));
const output = path.join(root, 'docs', 'defense', process.env.PRESENTATION_NAME || 'PERVYI_OTVET.pptx');
const screenshot = process.env.DEMO_SCREENSHOT || path.join(root, '.tmp', 'workspace.png');
const artifactModule = process.env.ARTIFACT_TOOL;
const skill = process.env.PRESENTATION_SKILL_DIR;
const python = process.env.PRESENTATION_PYTHON;
if (!skill || !python) throw new Error('Set PRESENTATION_SKILL_DIR and PRESENTATION_PYTHON to the presentation runtime paths.');
const { FileBlob, Presentation, PresentationFile } = await import(artifactModule ? pathToFileURL(artifactModule).href : '@oai/artifact-tool');
const { finalizePresentation } = await import(pathToFileURL(path.join(skill, 'container_tools', 'artifact_tool_utils.mjs')).href);

const report = JSON.parse(await fs.readFile(path.join(root, 'docs', 'experiments', 'v2.json'), 'utf8'));
const test = report.comparison.test;
const best = report.release.algorithm;
const outcome = test[best];
const release = report.release;
const budget = report.economics.base.results;
const ru = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const pct = new Intl.NumberFormat('ru-RU', { style: 'percent', maximumFractionDigits: 1 });
const integer = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const money = value => integer.format(value) + ' ₽';
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const colors = { ink: '#15213A', muted: '#4B5B77', blue: '#254DC3', tint: '#EDF2FF', paper: '#FFFFFF', line: '#D8E1EF', dark: '#173887' };
const modelNames = { v1: 'Исходная модель', rules: 'Правила', naive_bayes: 'Naive Bayes', logistic: 'Logistic Regression', svm: 'Linear SVM' };

function text(slide, value, x, y, w, h, options = {}) {
  const shape = slide.shapes.add({
    name: options.name || value.slice(0, 60),
    geometry: 'textbox',
    position: { left: x, top: y, width: w, height: h },
    fill: 'none',
    line: { fill: 'none', width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: 'Arial', fontSize: options.size || 26, color: options.color || colors.ink,
    bold: options.bold || false, verticalAlignment: 'top', insets: 0, wrap: 'square',
  };
}

function slide(title, notes, subtitle) {
  const item = p.slides.add();
  item.background.fill = colors.paper;
  text(item, title, 74, 60, 1132, 68, { size: 46, bold: true });
  if (subtitle) text(item, subtitle, 76, 133, 1120, 40, { size: 21, color: colors.muted });
  item.speakerNotes.text = notes;
  return item;
}

function table(item, values, widths, y, rowHeight, selected) {
  const grid = item.tables.add({
    rows: values.length, columns: values[0].length, left: 76, top: y,
    width: widths.reduce((a, b) => a + b, 0), height: values.length * rowHeight,
    columnWidths: widths, values,
  });
  grid.borders.assign({ style: 'solid', fill: colors.line, width: 1 });
  for (let row = 0; row < values.length; row++) {
    grid.rows[row].height = rowHeight;
    const block = grid.cells.block({ row, column: 0, rowCount: 1, columnCount: values[0].length });
    block.assign({
      fill: row === 0 ? colors.dark : row === selected ? colors.tint : colors.paper,
      textStyle: { typeface: 'Arial', fontSize: row === 0 ? 20 : 23, bold: row === 0 || row === selected,
        color: row === 0 ? colors.paper : colors.ink },
      margins: { left: 12, top: 6, right: 10, bottom: 6 }, anchor: 'center',
    });
  }
}

function stat(item, value, caption, x, y, width) {
  text(item, value, x, y, width, 67, { size: 50, color: colors.blue, bold: true });
  text(item, caption, x, y + 71, width, 63, { size: 22, color: colors.muted });
}

const cover = p.slides.add();
cover.background.fill = colors.dark;
text(cover, 'Проект 0.25', 86, 72, 440, 40, { size: 23, color: '#D8E4FF' });
text(cover, 'Первый ответ', 83, 201, 1100, 112, { size: 86, bold: true, color: colors.paper });
text(cover, 'Маршрутизация обращений\nв поддержку онлайн-школы', 88, 331, 1000, 127,
  { size: 38, color: colors.paper });
text(cover, 'Учебный MVP', 88, 622, 540, 42, { size: 22, color: '#D8E4FF' });
cover.speakerNotes.text = '0:00–0:45. Назовите участников и опишите их фактический вклад. Цель — уменьшить активное время оператора на выбор очереди, сохраняя его ответственность.';

const context = slide('Нагрузка на первую линию',
  '0:45–1:50. В модели рассматриваем одну школу. Объём, среднее время и ставка — сценарные допущения. Ключевая метрика пилота — секунды активной работы до корректной очереди. Мы не оцениваем полное время решения вопроса. Источник: docs/PRODUCT_CONCEPT.md, docs/ECONOMICS.md.',
  'Расчёт для одного внедрения');
stat(context, '5 000', 'активных учащихся', 76, 217, 345);
stat(context, '6 000', 'обращений в месяц', 456, 217, 345);
stat(context, '150 ч', 'ручного выбора очереди в месяц', 835, 217, 335);
text(context, 'Оператор выбирает между четырьмя очередями. Сложные и неясные сообщения требуют отдельного разбора.', 76, 414, 1020, 105,
  { size: 29 });
text(context, 'В расчёте на одно обращение заложено 90 секунд.', 76, 556, 1120, 50, { size: 25, color: colors.muted });

const demo = slide('Рабочее место оператора',
  '1:50–4:10. Откройте браузер с запущенным app.py. Загрузите демо. Подтвердите очередь для двойного списания. Откройте партнёрство, покажите причину отказа и отметьте ручной разбор. В истории найдите обе записи. Если время позволяет, выберите очередь вручную для методички. На слайде снимок из локального браузерного теста с синтетическими сообщениями.');
text(demo, 'Двойное списание', 76, 177, 351, 37, { size: 24, bold: true, color: colors.blue });
text(demo, 'Модель предлагает очередь оплаты. Оператор подтверждает выбор.', 76, 226, 345, 117, { size: 27 });
text(demo, 'Запрос о партнёрстве', 76, 372, 365, 40, { size: 24, bold: true, color: colors.blue });
text(demo, 'Приложение сохраняет причину отказа. Оператор ставит обращение на разбор.', 76, 421, 345, 153, { size: 27 });
demo.images.add({ blob: await fs.readFile(screenshot), contentType: 'image/png', fit: 'contain',
  alt: 'Входящие и карточка подтверждённого демонстрационного обращения',
  position: { left: 447, top: 140, width: 755, height: 514 } });

const data = slide('Данные и выбор модели',
  '4:10–5:45. Укажите происхождение каждого набора. Первое сравнение на 125 новых тренировочных строках уступило v1. Добавили 120 исходных тренировочных примеров, сгруппировали сценарии и зафиксировали протокол до замера нового test. Пять фолдов с разделением по группам для sigmoid-калибровки. TF-IDF по символам и словам помогает при смене форм слов. Сравнили правила, исходную модель, Naive Bayes, логистическую регрессию и SVM. Источники: docs/DATA_METHOD.md, docs/ML_EXPERIMENT.md, https://scikit-learn.org/1.7/modules/calibration.html.',
  'Синтетические русскоязычные обращения');
stat(data, '245', 'обучение и калибровка', 76, 213, 245);
stat(data, '75', 'выбор модели и порога', 363, 213, 245);
stat(data, '90', 'итоговый тест', 650, 213, 245);
stat(data, '60', 'стресс-тест', 937, 213, 245);
text(data, 'Семейства сценариев разнесены по наборам. Словарь TF-IDF строится только на обучении.', 76, 383, 1090, 82, { size: 28 });
text(data, 'Naive Bayes выбрали на validation по ожидаемому времени и допустимой доле ошибок. Порог зафиксирован на ' + pct.format(release.threshold) + '.', 76, 489, 1120, 87, { size: 28 });

const comparison = slide('Результаты итогового теста',
  '5:45–7:05. Все модели сравниваем на одних и тех же 90 текстах. Selective Accuracy считает долю верных среди выданных советов. Ошибки в потоке делим на 90. Правила безопаснее на этом тесте, но дают заметно меньше подсказок. Логистическая регрессия получила более высокий macro-F1 на test, её не выбирали после просмотра test. Источник: docs/experiments/v2.json.',
  '90 сообщений, из них 18 вне поддерживаемых очередей');
const headings = ['Подход', 'Охват', 'Точность подсказок', 'Ошибки в потоке'];
const ordered = ['v1', 'rules', 'naive_bayes', 'logistic', 'svm'];
table(comparison, [headings, ...ordered.map(name => [modelNames[name], pct.format(test[name].coverage),
  pct.format(test[name].precision), pct.format(test[name].wrong_share)])], [394, 179, 278, 271], 197, 49, ordered.indexOf(best) + 1);
text(comparison, String(outcome.correct) + ' верных подсказок из ' + outcome.recommended +
  ' у Naive Bayes. Итоговый охват выше v1 на 18,9 п. п.', 76, 534, 1100, 75,
  { size: 26, bold: true });

const risk = slide('Ошибки и решение оператора',
  '7:05–8:10. Все семь ошибочных подсказок на test были по темам вне очередей. Показать пример te-086. На challenge смешанные обращения дали 3 ошибки из 13, отрицания — 1 из 9. Brier и ECE на тесте после калибровки выросли, поэтому численные оценки не переносим на реальные данные. Лимит 6% был условием validation и не подтверждён новым тестом. Источник: docs/ML_EXPERIMENT.md и docs/experiments/errors.csv.');
stat(risk, pct.format(outcome.wrong_share), 'ошибочные подсказки в итоговом тесте', 76, 184, 360);
stat(risk, '6%', 'ориентир при выборе порога на validation', 468, 184, 360);
stat(risk, '11 из 18', 'отказов по темам вне очередей', 860, 184, 344);
text(risk, '«Меня оценили по критериям другой специализации, как пересмотреть результат?»', 76, 380, 1070, 88,
  { size: 29, bold: true });
text(risk, 'Модель предложила расписание. Запрос на пересмотр оценки требует ручного разбора.', 76, 486, 1100, 73,
  { size: 27, color: colors.muted });
text(risk, 'Очередь всегда выбирает оператор.', 76, 594, 1060, 43, { size: 26, color: colors.blue, bold: true });

const economy = slide('Экономика одного внедрения',
  '8:10–10:20. Структура исходов: 60 верных подсказок по 30 с, 7 ошибочных по 120 с, 23 разбора по 100 с. Разделить сумму на 90. 160 ч/мес. на FTE, 800 ₽/ч, внедрение 90 тыс. ₽, обслуживание 12 тыс. ₽ в месяц. Монетизация 65%. В браузере сменить сценарий. При 0% монетизации денежный эффект равен ежемесячным затратам со знаком минус. Источник: docs/ECONOMICS.md и docs/experiments/v2.json.',
  'Базовый сценарий при 6 000 обращений в месяц');
stat(economy, '90 и ' + ru.format(budget.assisted_seconds) + ' с', 'время до и после внедрения', 76, 198, 365);
stat(economy, '0,94 и 0,57', 'FTE до и после внедрения', 463, 198, 375);
stat(economy, money(budget.net_month_rub), 'чистый прогноз в месяц', 855, 198, 345);
text(economy, '90 000 ₽ внедрение и 12 000 ₽ в месяц за эксплуатацию и сопровождение.', 76, 377, 1100, 45,
  { size: 27 });
text(economy, 'При 65% монетизации окупаемость 4,88 месяца. ROI за год 56,0%.', 76, 452, 1125, 50, { size: 26, bold: true });
text(economy, 'Пессимистичный сценарий даёт убыток около 9 233 ₽ в месяц.', 76, 540, 1100, 50, { size: 24, color: colors.muted });

const pilot = slide('Проверка перед внедрением',
  '10:20–11:30 и до 14:00 вопросы. Перед сдачей добавьте фактический вклад каждого студента в AI_DISCLOSURE.md, подтвердите согласование темы и источников, предоставьте преподавателю ссылку и права чтения. Воспроизведите запуск из свежей копии до защиты. Раскройте синтетическое происхождение данных и отсутствие пользовательских замеров.');
text(pilot, 'Независимая разметка', 76, 187, 360, 37, { size: 25, bold: true, color: colors.blue });
text(pilot, 'Два участника размечают новые обращения. Арбитр согласует спорные случаи.', 76, 239, 495, 125, { size: 29 });
text(pilot, 'Замер работы оператора', 647, 187, 524, 37, { size: 25, bold: true, color: colors.blue });
text(pilot, 'Сопоставимые наборы вручную и с подсказками. Измеряем время и ошибки очереди.', 647, 239, 520, 125, { size: 29 });
text(pilot, 'Вклад генеративного ИИ', 76, 415, 670, 40, { size: 25, bold: true, color: colors.blue });
text(pilot, 'OpenAI Codex использовался для кода, синтетических данных, тестов и материалов. Фактический вклад команды фиксируется по правкам и замерам.', 76, 465, 1120, 116, { size: 27 });
text(pilot, 'Классификация в приложении выполняется локально в scikit-learn.', 76, 594, 1120, 59, { size: 23, color: colors.muted });

await fs.mkdir(path.dirname(output), { recursive: true });
const candidatePath = path.join(temporary, 'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidatePath);
const requirements = { explicitTotalSlideCount: 8, requiredNativeTableOwnerSlides: [5] };
await finalizePresentation({
  ...requirements, workspaceDir: root, candidatePath, finalPath: output, pythonExecutable: python,
  integrityValidatorPath: path.join(skill, 'container_tools', 'inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(skill, 'container_tools', 'inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu', '12192000,6858000', '--validate-heading-fit', '--require-native-table-slide', '5'],
  fontPolicy: { basis: 'design', families: ['Arial'] }, verifyArtifactToolImport: true,
  receiptPath: path.join(temporary, 'validation.json'),
});
const final = await PresentationFile.importPptx(await FileBlob.load(output));
for (const [index, item] of final.slides.items.entries()) {
  const preview = await final.export({ slide: item, format: 'png', scale: 1 });
  await fs.writeFile(path.join(temporary, 'slide-' + (index + 1) + '.png'), new Uint8Array(await preview.arrayBuffer()));
}
console.log('Presentation renders saved in ' + temporary);
