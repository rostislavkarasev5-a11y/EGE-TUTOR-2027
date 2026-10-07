#!/usr/bin/env bash
# Установка сайта EGE-TUTOR-2027 на чистый сервер Ubuntu 24.04 (ADR-0013).
#
# Запуск (в консоли сервера, от root или через sudo):
#   curl -fsSL https://raw.githubusercontent.com/rostislavkarasev5-a11y/EGE-TUTOR-2027/main/deploy/install-server.sh -o install.sh
#   sudo bash install.sh
#
# Свой домен вместо бесплатного адреса sslip.io:  sudo bash install.sh --domain tutor.example.ru
# Повторный запуск безопасен: данные и пароль сохраняются.
set -euo pipefail

install_docker() {
	# У многих провайдеров (например, Beget) Docker уже установлен из репозитория Docker:
	# тогда пакеты Ubuntu docker.io ставить нельзя, они конфликтуют с docker-ce.
	if command -v docker >/dev/null; then
		echo "      Docker уже установлен: $(docker --version)"
		if ! docker compose version >/dev/null 2>&1; then
			apt-get install -y -qq docker-compose-plugin >/dev/null 2>&1 ||
				apt-get install -y -qq docker-compose-v2 >/dev/null
		fi
	else
		apt-get install -y -qq docker.io docker-compose-v2 >/dev/null
	fi
	systemctl enable --now docker >/dev/null
	if ! docker compose version >/dev/null 2>&1; then
		echo "Не получилось установить docker compose. Пришли Claude скриншот этого окна." >&2
		return 1
	fi
}

check_ports_free() {
	# Порты 80 и 443 нужны сайту. Если их занимает другая программа (не наш Caddy),
	# лучше остановиться и сказать об этом, чем сломать чужой сайт.
	local busy
	busy=$(ss -ltnpH '( sport = :80 or sport = :443 )' 2>/dev/null | grep -v docker-proxy || true)
	if [[ -n "$busy" ]]; then
		echo "Порты 80/443 уже заняты другой программой:" >&2
		echo "$busy" >&2
		echo "Пришли Claude скриншот этого окна, ничего не удаляй." >&2
		return 1
	fi
}

main() {
	local domain=""
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--domain)
			domain="${2:?после --domain нужен адрес}"
			shift 2
			;;
		*)
			echo "Неизвестный параметр: $1" >&2
			return 1
			;;
		esac
	done

	if [[ $EUID -ne 0 ]]; then
		echo "Запусти так: sudo bash install.sh" >&2
		return 1
	fi
	if ! grep -q '^ID=ubuntu' /etc/os-release; then
		echo "Скрипт рассчитан на Ubuntu 24.04." >&2
		return 1
	fi

	echo "[1/6] Проверяю Docker и Git..."
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq
	apt-get install -y -qq git curl >/dev/null
	install_docker
	check_ports_free
	# Если на сервере уже включён файрвол ufw, открываем в нём порты сайта.
	# Сами мы ufw не включаем: на сервере могут работать другие программы.
	if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
		ufw allow OpenSSH >/dev/null
		ufw allow 80/tcp >/dev/null
		ufw allow 443/tcp >/dev/null
	fi

	echo "[2/6] Скачиваю программу..."
	local repo_url="https://github.com/rostislavkarasev5-a11y/EGE-TUTOR-2027.git"
	if [[ -d /opt/ege-tutor/.git ]]; then
		git -C /opt/ege-tutor fetch --quiet origin main
		git -C /opt/ege-tutor reset --quiet --hard origin/main
	else
		git clone --quiet --branch main "$repo_url" /opt/ege-tutor
	fi
	# shellcheck source=deploy/common.sh
	source /opt/ege-tutor/deploy/common.sh

	echo "[3/6] Готовлю настройки и папку для данных..."
	if [[ -z "$domain" ]]; then
		local ip
		ip=$(curl -fsS4 --max-time 10 https://api.ipify.org || true)
		if [[ ! "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
			echo "Не удалось узнать IP-адрес сервера. Запусти с параметром --domain." >&2
			return 1
		fi
		domain="${ip//./-}.sslip.io"
	fi
	install -d -m 700 "$EGE_ETC"
	printf 'EGE_SITE_ADDRESS=%s\n' "$domain" >"$EGE_ETC/compose.env"
	if [[ ! -s "$EGE_ETC/web.env" ]]; then
		(
			umask 077
			printf 'EGE_WEB_SECRET_KEY=%s\n' "$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')" \
				>"$EGE_ETC/web.env"
		)
	fi
	chmod 600 "$EGE_ETC/compose.env" "$EGE_ETC/web.env"
	install -d -o "$EGE_UID" -g "$EGE_UID" -m 700 "$EGE_DATA"

	echo "[4/6] Собираю сайт (несколько минут)..."
	compose build --pull app

	echo "[5/6] Пароль для входа на сайт."
	if [[ -s "$EGE_DATA/web/password.argon2" ]]; then
		echo "Пароль уже задан. Сменить: sudo bash $EGE_DIR/deploy/set-password.sh"
	else
		compose run --rm --no-deps app ege-web set-password </dev/tty
	fi
	compose up -d --remove-orphans

	echo "[6/6] Включаю автообновление и ночные копии базы..."
	install -m 644 "$EGE_DIR"/deploy/systemd/ege-tutor-*.service "$EGE_DIR"/deploy/systemd/ege-tutor-*.timer \
		/etc/systemd/system/
	systemctl daemon-reload
	systemctl enable --now ege-tutor-update.timer ege-tutor-backup.timer >/dev/null

	echo
	echo "Готово! Сайт: https://$domain"
	echo "Первый вход может занять минуту: сервер получает сертификат https."
}

main "$@"
