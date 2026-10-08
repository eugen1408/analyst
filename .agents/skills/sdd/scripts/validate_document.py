#!/usr/bin/env python3
"""Validate Markdown artifacts against the bundled templates, using only stdlib.

Checks structure, not meaning or Mermaid syntax. Does not modify input files.
"""

import argparse
import json
import re
from pathlib import Path


SECTIONS = {
    "business": (
        "Контекст и цель", "Роли пользователей", "Пользовательские сценарии",
        "Сообщения и уведомления", "Бизнес-ограничения и допущения",
    ),
    "system": (
        "Архитектурный обзор", "Модель данных", "Интеграции", "Безопасность",
        "Открытые допущения", "Покрытие требований и проверка",
    ),
    "spec": (
        "Источники и основания", "Обзор", "Пользовательская история",
        "Критерии приемки", "Требования к данным и API",
        "Пограничные случаи и обработка ошибок", "Зависимости и риски",
        "Заметки по тестированию", "Покрытие требований", "Открытые вопросы",
        "Заметки по реализации",
    ),
    "epic": (
        "Источники и основания", "Обзор", "Пользовательская история верхнего уровня",
        "Архитектурный контекст", "Части эпика", "Зависимости между частями",
        "Критерии готовности эпика", "Покрытие требований",
        "Открытые вопросы эпика", "Заметки по реализации",
    ),
    "questions": (),
}
DIAGRAM_START = re.compile(
    r"^(?:flowchart|graph|sequenceDiagram|stateDiagram(?:-v2)?|erDiagram|"
    r"classDiagram|journey|gantt|pie|mindmap|timeline|C4Context|C4Container)\b"
)
PLACEHOLDER = re.compile(
    r"\[(?:TODO|TBD)[^\]\n]*\]|"
    r"\[(?:роль|функция|польза|конкретное действие|конкретное поведение|"
    r"конкретный сценарий|Ссылка[^\]\n]*|Другие задачи|Предварительные условия|"
    r"Специфичный критерий[^\]\n]*)\]"
)
ANGLE_TOKENS = {
    "название", "роль", "термин", "состояние", "событие", "условие",
    "ответственность", "источник", "компонент", "объекты", "тип", "ограничение",
    "действие", "статус", "результат", "часть", "контракт", "назначение",
    "метрика", "идентификатор", "основание", "данные", "требование",
    "task-key", "task-id", "feature-name", "part-name", "epic-name",
}


def has_placeholder(line):
    if PLACEHOLDER.search(line):
        return True
    for match in re.finditer(r"<([^<>\n]+)>", line):
        token = match[1].strip()
        if token.casefold() in ANGLE_TOKENS:
            return True
        # Russian instructional phrases, not autolinks, HTML or XML attributes.
        if (len(token.split()) > 1 and re.search(r"[А-Яа-яЁё]", token)
                and not re.search(r"[\"'=]", token)):
            return True
    return False


def strip_comments(line, in_comment):
    """Remove HTML comments outside fenced code, preserving original line numbers."""
    parts = []
    while line:
        if in_comment:
            closing = line.find("-->")
            if closing < 0:
                return "".join(parts), True
            line = line[closing + 3:]
            in_comment = False
        else:
            # Comment delimiters inside inline code are literal Markdown content.
            literals = [(match.start(), match.end())
                        for match in re.finditer(r"(`+).*?\1", line)]
            opening = next((match.start() for match in re.finditer(r"<!--", line)
                            if not any(start <= match.start() < end
                                       for start, end in literals)), -1)
            if opening < 0:
                parts.append(line)
                break
            parts.append(line[:opening])
            line = line[opening + 4:]
            in_comment = True
    return "".join(parts), in_comment


def normalize(title):
    return re.sub(r"^\d+[.)]\s*", "", title).strip().casefold().replace("ё", "е")


def validate(text, kind, stage):
    issues = []

    def add(rule, message, line=0, warning=False):
        issues.append({"level": "warning" if warning else "error",
                       "rule": rule, "line": line, "message": message})

    visible = []
    fence = None
    language = ""
    block = []
    block_line = 0
    in_comment = False
    for number, line in enumerate(text.splitlines(), 1):
        if not fence:
            line, in_comment = strip_comments(line, in_comment)
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence:
            if (marker and marker[1][0] == fence[0]
                    and len(marker[1]) >= len(fence) and not marker[2].strip()):
                meaningful = [value.strip() for value in block
                              if value.strip() and not value.lstrip().startswith("%%")]
                first = meaningful[0] if meaningful else ""
                if DIAGRAM_START.match(first) and language != "mermaid":
                    add("diagram-format", "Схема должна быть в блоке mermaid", block_line)
                if language == "mermaid" and not first:
                    add("empty-diagram", "Пустая схема Mermaid", block_line)
                fence = None
            else:
                block.append(line)
                if has_placeholder(line):
                    add("placeholder", "Осталась шаблонная заглушка в блоке кода",
                        number, stage == "draft")
            continue
        if marker:
            fence, language = marker[1], marker[2].strip().casefold()
            block, block_line = [], number
        else:
            visible.append((number, line))
    if fence:
        add("unclosed-fence", "Незакрытый блок кода", block_line)

    headers = {}
    for number, line in visible:
        match = re.match(r"^##\s+(.+)$", line)
        if match:
            title = normalize(match[1])
            if title in headers:
                add("duplicate-section", f"Повторный раздел: {match[1]}", number)
            headers[title] = number
    for title in SECTIONS[kind]:
        if normalize(title) not in headers:
            add("missing-section", f"Нет раздела: {title}")
    if not any(re.match(r"^#\s+\S", line) for _, line in visible):
        add("missing-title", "Нет заголовка документа")
    if kind != "questions":
        statuses = [(number, re.match(r"^\s*(?:-\s+)?\*\*Статус:\*\*\s*(.+)$", line))
                    for number, line in visible]
        statuses = [(number, match[1].strip()) for number, match in statuses if match]
        allowed = (("Черновик", "На согласовании", "Согласовано")
                   if kind in ("business", "system") else
                   ("Черновик", "На ревью", "Утверждено", "В работе", "Реализовано"))
        if not statuses:
            add("missing-status", "Нет статуса документа")
        elif statuses[0][1] not in allowed:
            add("document-status", "Не выбран допустимый статус документа", statuses[0][0])

    # Only explicit definitions count; mentions in prose and trace tables do not.
    definitions = {}
    section = ""
    for number, line in visible:
        header = re.match(r"^##\s+(.+)$", line)
        if header:
            section = normalize(header[1])
        identifier = re.match(r"^#{2,6}\s+((?:UC|Q)-\d+):", line)
        if not identifier:
            identifier = re.match(r"^\s*-\s+(?:\[[ xX]\]\s+)?(AC-\d+):", line)
        if not identifier and "покрытие" not in section:
            identifier = re.match(r"^\|\s*((?:BR|NFR)-\d+)\s*\|", line)
        if identifier:
            key = identifier[1]
            if key in definitions:
                add("duplicate-id", f"Повторное определение {key}", number)
            definitions[key] = number
        if has_placeholder(line):
            add("placeholder", "Осталась шаблонная заглушка", number, stage == "draft")

    if kind == "business" and not any(key.startswith("UC-") for key in definitions):
        add("missing-use-case", "Нет определения сценария UC-NN")
    if kind == "spec" and not any(key.startswith("AC-") for key in definitions):
        add("missing-acceptance", "Нет определения критерия AC-NN")

    # A question block ends at the next question or section of equal/higher level.
    for index, (number, line) in enumerate(visible):
        question = re.match(r"^(#{2,6})\s+(Q-\d+):", line)
        if not question:
            continue
        parts = []
        for _, following in visible[index + 1:]:
            next_header = re.match(r"^(#{1,6})\s", following)
            if next_header and len(next_header[1]) <= len(question[1]):
                break
            parts.append(following)
        fields = {field: "" for field in ("Приоритет", "Вопрос", "Статус", "Ответ")}
        for offset, value in enumerate(parts):
            found = re.match(r"^\*\*([^*\n]+):\*\*[ \t]*(.*)$", value)
            if not found or found[1] not in fields:
                continue
            values = [found[2]]
            if found[1] in ("Вопрос", "Ответ"):
                for continuation in parts[offset + 1:]:
                    if re.match(r"^\*\*[^*\n]+:\*\*|^#{1,6}[ \t]", continuation):
                        break
                    values.append(continuation)
            fields[found[1]] = "\n".join(values).strip()
        for field in ("Приоритет", "Вопрос", "Статус"):
            if not fields[field]:
                add("question-field", f"{question[2]}: не заполнено поле {field}", number)
        if fields["Статус"] and fields["Статус"] not in ("Открыт", "Отвечен"):
            add("question-status", f"{question[2]}: неизвестный статус", number)
        if fields["Приоритет"] and fields["Приоритет"] not in (
                "Блокирующее", "Высокое", "Среднее", "Низкое"):
            add("question-priority", f"{question[2]}: неизвестный приоритет", number)
        if fields["Статус"] == "Отвечен" and not fields["Ответ"]:
            add("missing-answer", f"{question[2]}: нет ответа", number)
        if fields["Приоритет"] == "Блокирующее" and fields["Статус"] == "Открыт":
            add("open-blocker", f"{question[2]}: открытый блокирующий вопрос",
                number, stage == "draft")

    errors = [value for value in issues if value["level"] == "error"]
    warnings = [value for value in issues if value["level"] == "warning"]
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--kind", choices=tuple(SECTIONS), required=True)
    parser.add_argument("--stage", choices=("draft", "final"), default="draft")
    args = parser.parse_args()
    try:
        text = args.document.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(json.dumps({"valid": False, "input_error": str(exc)}, ensure_ascii=False))
        return 2
    result = validate(text, args.kind, args.stage)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
