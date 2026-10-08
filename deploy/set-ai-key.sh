#!/usr/bin/env bash
# Подключить ИИ (Yandex AI Studio, ADR-0017): записать ключ и каталог в настройки сервера
# и перезапустить сайт. Ключ вводится скрыто и хранится только в /etc/ege-tutor/web.env.
#
# Запуск:  sudo bash /opt/ege-tutor/deploy/set-ai-key.sh
# Выключить ИИ и удалить ключ с сервера:  sudo bash /opt/ege-tutor/deploy/set-ai-key.sh --off
set -euo pipefail

AI_VARS='^(EGE_YANDEX_API_KEY|EGE_YANDEX_FOLDER_ID|EGE_AI_PROVIDER|EGE_AI_MONTHLY_BUDGET_RUB)='

ask() {
	# ask ПЕРЕМЕННАЯ "вопрос" [hidden]
	local __name=$1 __prompt=$2 __hidden=${3:-} __value=""
	while [[ -z "$__value" ]]; do
		if [[ -n "$__hidden" ]]; then
			read -r -s -p "$__prompt" __value </dev/tty
			echo
		else
			read -r -p "$__prompt" __value </dev/tty
		fi
		__value=$(printf '%s' "$__value" | tr -d '[:space:]')
		[[ -z "$__value" ]] && echo "Пусто. Попробуй ещё раз."
	done
	printf -v "$__name" '%s' "$__value"
}

write_env() {
	# Переписать web.env без старых настроек ИИ и добавить новые строки ($@).
	local file="$EGE_ETC/web.env" tmp
	tmp=$(mktemp "$EGE_ETC/web.env.XXXXXX")
	chmod 600 "$tmp"
	grep -Ev "$AI_VARS" "$file" >"$tmp" || true
	local line
	for line in "$@"; do
		printf '%s\n' "$line" >>"$tmp"
	done
	mv "$tmp" "$file"
}

main() {
	# shellcheck source=deploy/common.sh
	source "$(dirname "$(readlink -f "$0")")/common.sh"
	if [[ $EUID -ne 0 ]]; then
		echo "Запусти через sudo: sudo bash $0" >&2
		return 1
	fi
	if [[ ! -f "$EGE_ETC/web.env" ]]; then
		echo "Сайт ещё не установлен: сначала install-server.sh" >&2
		return 1
	fi

	if [[ "${1:-}" == "--off" ]]; then
		write_env "EGE_AI_PROVIDER=disabled"
		echo "Ключ удалён с сервера, ИИ выключен."
	else
		local folder key budget
		echo "Подключение ИИ (Yandex AI Studio). Ключ на экране не показывается."
		ask folder "Идентификатор каталога (b1g...): "
		ask key "API-ключ (вставь и нажми Enter): " hidden
		read -r -p "Лимит трат в месяц, рублей [300]: " budget </dev/tty || true
		budget=${budget:-300}
		if [[ ! "$budget" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
			echo "Лимит — это число рублей, например 300." >&2
			return 1
		fi
		if [[ "$key" != AQVN* ]]; then
			echo "Внимание: ключи Yandex AI Studio обычно начинаются с AQVN. Проверь, что вставил ключ, а не его идентификатор."
		fi
		write_env "EGE_AI_PROVIDER=yandex" "EGE_YANDEX_FOLDER_ID=$folder" \
			"EGE_YANDEX_API_KEY=$key" "EGE_AI_MONTHLY_BUDGET_RUB=$budget"
		unset key
		echo "Ключ записан в $EGE_ETC/web.env (доступ только у root)."
	fi

	echo "Перезапускаю сайт..."
	compose up -d --no-deps --force-recreate app >/dev/null
	sleep 5
	compose exec -T app ege ai || true
}

main "$@"
