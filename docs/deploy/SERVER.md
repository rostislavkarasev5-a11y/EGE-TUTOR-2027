# Сайт на своём сервере (ADR-0013)

## Как устроено

```
браузер ──https──▶ Caddy (сертификат Let's Encrypt) ──▶ app: ege-web serve (FastAPI) ──▶ TutorApp
                                                         │
                                       /var/lib/ege-tutor ◀┘  база, хеш пароля, копии
```

- `Dockerfile` — образ сайта. Внутри нет секретов и личных данных.
- `deploy/docker-compose.yml` — контейнеры `app` и `caddy`; наружу открыты только 80 и 443.
- `/etc/ege-tutor/compose.env` — адрес сайта (`EGE_SITE_ADDRESS`).
- `/etc/ege-tutor/web.env` — секрет подписи cookie (`EGE_WEB_SECRET_KEY`), создаётся при установке.
- `/var/lib/ege-tutor` — личные данные (том `/data` в контейнере): `ege.db`, `web/password.argon2`,
  `backups/`, `private_content/`.

## Установка

Сервер: Ubuntu 24.04, 1 vCPU, 2 ГБ RAM, от 20 ГБ диска. В консоли сервера:

```bash
curl -fsSL https://raw.githubusercontent.com/rostislavkarasev5-a11y/EGE-TUTOR-2027/main/deploy/install-server.sh -o install.sh
sudo bash install.sh                      # адрес вида 203-0-113-10.sslip.io
sudo bash install.sh --domain my.site.ru  # или свой домен (A-запись на IP сервера)
```

Скрипт ставит Docker (или использует уже установленный), проверяет, что порты 80 и 443 свободны, скачивает репозиторий в `/opt/ege-tutor`, создаёт настройки,
спрашивает пароль для входа, запускает сайт и включает таймеры. Повторный запуск безопасен.

## Обслуживание

| Что | Как |
|---|---|
| Обновление | само: `ege-tutor-update.timer` раз в 10 минут проверяет `main` (копия базы перед обновлением) |
| Обновить сейчас | `sudo bash /opt/ege-tutor/deploy/update.sh --force` |
| Копия базы | сама: `ege-tutor-backup.timer` в 03:30, хранится 14 копий; на сайте — «Скачать копию базы» |
| Сменить пароль | `sudo bash /opt/ege-tutor/deploy/set-password.sh` (все сессии выходят) |
| Журнал | `journalctl -u ege-tutor-update` · `docker compose ... logs app` |

## Безопасность

- Вход только по паролю владельца, хеш Argon2; 5 неверных паролей — блокировка адреса на 15 минут.
- Cookie сессии: подписанная, `HttpOnly`, `Secure`, `SameSite=Lax`, 30 дней.
- Все формы с CSRF-токеном; заголовки CSP, HSTS, `X-Frame-Options: DENY`.
- Загрузки: только `.yaml`, `.csv`, `.zip`; архив проверяется (без `..` и абсолютных путей,
  до 500 файлов и 200 МБ); файлы к задачам берутся только из папки файла задач.
- Сервер сам забирает обновления из публичного репозитория: ключей от сервера нет ни в GitHub,
  ни у Claude.
