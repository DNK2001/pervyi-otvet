import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const source = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(source ? pathToFileURL(path.resolve(source)).href : 'playwright');
const directory = await mkdtemp(path.join(tmpdir(), 'first-reply-test-'));
const python = process.env.APP_PYTHON || (process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const server = spawn(python, ['-B', 'app.py', '--port', '0', '--db', path.join(directory, 'test.sqlite3')], {
  stdio: ['ignore', 'pipe', 'pipe'],
});
const closed = new Promise(resolve => server.once('close', resolve));
let browser;
try {
  const url = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Backend startup timed out')), 12000);
    let output = '';
    server.stderr.on('data', data => { output += data; });
    server.once('error', reject);
    server.once('close', code => reject(new Error('Backend exited ' + code + ' ' + output)));
    server.stdout.on('data', chunk => {
      const match = String(chunk).match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
  });
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, args: ['--disable-breakpad', '--disable-crash-reporter'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 980 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const nav = name => page.getByRole('navigation').getByRole('link', { name, exact: true }).click();
  const visible = (locator) => locator.waitFor({ state: 'visible', timeout: 7000 });
  await page.goto(url);
  await visible(page.getByText('Обращений пока нет.', { exact: false }));
  await page.getByRole('button', { name: 'Загрузить демо', exact: true }).click();
  await visible(page.getByText('Загружено демо-обращений: 8.'));
  await page.getByRole('button', { name: 'Подтвердить подсказку' }).click();
  await visible(page.getByText('Очередь сохранена.'));
  await page.getByText('История действий', { exact: true }).click();
  await visible(page.getByText('Очередь подтверждена · Оплата и возврат'));
  await page.getByText('История действий', { exact: true }).click();
  if (process.env.DEMO_SCREENSHOT) {
    await page.locator('#notice').waitFor({ state: 'hidden', timeout: 6000 });
    await page.screenshot({ path: process.env.DEMO_SCREENSHOT });
  }
  await page.locator('#queue-filter').selectOption('manual');
  await page.waitForFunction(() => document.querySelectorAll('#ticket-rows tr').length === 3);
  await page.getByRole('searchbox').fill('партнёрство');
  await page.waitForFunction(() => document.querySelectorAll('#ticket-rows tr').length === 1);
  await page.getByRole('button', { name: /Мы хотим обсудить партнёрство/ }).click();
  await visible(page.getByText('Без рекомендации'));
  await page.getByRole('button', { name: 'На ручной разбор' }).click();
  await visible(page.getByText('Обращение передано на ручной разбор.'));
  await nav('История');
  await page.waitForFunction(() => document.querySelectorAll('#ticket-rows tr').length === 2);
  await nav('Аналитика');
  await visible(page.getByRole('heading', { name: 'Пока нет данных' }));
  await page.locator('#analytics-scope').selectOption('demo');
  await visible(page.getByRole('heading', { name: 'Динамика по дням' }));
  await nav('Качество ИИ');
  await visible(page.getByRole('heading', { name: 'Матрица решений' }));
  assert.equal(await page.locator('canvas').count(), 3);
  await page.locator('#quality-split').selectOption('challenge');
  await visible(page.getByRole('heading', { name: 'Стресс-тест по типам сообщений' }));
  await nav('Экономика');
  await visible(page.getByText('ROI первого года'));
  await page.locator('#scenario').selectOption('pessimistic');
  await visible(page.getByText('Не окупается'));
  await page.getByRole('spinbutton', { name: 'Монетизация времени, %' }).fill('0');
  await page.getByRole('button', { name: 'Пересчитать' }).click();
  await visible(page.getByText(/−?14\s000\s?₽/).first());
  await nav('Обращения');
  await page.getByRole('button', { name: 'Новое обращение' }).click();
  await page.keyboard.type('   ');
  await page.getByRole('button', { name: 'Сохранить и проанализировать' }).click();
  await visible(page.getByText('Введите текст обращения.', { exact: true }));
  await page.getByRole('textbox', { name: 'Текст сообщения' }).fill('Нужна квитанция за платёж по курсу.');
  await page.getByRole('button', { name: 'Сохранить и проанализировать' }).click();
  await visible(page.getByRole('heading', { name: /Обращение #9/ }));
  assert.equal(await page.locator(':focus').getAttribute('id'), 'ticket-heading');
  await page.getByRole('combobox', { name: 'Очередь оператора' }).selectOption('payment');
  await page.getByRole('button', { name: 'Сохранить очередь' }).click();
  await visible(page.getByText('Очередь сохранена.'));
  await page.getByRole('button', { name: 'Импорт CSV' }).click();
  const template = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Скачать шаблон CSV' }).click();
  assert.equal((await template).suggestedFilename(), 'template.csv');
  const file = page.locator('#csv-file');
  await file.setInputFiles({ name: 'bad.csv', mimeType: 'text/csv', buffer: Buffer.from('wrong\nvalue\n') });
  await page.getByRole('button', { name: 'Импортировать' }).click();
  await visible(page.getByText(/CSV должен содержать столбец text/));
  await file.setInputFiles({ name: 'valid.csv', mimeType: 'text/csv', buffer: Buffer.from('text\nНужна запись урока\n') });
  await page.getByRole('button', { name: 'Импортировать' }).click();
  await visible(page.getByText('Импортировано обращений: 1.'));
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Выгрузить' }).click();
  assert.equal((await download).suggestedFilename(), 'tickets.csv');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: /Нужна запись урока/ }).click();
  await visible(page.getByRole('heading', { name: 'Обращение #10' }));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
  await context.setOffline(true);
  await page.getByRole('button', { name: 'Загрузить демо' }).click();
  await visible(page.getByText(/Локальный сервер недоступен/));
  await context.setOffline(false);
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await visible(page.getByText('Локальный режим'));
  assert.deepEqual(errors, []);
  console.log('Passed Chromium UI workflows at 1440px and 390px');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
  await closed;
  await rm(directory, { recursive: true, force: true });
}
