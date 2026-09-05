# AlignMabZoo

AlignMabZoo — самостоятельный сервис для обработки SnapGene `.dna` и GenBank
`.gb`/`.genbank` файлов с последовательностями моноклональных антител. Он
извлекает белковые цепи, выполняет нумерацию ANARCI (IMGT, Kabat и Chothia),
выравнивание Clustal Omega и показывает результат в веб-интерфейсе.

## Требования к хосту

- Docker Engine с Docker Compose v2;
- существующая внешняя Docker-сеть `internal-net`;
- исходные данные в `/home/bioinfo/synced_data/mabzoo`;
- каталог результатов `/home/bioinfo/containers/alignmabzoo/jobs` с правом
  записи для Docker.

Каталог `anarci-master` должен находиться в корне репозитория. Это локальный
артефакт build context с ANARCI и подготовленной HMM-базой `dat/HMMs`; Docker
образ устанавливает их при сборке. ANARCI не требуется устанавливать на хосте.

## Развёртывание

Все команды ниже выполняются из корня этого репозитория на Linux-хосте
развёртывания.

1. При необходимости создайте внешнюю сеть и каталог результатов:

   ```sh
   docker network create internal-net
   mkdir -p /home/bioinfo/containers/alignmabzoo/jobs
   ```

   Если сеть уже существует, первую команду выполнять не нужно.

2. До подключения конфигурации к Nginx замените единственный плейсхолдер
   `__DOMAIN__` в `nginx/alignmabzoo.conf` на домен развёртывания. Например,
   отредактируйте строку `server_name alignmabzoo.__DOMAIN__;`, затем подключите
   этот файл в конфигурацию вашего Nginx и примените его стандартным способом.
   Конкретный домен и TLS-настройки определяет администратор инфраструктуры.

3. Соберите образ:

   ```sh
   docker compose build
   ```

4. Обязательно, до запуска сервиса, проверьте внутри собранного образа ANARCI,
   HMM-базу, HMMER и Clustal Omega:

   ```sh
   docker compose run --rm --no-deps alignmabzoo sh -c 'python -c "import anarci; from pathlib import Path; hmm = Path(anarci.__file__).parent / \"dat\" / \"HMMs\" / \"ALL.hmm\"; assert hmm.is_file(), hmm" && ANARCI --help && hmmscan -h && clustalo --version'
   ```

   Команда должна завершиться с кодом `0`. Если нет, не запускайте сервис до
   устранения проблемы с образом или локальной поставкой `anarci-master`.

5. Запустите сервис:

   ```sh
   docker compose up -d
   ```

   Контейнер доступен внутри `internal-net` как `alignmabzoo:8000`; Nginx
   проксирует к нему HTTP-запросы. Для просмотра состояния контейнера используйте
   `docker compose ps` и `docker compose logs alignmabzoo`.

## Данные и результаты

`docker-compose.yml` монтирует исходные данные строго в режиме read-only:

| Назначение | Хост | Контейнер | Режим |
| --- | --- | --- | --- |
| Исходные данные | `/home/bioinfo/synced_data/mabzoo` | `/synced_data/mabzoo` | только чтение |
| Результаты job | `/home/bioinfo/containers/alignmabzoo/jobs` | `/app/jobs` | чтение/запись |

Приложение не создаёт, не изменяет и не удаляет файлы в
`/synced_data/mabzoo`. Каждая job получает UUID-каталог в `/app/jobs`, а реестр
`jobs_registry.json` хранится в корне этого каталога.

Обычный набор артефактов job:

```text
<job_id>/
├── parsed_chains.txt
├── chains_named.fasta
├── log.txt
├── log_valid_error.txt
├── report.json
├── anarci/
├── alignment/input.fasta
├── alignment/alignment.aln
└── alignment.json
```

Статусы: `queued → running → done | partial | failed`. Ошибка отдельного
входного файла фиксируется в `report.json` и `log.txt`, не прерывает остальные
файлы и приводит к `partial`. После перезапуска приложения сохранённые `running`
job переводятся в `failed` с причиной на русском языке. Одновременно запускаются
не более двух job; Clustal Omega для каждой использует один поток.

## HTTP API

Собранный React-интерфейс раздаётся самим FastAPI. Базовые маршруты API:

- `GET /api/health` — техническая доступность;
- `GET /api/animals`;
- `GET /api/animals/{code}/projects`;
- `GET /api/animals/{code}/projects/{project}/groups`;
- `POST /api/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}`;
- `GET /api/jobs/{id}/alignments`, `GET /api/jobs/{id}/exclusions`;
- `GET /api/jobs/{id}/log`, `GET /api/jobs/{id}/report`;
- `GET /api/jobs/{id}/alignment.aln` и
  `GET /api/jobs/{id}/anarci/{filename}` — скачивание артефактов.

`POST /api/jobs` принимает JSON с полями `name` (не более 200 символов) и
`selection` — выбором животных, проектов и групп из browse API.

## Примечание о проверках

Автоматические тесты, Docker-сборка и запуск контейнера не выполняются сами по
себе при изменении исходного кода. Перед вводом в эксплуатацию обязательна
проверка образа из шага 4; тесты запускаются только по явному решению команды.
