# AlignMabZoo

Production-конфигурация находится в `docker-compose.yml`. Для дальнейшей
разработки используется отдельный `docker-compose.dev.yml`; production и dev
не делят контейнеры, образы или каталог результатов.

Сервис извлекает белки из SnapGene `.dna` и GenBank `.gb`/`.genbank`, выполняет
ANARCI (IMGT, Kabat, Chothia), MSA Clustal Omega и показывает результат с CDR.
Python 3.12/FastAPI раздаёт собранный React 18/TypeScript/MUI/Vite frontend.

Production URL: `alignmabzoo.bioinfo3.immunochemistry.local`.
Dev URL: `dev-alignmabzoo.bioinfo3.immunochemistry.local`.

## Данные и ограничения

- Источник: `/home/bioinfo/synced_data/mabzoo:/synced_data/mabzoo:ro`.
- Production jobs: `/home/bioinfo/containers/alignmabzoo/jobs:/app/jobs`.
- Dev jobs: `/home/bioinfo/containers/alignmabzoo-dev/jobs:/app/jobs`.
  Совместное использование jobs-root запрещено.
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

Реестр `/app/jobs/jobs_registry.json` читает версии 1 и 2 и пишет версию 2.
Перед production-переключением нужно сохранить реестр версии 1: прежний образ
не сможет прочитать его после миграции.

## Viewer и API

Viewer поддерживает черновые исключения, повторное MSA, undo/redo, сортировку
CDR3 и ручной порядок. Скачивания и отчёт следуют за активной версией.
Экспорт панели сохраняет отображаемый порядок; файлы расчёта — нативный порядок
Clustal. Кластеризация MMseqs2 и локальный V(D)J-анализ IgBLAST запускаются как
отдельные производные job из выбранных в MSA последовательностей.

- `GET /api/health`;
- `GET /api/animals`, `/api/animals/{code}/projects`,
  `/api/animals/{code}/projects/{project}/groups`;
- `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`;
- `POST /api/jobs/{id}/realign` с `sequence_ids`;
- `POST /api/jobs/{id}/cluster` и `GET /api/jobs/{id}/clusters`;
- `POST /api/jobs/{id}/vdj` и `GET /api/jobs/{id}/vdj-results`;
- `GET /api/jobs/{id}/alignments`, `/exclusions`, `/log`, `/report`;
- `GET /api/jobs/{id}/alignments/{filename}` для четырёх пакетов;
- `GET /api/jobs/{id}/anarci`, `/api/jobs/{id}/anarci/{filename}`;
- `DELETE /api/jobs` с `job_ids` для завершённых job.

Dev получает MMseqs2 из последнего master; фактический SHA сохраняется в образе.
Для production этот проверенный SHA передаётся как `MMSEQS_GIT_REF`, чтобы
release-сборка не получила другой commit.

Тесты и вычислительные сценарии запускаются только по прямому указанию пользователя.
Импорты и сборка проверяют совместимость модулей, но не заменяют реальный pipeline.
Перед запуском нового образа обязательна проверка его утилит по deployment-инструкции.

## Установка production

Переключение выполнять, когда в production нет job со статусом `queued` или
`running`. Сначала сохранить реестр и текущий образ:

```bash
release_stamp=$(date +%Y%m%d-%H%M%S)
backup_root="/home/bioinfo/containers/alignmabzoo/backups/$release_stamp"
mkdir -p "$backup_root"
cp -a /home/bioinfo/containers/alignmabzoo/jobs/jobs_registry.json "$backup_root/jobs_registry.json"

old_container=$(docker ps -q \
  --filter label=com.docker.compose.project=alignmabzoo \
  --filter label=com.docker.compose.service=alignmabzoo)
test -n "$old_container"
old_image_id=$(docker inspect "$old_container" --format '{{.Image}}')
docker image tag "$old_image_id" "alignmabzoo:rollback-$release_stamp"
```

Получить production-код в отдельный checkout и закрепить SHA MMseqs2,
проверенный в dev:

```bash
cd /home/bioinfo/containers
git clone https://github.com/mishin-alextech/alignmabzoo.git alignmabzoo-release
cd alignmabzoo-release
git switch main
git pull --ff-only origin main

dev_container=$(docker ps -q \
  --filter label=com.docker.compose.project=dev-alignmabzoo \
  --filter label=com.docker.compose.service=dev-alignmabzoo)
mmseqs_sha=$(docker exec "$dev_container" cat /usr/local/share/mmseqs2-revision)
release_sha=$(git rev-parse --short=12 HEAD)
printf 'ALIGNMABZOO_IMAGE_TAG=%s\nMMSEQS_GIT_REF=%s\n' "$release_sha" "$mmseqs_sha" > .env

docker compose -p alignmabzoo config
docker compose -p alignmabzoo build --pull --no-cache alignmabzoo
```

До переключения проверить инструменты в собранном образе:

```bash
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo python -c 'import anarci; from pathlib import Path; assert (Path(anarci.__file__).parent / "dat/HMMs/ALL.hmm").is_file()'
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo ANARCI --help
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo hmmscan -h
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo clustalo --version
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo mmseqs version
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo igblastn -version
docker compose -p alignmabzoo run --rm --no-deps alignmabzoo sh -lc 'cd /opt/igblast/profiles && sha256sum --check SHA256SUMS'
```

Переключить контейнер и проверить health endpoint:

```bash
docker compose -p alignmabzoo up -d --no-deps alignmabzoo
docker compose -p alignmabzoo ps
docker compose -p alignmabzoo logs --tail 150 alignmabzoo
curl -fsS http://alignmabzoo.bioinfo3.immunochemistry.local/api/health
```

Nginx менять не требуется: production сохраняет DNS-имя
`alignmabzoo:8000` во внешней сети `internal-net`.

Для отката остановить новый контейнер, восстановить сохранённый
`jobs_registry.json`, записать `ALIGNMABZOO_IMAGE_TAG=rollback-<release_stamp>`
в `.env` и выполнить:

```bash
docker compose -p alignmabzoo up -d --no-deps --no-build alignmabzoo
```
