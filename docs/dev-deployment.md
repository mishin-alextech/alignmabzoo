# Deployment отдельного dev-alignmabzoo

Production зафиксирован в main и не обновляется этими командами. Выполнять их
только из отдельного dev checkout ветки feature/parser-nucleotide-manifest.

| Настройка | Dev |
|---|---|
| Compose project / service | `dev-alignmabzoo` / `dev-alignmabzoo` |
| Образ | `dev-alignmabzoo:local` |
| Jobs на хосте | `/home/bioinfo/containers/alignmabzoo-dev/jobs` |
| Источник | `/home/bioinfo/synced_data/mabzoo:/synced_data/mabzoo:ro` |
| Сеть контейнера | `internal-net` |
| Nginx upstream | `127.0.0.1:5000` |
| Host-порт | `127.0.0.1:5000` |
| Nginx шаблон | `nginx/dev-alignmabzoo.conf` |

В `.env` dev можно задать `ALIGNMABZOO_DEV_PORT=5000` и
`ALIGNMABZOO_DEV_IMAGE_TAG=local`. Другой свободный порт разрешает конфликт bind.
Общий Nginx установлен на хосте, поэтому он обращается к
`127.0.0.1:<порт>`, а не к Docker DNS. Loopback-публикация не открывает dev
извне напрямую: доступ даёт только отдельный Nginx virtual host.

## Существующий dev-контейнер

Перед обновлением проверить Compose labels, mounts, image и ports фактического
dev-контейнера. Одного container name недостаточно. Явный `-p dev-alignmabzoo`
ниже исключает выбор production project из переменных оболочки, но не мигрирует
контейнер, ранее запущенный через docker run или другой Compose project/service.
В таком случае отдельно заменяется именно старый dev; он может продолжать занимать
5000. Не использовать down общего проекта alignmabzoo или remove-orphans.

Команды чтения состояния:

```sh
git branch --show-current
git rev-parse HEAD
docker compose -p dev-alignmabzoo config
docker compose ls
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
```

Затем `docker inspect <фактическое-имя-dev>`. До обновления сохранить резервную
копию dev jobs: новый код пишет реестр v2, прежние main/dev v1 его не читают.
Production jobs и реестр не использовать и не изменять.

## Последняя версия MMseqs2

По решению пользователя используется master. Для получения новой ревизии без
старого слоя с git fetch:

```sh
docker compose -p dev-alignmabzoo build --pull --no-cache dev-alignmabzoo
```

Обычная сборка с cache может сохранить прежнюю версию. Фактический SHA находится
в `/usr/local/share/mmseqs2-revision`. Новый upstream может потребовать обновления
сборочных зависимостей; каждый полученный образ проверяется перед запуском.

Обязательные проверки одноразовым dev-контейнером, без запуска job и публикации портов:

```sh
docker compose -p dev-alignmabzoo run --rm --no-deps dev-alignmabzoo python -c 'import anarci; from pathlib import Path; assert (Path(anarci.__file__).parent / "dat/HMMs/ALL.hmm").is_file()'
docker compose -p dev-alignmabzoo run --rm --no-deps dev-alignmabzoo ANARCI --help
docker compose -p dev-alignmabzoo run --rm --no-deps dev-alignmabzoo hmmscan -h
docker compose -p dev-alignmabzoo run --rm --no-deps dev-alignmabzoo clustalo --version
docker compose -p dev-alignmabzoo run --rm --no-deps dev-alignmabzoo mmseqs version
docker compose -p dev-alignmabzoo run --rm --no-deps dev-alignmabzoo cat /usr/local/share/mmseqs2-revision
```

После успешных проверок и сопоставления существующего dev deployment с новой конфигурацией:

```sh
docker compose -p dev-alignmabzoo up -d --no-deps dev-alignmabzoo
docker compose -p dev-alignmabzoo ps
docker compose -p dev-alignmabzoo logs --tail 100 dev-alignmabzoo
```

Production Nginx-шаблон сохранён. Dev публикуется отдельно как
`dev-alignmabzoo.bioinfo3.immunochemistry.local` через
`nginx/dev-alignmabzoo.conf`, проксирующий на `127.0.0.1:5000`. DNS и TLS
настраиваются отдельно. Сам файл в репозитории не меняет действующую конфигурацию
Nginx.

Реестр и очередь требуют ровно одного ASGI worker. Не переопределять CMD на два
workers и не запускать несколько контейнеров с одним jobs-root. Две вычислительные
job используют общий семафор. CPU dev ограничен двумя, но память/диск общие;
сборка образа не подчиняется runtime-ограничению cpus.
