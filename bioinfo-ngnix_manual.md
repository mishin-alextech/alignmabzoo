# Nginx и Docker-сервисы на bioinfo3

Этот документ описывает фактическую схему reverse proxy на сервере
`bioinfo3` по состоянию на 11 сентября 2026 года.

## Фактическая структура

Внешний reverse proxy — Docker-контейнер `nginx` на образе `nginx:1.23`, а не
системный сервис. Системный `nginx.service` может быть выключен: он не участвует
в публикации сайтов.

Контейнер публикует на хосте только входные порты `80` и `443` и подключён к
двум внешним сетям:

| Сеть | Назначение |
|---|---|
| `public-net` | Внешний вход в reverse proxy |
| `internal-net` | Связь reverse proxy с Docker-сервисами |

Конфигурация Nginx смонтирована одним файлом:

```text
/home/bioinfo/containers/nginx/nginx.conf
    -> /etc/nginx/nginx.conf
```

Других конфигурационных каталогов Nginx с хоста не примонтировано. Поэтому
`/etc/nginx/sites-available` и `sites-enabled` хоста не изменяют Docker Nginx.

## Как Nginx находит контейнеры

Nginx и backend-сервис должны состоять в `internal-net`. В `proxy_pass` нужно
использовать DNS-имя Docker-сервиса и внутренний порт контейнера:

```nginx
proxy_pass http://<compose-service>:<container-port>;
```

Примеры работающей схемы:

```nginx
proxy_pass http://alignmabzoo:8000;
proxy_pass http://frontend:3000;
proxy_pass http://backend:8000;
proxy_pass http://mabseq:5000;
```

`127.0.0.1` внутри контейнера Nginx — это сам контейнер Nginx, а не хост и не
другой контейнер. Поэтому для Docker backend нельзя указывать
`proxy_pass http://127.0.0.1:<порт>`.

## Добавление нового Docker-приложения

1. Подключить приложение к существующей внешней сети `internal-net`.

   ```yaml
   services:
     my-service:
       networks:
         - internal-net

   networks:
     internal-net:
       external: true
   ```

2. В `~/containers/nginx/nginx.conf` добавить отдельный `server` с уникальным
   `server_name`. Не изменять блок существующего production-сервиса.

   ```nginx
   server {
       listen 80;
       server_name dev-example.bioinfo3.immunochemistry.local;

       client_max_body_size 100m;

       location / {
           proxy_pass http://my-service:8000;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 300s;
           proxy_send_timeout 300s;
       }
   }
   ```

3. Добавить DNS-запись нового поддомена на IP этого сервера. Для HTTPS добавить
   сертификат и `listen 443 ssl` по существующему на сервере образцу; не заменять
   чужие сертификаты и default server.

4. Проверить и применить конфигурацию в контейнере:

   ```bash
   cd ~/containers/nginx
   cp nginx.conf nginx.conf.backup-$(date +%F-%H%M%S)
   docker exec nginx nginx -t
   docker exec nginx nginx -s reload
   ```

   Если `nginx -t` сообщает ошибку, восстановить backup до reload.

## Dev AlignMabZoo

Dev-сервис имеет Compose project и service `dev-alignmabzoo`, состоит в
`internal-net` и слушает внутри контейнера `8000`. Его Nginx-блок должен быть:

```nginx
server {
    listen 80;
    server_name dev-alignmabzoo.bioinfo3.immunochemistry.local;

    client_max_body_size 100m;

    location / {
        proxy_pass http://dev-alignmabzoo:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Production остаётся отдельным блоком:

```nginx
server_name alignmabzoo.bioinfo3.immunochemistry.local;
proxy_pass http://alignmabzoo:8000;
```

## Выбор портов

| Сценарий | Что делать |
|---|---|
| Обычный HTTP-сервис через Docker Nginx | Не использовать `ports`; подключить к `internal-net` и указать внутренний порт в `proxy_pass`. |
| Внешний веб-доступ | Только контейнер Nginx публикует host-порты `80` и `443`. |
| Локальная диагностика на хосте | Временно опубликовать `127.0.0.1:<host-port>:<container-port>`; это не является upstream для Docker Nginx. |
| Два backend-сервиса с одинаковым внутренним портом | Конфликта нет: Docker DNS направляет на разные контейнеры. |
| Два сервиса с одинаковым host-портом | Конфликт; host-порт должен быть уникальным либо не публиковаться. |

`expose` документирует внутренний порт, но не открывает его на хосте. При связи
через общую Docker-сеть он необязателен, однако полезен как описание контракта
сервиса.

## Диагностика

Проверить сети и mount конфигурации:

```bash
docker inspect nginx --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
docker inspect nginx --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}'
docker inspect <container> --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}'
```

Проверить итоговую конфигурацию и DNS из Nginx:

```bash
docker exec nginx nginx -T
docker exec nginx getent hosts dev-alignmabzoo
docker exec nginx wget -qO- http://dev-alignmabzoo:8000/api/health
```

Если сервис не находится по имени, сначала проверить, что оба контейнера в
`internal-net`, затем сверить имя Compose service через `docker compose config`.
