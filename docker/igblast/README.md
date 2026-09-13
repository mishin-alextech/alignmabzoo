# Поставка IgBLAST для V(D)J

Этот каталог — локальный build context для V(D)J-образа. Репозиторий
намеренно не содержит бинарный архив IgBLAST, IMGT FASTA, BLAST-индексы или
готовые профили: на текущий момент для них не утверждены конкретные release,
лицензионные notices и SHA-256.

Обычная сборка приложения выполняется без V(D)J-инструмента:

```bash
docker compose build dev-alignmabzoo
```

Она создаёт `/opt/igblast/profiles/UNAVAILABLE`; V(D)J API обязан вернуть
русский статус недоступности и не запускать внешний процесс.

## Утверждённая поставка

После отдельной проверки артефактов их кладут **локально, до Docker build**:

```text
docker/igblast/
├── dist/
│   └── <проверенный-linux-igblast-архив>.tar.gz
├── igblast.sha256
└── profiles/
    ├── manifest.json
    ├── SHA256SUMS
    ├── hu/
    ├── ms/
    ├── rb/
    └── rt/
```

`igblast.sha256` имеет обычный формат `sha256sum --check` и содержит ровно
одну запись для файла из `dist/`. В архиве должны быть исполняемые файлы
`igblastn` и `makeblastdb`. URL, версия, дата получения, лицензия и SHA-256
записываются в `profiles/manifest.json` и в утверждённый журнал поставки.
Dockerfile не получает их из сети и не выбирает «последнюю» версию сам.

V(D)J-образ разрешено собрать только явно:

```bash
docker compose build --build-arg IGBLAST_REQUIRED=1 dev-alignmabzoo
```

Сборка обязана остановиться, если нет архива, checksum-файла, общего manifest,
любой из папок `hu`, `ms`, `rb`, `rt` или если хотя бы одна checksum не
совпадает. После успешной сборки в runtime доступны только локальные
`/opt/igblast/bin/igblastn`, `/opt/igblast/bin/makeblastdb` и read-only
`/opt/igblast/profiles`.

Не добавляйте артефакты в Git без отдельно подтверждённого права на их
распространение. Нельзя заменять отсутствующий профиль базой другого вида и
нельзя использовать `-remote`.
