# Architecture Decision Records (ADR)

ADR — короткая запись одного архитектурного решения: контекст, решение, последствия.

Правила:
1. Любое изменение утверждённой архитектуры, стека, структуры данных или правил обучения оформляется новым ADR со статусом `Proposed`.
2. ADR становится `Accepted` только после явного подтверждения владельца проекта.
3. Принятые ADR не переписываются. Если решение меняется — новый ADR со ссылкой «Supersedes ADR-NNNN», а старый получает статус `Superseded`.
4. Шаблон — `0000-template.md`. Номера идут по порядку.

| № | Решение | Статус |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Фиксировать архитектурные решения в ADR | Accepted |
| [0002](0002-core-ports-and-ai-layer.md) | CORE + порты + TutorApp; ИИ предлагает, CORE решает | Accepted |
| [0003](0003-technology-stack.md) | Стек технологий и порядок подключения зависимостей | Accepted |
| [0004](0004-public-repository-and-private-data.md) | Публичный репозиторий, личные данные только локально | Accepted |
| [0005](0005-configuration-and-exam-dates.md) | Конфигурация в TOML + Pydantic, даты экзаменов TBD | Accepted |
| [0006](0006-mastery-v0-experimental.md) | Mastery v0 — экспериментальная конфигурируемая модель | Accepted |
| [0007](0007-task-source-metadata.md) | Метаданные источника задачи и пометка AI-задач | Accepted |
| [0008](0008-sandbox-on-windows.md) | Sandbox на Windows: Docker Desktop, запасной WSL2 | Accepted |
| [0009](0009-exam-mode-rules.md) | Правила Exam Mode | Accepted |
| [0010](0010-pyyaml-for-content.md) | PyYAML для файлов контента | Accepted |
| [0011](0011-import-batches-and-soft-rollback.md) | Импорт пачками, предпросмотр и мягкая отмена | Accepted |
| [0012](0012-attempts-and-answer-checking.md) | Попытки, подсказки и проверка кратких ответов | Accepted |
| [0013](0013-web-and-own-server.md) | Сайт на собственном сервере (VPS) | Accepted |
