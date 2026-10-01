#!/usr/bin/env bash
# Развернуть pii-mask в боевой каталог из текущего коммита.

set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
PROD="${PII_MASK_HOME:-/data/apps/pii-mask}"
LINK="$HOME/.local/bin/pii-mask"

cd "$SRC"

echo "== тесты =="
.venv/bin/python -m pytest -q

DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then
    echo "!! в дереве есть незакоммиченные правки - они НЕ попадут в бой:" >&2
    echo "$DIRTY" >&2
fi
COMMIT="$(git rev-parse --short HEAD)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
git archive HEAD | tar -x -C "$STAGE"

echo "== установка в $PROD =="
mkdir -p "$PROD"
[ -x "$PROD/.venv/bin/python" ] || python3 -m venv "$PROD/.venv"
# Не editable: в бой едет копия кода, а не ссылка на рабочее дерево - иначе
# разделение существует только на бумаге.
"$PROD/.venv/bin/pip" install --quiet --upgrade "$STAGE"

printf '%s %s %s\n' "$COMMIT" "$BRANCH" "$(date +%Y-%m-%dT%H:%M)" > "$PROD/ВЕРСИЯ"
mkdir -p "$(dirname "$LINK")"
ln -sfn "$PROD/.venv/bin/pii-mask" "$LINK"

echo "== проверка =="
# Спрашиваем у самой точки входа, какой код она импортирует, и делаем это вне каталога репозитория
GOT="$(cd /tmp && "$LINK" where)"
case "$GOT" in
    "$PROD"/*) ;;
    *) echo "!! точка входа импортирует код не из боевого каталога: $GOT" >&2
       exit 1 ;;
esac
echo "код в бою: $GOT"
echo "версия: $(cat "$PROD/ВЕРСИЯ")"
echo "точка входа: $LINK -> $(readlink -f "$LINK")"

# Перезапуск службы на сервере для работы с обновлённым кодом
# Запускается только в случае работы бота на сервере
SERVICE="pii-mask"
echo "== служба =="
if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl нет - службы на этой машине не бывает, пропускаю"
elif ! systemctl --user is-active --quiet "$SERVICE"; then
    echo "служба $SERVICE не запущена - перезапускать нечего"
else
    systemctl --user restart "$SERVICE"
    sleep 2
    if ! systemctl --user is-active --quiet "$SERVICE"; then
        echo "!! служба $SERVICE не поднялась после перезапуска:" >&2
        systemctl --user status "$SERVICE" --no-pager >&2 || true
        exit 1
    fi
    # "active" не значит "на новом коде": проверяем, откуда запущен процесс.
    PID="$(systemctl --user show "$SERVICE" -p MainPID --value)"
    CMD="$(ps -o cmd= -p "$PID")"
    case "$CMD" in
        *"$PROD"/*) ;;
        *) echo "!! служба запущена не из боевого каталога: $CMD" >&2
           exit 1 ;;
    esac
    echo "служба перезапущена: $CMD"
fi
