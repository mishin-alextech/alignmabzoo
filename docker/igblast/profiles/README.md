# Контракт IMGT-профилей IgBLAST

Профили должны быть подготовлены из утверждённых файлов IMGT до Docker build.
Dockerfile не вызывает загрузчик, `edit_imgt_file.pl` или `makeblastdb`: образ
получает уже проверенные FASTA, индексы и служебные данные.

`profiles/manifest.json` — один JSON-документ с `schema_version`, записью для
каждого profile ID (`hu`, `ms`, `rb`, `rt`), статусом `ready`, точным таксоном,
IMGT release/URL, версией IgBLAST, лицензией, датой получения и путями к
V/D/J-базам и `IGDATA`. Для тяжёлой цепи обязательны V/D/J; для kappa и lambda
— V/J.

`profiles/<id>/profile.json` — контракт непосредственно с backend. Он содержит
строковые поля `id`, `version`, `organism`, `v_db`, `d_db`, `j_db` и
`auxiliary_data`. Последние четыре значения должны быть абсолютными путями
внутри `/opt/igblast`, например
`/opt/igblast/profiles/hu/databases/imgt_hu_v` и
`/opt/igblast/profiles/hu/igdata/optional_file/human_gl.aux`. Backend отвергает
внешние пути и не подставляет базы другого вида.

Каждая запись также содержит SHA-256 всех поставляемых файлов: исходных IMGT
FASTA, BLAST-индексов, `.aux`, `.ndm.imgt`, `internal_data`, `optional_file` и
контрольного запроса. `SHA256SUMS` содержит checksum каждой такой поставляемой
файловой записи в формате `sha256sum --check`; README в него не включается.

Рекомендуемая структура одного профиля:

```text
profiles/<id>/
├── profile.json
├── databases/        # собственные V/D/J FASTA и BLAST-индексы
├── igdata/           # internal_data, optional_file, .aux, .ndm.imgt
└── validation/       # вход и ожидаемый результат контрольного запуска
```

Профиль считается `ready` только после локального запуска `igblastn` без
`-remote`, проверки контрольного результата и совпадения локуса. До этого он
имеет `blocked` и не может быть помещён в V(D)J-образ. Для остальных животных
потребуются отдельные profile ID и собственные IMGT-артефакты; подмена близким
видом запрещена.
