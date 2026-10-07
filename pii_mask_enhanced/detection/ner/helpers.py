import re

TYPE_MAP = {"PER": "PERSON", "ORG": "ORG", "LOC": "LOC"}

# Граммемы личного имени в pymorphy: имя, фамилия, отчество.
NAME_GRAMMEMES = {"Name", "Surn", "Patr"}

# Термины, которые NER регулярно принимает за организацию или персону в резюме, вакансиях и служебной верстке.
STOP_TERMS = frozenset({
    "dwh", "data mart", "etl", "bi", "brd", "fsd", "lm", "sql", "ms sql",
    "powerbi", "power bi", "crm", "erp", "kpi", "api", "ui", "ux",
    "ml", "nlp", "ner", "llm", "genai", "rag", "mcp", "sdd", "ci/cd", "devops",
    "backend", "frontend", "fullstack", "qa", "ux/ui",
    "jira", "redmine", "confluence", "ms project", "mysql", "postgresql",
    "postgres", "mongodb", "clickhouse", "redis", "docker", "kubernetes",
    "laravel", "django", "react", "vue", "git", "gitlab", "github",
    "ollama", "claude", "claude api", "claude code", "openai api", "cursor",
    "langchain", "excel", "ms office", "figma", "notion", "trello", "asana",
    "hrbp", "t&d", "talent review", "performance review", "performance",
    "ispring", "power point", "powerpoint", "smart", "9-box", "ии", "ис",
    "obsidian", "sqlite", "onnx", "codex", "qwen", "ktalk", "linkedin", "vk",
    "google", "telegram", "whisper", "pert", "wbs", "субд", "cv", "pdf",
    "scrum", "kanban", "waterfall", "agile", "safe", "evm", "pmbok", "itil",
    "spec-driven development", "time & material", "fixed price",
    "product owner", "product manager", "project manager", "team lead",
    "tech lead", "delivery", "delivery/pm", "pm", "рп", "тимлид", "cto", "cio",
    "scrum master", "бизнес-аналитик", "системный аналитик",
    "ai", "it", "hr", "ib", "иб", "ит", "nda", "p&l", "roi", "tco", "sla",
    "ткп", "тз", "нда", "гост", "ндс", "ооо", "ано", "ип",
    "инн", "кпп", "огрн", "огрнип", "окпо", "октмо", "оквэд", "бик",
    "снилс", "кбк", "уин","тмц", "пто", "егрюл", "егрип", "ндфл", "фсс", "пфр", "омс", "усн",
    "осно", "envd", "енвд", "кудир", "тк рф", "гк рф", "жкх", "смр", "окс",
    "кс-2", "кс-3", "тору", "зуп", "мсфо", "рсбу", "авр", "первичка",
    "саше","специализации", "специализация", "занятость", "планирование",
    "анализ данных", "навыки", "образование", "опыт работы", "транскрипт",
    "ключевые навыки", "о себе", "достижения", "проекты", "портфолио",
})

# компания, чье название начинается со стоп-термина ("AI-Systems"), перестаёт маскироваться
TERM_TAIL = re.compile(r"[-/].*$")

# должность за названием работодателя ("Северная Торговая Компания - логист")
ROLE_TAIL = re.compile(r"\s+[-–—]\s+[а-яёa-z][^\n]*\Z")

# фикс разметки, которая сбивает сегментацию slovnet
MD_LINE_EDGE = re.compile(r"^[ \t]*[#+|]+[ \t]*|[ \t]*[#|]+[ \t]*$", re.M)
MD_INLINE = re.compile(r"[|`]")
# перевод строки после строки, не оканчивающейся знаком препинания
LINE_BREAK = re.compile(r"(?<=[^\s.!?:;,\-|>])\n")

CAPS_RUN = re.compile(r"[А-ЯЁA-Z]{2,}(?:[-'][А-ЯЁA-Z]{2,})*")

# кусок названия
JUNK_INSIDE = re.compile(r"[+*/\\|]|\*\*")

# спан, начинающийся с отглагольного существительного
DUTY_HEAD = re.compile(
    r"^(?:полн\w+\s+)?(?:организация|ведение|проведение|подготовка|заключение"
    r"|обучение|консультирование|проверка|контроль|составление|оформление"
    r"|сопровождение|формирование|планирование|управление|взаимодействие"
    r"|обеспечение|разработка|внедрение|сдача|прием|учет|анализ)\b",
    re.IGNORECASE)

    # строка перечня инструментов
STACK_LINE = re.compile(
    r"[ \t>*-]*(?:стек|навыки|инструменты|технологии|hard skills|tech stack"
    r"|владею|знание инструментов|дополнительно|языки и библиотеки"
    r"|базы данных|бд|аналитика|визуализация)[^:\n]{0,60}[:：]", 
    re.IGNORECASE)