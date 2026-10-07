#!/usr/bin/env bash
# Ночная резервная копия базы: хранятся 14 последних копий в /var/lib/ege-tutor/backups.
set -euo pipefail

main() {
	# shellcheck source=deploy/common.sh
	source "$(dirname "$(readlink -f "$0")")/common.sh"
	compose exec -T app ege backup --keep 14
}

main "$@"
