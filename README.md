# AlignMabZoo — dev

Эта ветка развивает `dev-alignmabzoo`. Production зафиксирован в `main`; изменения
dev не предназначены для автоматического обновления production.

Сервис извлекает белки из SnapGene `.dna` и GenBank `.gb`/`.genbank`, выполняет
ANARCI (IMGT, Kabat, Chothia), MSA Clustal Omega и показывает результат с CDR.
Python 3.12/FastAPI раздаёт собранный React 18/TypeScript/MUI/Vite frontend.

Dev URL: `dev-alignmabzoo.bioinfo3.immunochemistry.local`. Запуск и обновление:
[docs/dev-deployment.md](docs/dev-deployment.md).
Исправления и проверка: [docs/dev-fixes-2026-09-11.md](docs/dev-fixes-2026-09-11.md).

## Данные и ограничения

- Источник: `/home/bioinfo/synced_data/mabzoo:/synced_data/mabzoo:ro`.
- Dev jobs: `/home/bioinfo/containers/alignmabzoo-dev/jobs:/app/jobs`.
  Общий с production jobs-root запрещён.
- Один ASGI worker, максимум две обычные или производные job, Clustal с одним
  потоком, лимит контейнера 2 CPU без memory limit.
- Сохраняются биологические правила: минимум 80 aa, кандидаты из features,
  расширенный naming. Это уточнение пользователя от 11 сентября 2026 года.
- Пакеты MSA: `vheavy` (VHeavy и VHH), `vkappa`, `vlambda`, `other`.
- UUID-каталог на job; ошибка файла не останавливает остальные записи.
  Частичный результат — partial, полный провал MSA — failed.
  После рестарта running переводятся в failed, queued возобновляются.

## Артефакты

Обычная job сохраняет `parsed_chains.txt`, `parsed_chains_nucleotide.txt`,
`chains_named.fasta`, `sequence_manifest.json`, `log.txt`,
`log_valid_error.txt`, `report.json`, `anarci/`, `alignment/`,
`alignment.json`. Непустые пакеты имеют `<пакет>.fasta` и `<пакет>.aln`;
одиночная строка тоже получает файл без запуска Clustal.

`parsed_chains.txt` содержит проект/группу/имя без вложенных каталогов.
Первый токен `chains_named.fasta` — технический ID, описание — нормализованное
имя. Manifest связывает ID, источник, имя и белково-нуклеотидную пару.
Нуклеотиды — ориентированная исходная feature, пока без проверенной проекции
кодонов для V(D)J.

Производная job использует сохранённые белки и нумерацию без нового парсинга или
ANARCI. У неё собственные MSA, JSON, manifest, FASTA, лог и отчёт с отдельными
пользовательскими исключениями. ANARCI CSV не пересоздаются: аннотации находятся
в `alignment.json`. Для старых job белок восстанавливается из MSA, неизвестные
источник и нуклеотиды не угадываются. Поле `msa_id` производного manifest
связывает legacy ID с безопасным FASTA-токеном. Удаление родителя блокируется,
пока производная job queued/running.

Реестр `/app/jobs/jobs_registry.json` читает версии 1 и 2, пишет версию 2.
Main не поддерживает этот формат; откат требует совместимой резервной копии
dev-реестра. Подключать его к production нельзя.

## Viewer и API

Viewer поддерживает черновые исключения, повторное MSA, undo/redo, сортировку
CDR3 и ручной порядок. Скачивания и отчёт следуют за активной версией.
Экспорт панели сохраняет отображаемый порядок; файлы расчёта — нативный порядок
Clustal. Кластеризация остаётся заглушкой, V(D)J — исследовательским этапом.

- `GET /api/health`;
- `GET /api/animals`, `/api/animals/{code}/projects`,
  `/api/animals/{code}/projects/{project}/groups`;
- `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`;
- `POST /api/jobs/{id}/realign` с `sequence_ids`;
- `GET /api/jobs/{id}/alignments`, `/exclusions`, `/log`, `/report`;
- `GET /api/jobs/{id}/alignments/{filename}` для четырёх пакетов;
- `GET /api/jobs/{id}/anarci`, `/api/jobs/{id}/anarci/{filename}`;
- `DELETE /api/jobs` с `job_ids` для завершённых job.

По решению пользователя MMseqs2 собирается из последнего master; фактический SHA
сохраняется в образе. Установка инструмента не включает расчёт кластеров.

Тесты и вычислительные сценарии запускаются только по прямому указанию пользователя.
Импорты и сборка проверяют совместимость модулей, но не заменяют реальный pipeline.
Перед запуском нового образа обязательна проверка его утилит по deployment-инструкции.
