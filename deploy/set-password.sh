#!/usr/bin/env bash
# Сменить пароль для входа на сайт. Все открытые сессии после этого выходят.
set -euo pipefail

main() {
	# shellcheck source=deploy/common.sh
	source "$(dirname "$(readlink -f "$0")")/common.sh"
	compose run --rm --no-deps app ege-web set-password
}

main "$@"
