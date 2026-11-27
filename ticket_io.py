"""Импорт и выгрузка обращений в CSV."""

import csv
import io
import re

MAX_TEXT_LENGTH = 1000
MAX_BATCH = 100
REQUEST_KEY = re.compile(r"[a-fA-F0-9-]{8,64}\Z")
DEMO = (
    "Где проверить расписание занятий моей группы на октябрь?",
    "Два раза списали деньги за оплату курса, прошу вернуть лишний платёж.",
    "Скиньте, пожалуйста, видеозапись прошлой лекции и слайды.",
    "У меня новый ноутбук. Не могу войти в аккаунт, старый пароль не подходит.",
    "Мы хотим обсудить партнёрство и сотрудничество с вашей школой.",
    "Срочно!",
    "Не открывается методичка к итоговой работе. В аккаунт я вошла.",
    "Хочу перенести утренний урок на вечер пятницы, если есть свободное время.",
)


def message(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Введите текст обращения.")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"Допустимо до {MAX_TEXT_LENGTH} символов в обращении.")
    if "\x00" in value:
        raise ValueError("Текст содержит недопустимый символ.")
    return value.strip()


def csv_messages(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Выберите непустой CSV-файл в UTF-8.")
    sample = value.lstrip("\ufeff")
    try:
        header = sample.splitlines()[0]
        delimiter = ";" if ";" in header and "," not in header else ","
        reader = csv.DictReader(io.StringIO(sample, newline=""), delimiter=delimiter, strict=True)
        fields = reader.fieldnames or []
        if "text" not in fields or len(fields) != len(set(fields)):
            raise ValueError("CSV должен содержать столбец text с уникальным названием.")
        items = []
        for row in reader:
            if len(items) >= MAX_BATCH:
                raise ValueError(f"За раз можно импортировать до {MAX_BATCH} строк.")
            if None in row or None in row.values():
                raise ValueError(f"Строка {reader.line_num}: число полей не совпадает с заголовком.")
            try:
                items.append(message(row["text"]))
            except ValueError as error:
                raise ValueError(f"Строка {reader.line_num}: {error}") from error
    except (csv.Error, IndexError) as error:
        raise ValueError("Не удалось разобрать CSV. Проверьте разделитель и кавычки.") from error
    if not items:
        raise ValueError("CSV не содержит обращений.")
    return items


def spreadsheet_text(value):
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def export_csv(items):
    buffer = io.StringIO(newline="")
    fields = ("id", "text", "source", "created_at", "status", "recommendation", "score",
              "model_version", "operator_route", "changed", "elapsed_seconds")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for item in items:
        writer.writerow({key: spreadsheet_text(item[key]) if key == "text" else item[key] for key in fields})
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")
