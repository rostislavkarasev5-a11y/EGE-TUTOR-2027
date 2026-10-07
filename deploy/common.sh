# Общие настройки для скриптов сервера. Подключается через source.
# shellcheck shell=bash
# Переменные используют скрипты, которые подключают этот файл.
# shellcheck disable=SC2034

EGE_DIR="/opt/ege-tutor"
EGE_ETC="/etc/ege-tutor"
EGE_DATA="/var/lib/ege-tutor"
EGE_UID=10001

compose() {
	docker compose --env-file "$EGE_ETC/compose.env" -f "$EGE_DIR/deploy/docker-compose.yml" "$@"
}

log() {
	echo "[ege-tutor $(date '+%Y-%m-%d %H:%M:%S')] $*"
}
