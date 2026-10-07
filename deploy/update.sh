#!/usr/bin/env bash
# Автообновление: если в ветке main есть новый коммит, сделать копию базы,
# пересобрать и перезапустить сайт. Запускается таймером раз в 10 минут.
#
# Весь код внутри main(): bash прочитает функцию целиком до запуска, поэтому
# обновление этого же файла через git во время работы ничего не сломает.
set -euo pipefail

main() {
	# shellcheck source=deploy/common.sh
	source "$(dirname "$(readlink -f "$0")")/common.sh"
	exec 9>/run/ege-tutor-update.lock
	flock -n 9 || { log "обновление уже идёт"; return 0; }

	cd "$EGE_DIR"
	git fetch --quiet origin main
	local current target
	current=$(git rev-parse HEAD)
	target=$(git rev-parse origin/main)
	if [[ "$current" == "$target" && "${1:-}" != "--force" ]]; then
		return 0
	fi

	log "обновление ${current:0:7} -> ${target:0:7}"
	if compose ps --status running --services | grep -qx app; then
		compose exec -T app ege backup --keep 14 || log "копию перед обновлением сделать не удалось"
	fi
	# На сервере нет своих правок: рабочая копия всегда совпадает с main.
	git reset --quiet --hard "$target"
	compose build --pull app
	compose up -d --remove-orphans
	docker image prune -f >/dev/null
	log "готово"
}

main "$@"
