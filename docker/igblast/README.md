# Поставка IgBLAST для V(D)J

Dev-образ содержит зафиксированные исходные архивы:

- NCBI IgBLAST `1.22.0`, Linux x64:
  `https://ftp.ncbi.nlm.nih.gov/blast/executables/igblast/release/1.22.0/ncbi-igblast-1.22.0-x64-linux.tar.gz`;
- IMGT/V-QUEST reference directory release `202631-1` от 27 июля 2026 года:
  `https://www.imgt.org/download/V-QUEST/IMGT_V-QUEST_reference_directory.zip`.

Контрольные суммы находятся в `igblast.sha256` и `imgt.sha256`. Docker build
проверяет их до распаковки. IMGT предоставляет данные по CC BY 4.0; лицензия
NCBI включена в архив IgBLAST и копируется в `/opt/igblast/NCBI-LICENSE`.

## Что создаётся при сборке

Для `hu`, `ms`, `rb`, `rt` Dockerfile берёт собственные IGHV/IGHD/IGHJ,
IGKV/IGKJ и IGLV/IGLJ из IMGT. Исходные FASTA сохраняются в
`profiles/<id>/databases/source/`. V, D и J объединяются отдельно, IMGT-gap
удаляются официальным `edit_imgt_file.pl`, затем `makeblastdb -parse_seqids`
создаёт нуклеотидные BLAST-индексы.

Из пакета IgBLAST в каждый профиль копируются соответствующие каталоги
`internal_data`, файл `<organism>_gl.aux` и `.ndm.imgt`. Итоговая структура
внутри контейнера:

```text
/opt/igblast/
├── bin/{igblastn,makeblastdb,edit_imgt_file.pl}
├── internal_data/
├── optional_file/
└── profiles/
    ├── manifest.json
    ├── SHA256SUMS
    ├── hu/{profile.json,databases/,igdata/}
    ├── ms/{profile.json,databases/,igdata/}
    ├── rb/{profile.json,databases/,igdata/}
    └── rt/{profile.json,databases/,igdata/}
```

`SHA256SUMS` для всех файлов готовых профилей создаётся и сразу проверяется
при сборке. `/opt/igblast` после этого переводится в read-only.

## Сборка на сервере

После `git pull` дополнительные загрузки не нужны:

```bash
docker compose build --no-cache dev-alignmabzoo
docker compose -p dev-alignmabzoo up -d dev-alignmabzoo
```

Проверка установки:

```bash
docker compose -p dev-alignmabzoo exec dev-alignmabzoo igblastn -version
docker compose -p dev-alignmabzoo exec dev-alignmabzoo makeblastdb -version
docker compose -p dev-alignmabzoo exec dev-alignmabzoo \
  sh -lc 'cd /opt/igblast/profiles && sha256sum --check SHA256SUMS'
```

Для диагностической сборки без V(D)J можно явно передать
`--build-arg IGBLAST_REQUIRED=0`. Такой образ создаёт marker
`/opt/igblast/profiles/UNAVAILABLE`, и backend возвращает статус
`unavailable` без запуска процесса.

Подмена профиля близким видом и использование `igblastn -remote` запрещены.
