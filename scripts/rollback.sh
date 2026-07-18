#!/bin/bash
# Откатывает бота к файлам из бэкапа, сделанного scripts/deploy.sh.
#
# Использование:
#   scripts/rollback.sh <hr-bot|brosky-bot> [timestamp|latest]
#
# Без второго аргумента (или "latest") берёт самый свежий бэкап из
# /root/deploy_backups/<bot>/. Перезапускает соответствующий(е)
# systemd-сервис(ы) после отката.
set -euo pipefail

BOT="${1:-}"
WHEN="${2:-latest}"

if [[ "$BOT" != "hr-bot" && "$BOT" != "brosky-bot" ]]; then
    echo "Использование: $0 <hr-bot|brosky-bot> [timestamp|latest]" >&2
    exit 1
fi

BOT_DIR="/opt/$BOT"
BACKUP_ROOT="/root/deploy_backups/$BOT"

if [[ "$WHEN" == "latest" ]]; then
    BACKUP_DIR=$(ls -1d "$BACKUP_ROOT"/*/ 2>/dev/null | sort | tail -1)
else
    BACKUP_DIR="$BACKUP_ROOT/$WHEN"
fi

if [[ -z "${BACKUP_DIR:-}" || ! -d "$BACKUP_DIR" ]]; then
    echo "Бэкап не найден: ${BACKUP_DIR:-$BACKUP_ROOT/$WHEN}" >&2
    echo "Доступные бэкапы:" >&2
    ls -1 "$BACKUP_ROOT" 2>/dev/null >&2 || echo "  (нет ни одного)" >&2
    exit 1
fi

echo "Откатываю $BOT из $BACKUP_DIR ..."
find "$BACKUP_DIR" -maxdepth 1 -type f -exec cp {} "$BOT_DIR/" \;

echo "Файлы восстановлены. Рестарт сервисов..."
if [[ "$BOT" == "hr-bot" ]]; then
    systemctl restart hr-bot hr-manager-bot
else
    systemctl restart brosky-bot
fi

sleep 3
systemctl is-active "$BOT" || echo "ВНИМАНИЕ: $BOT не активен после отката, проверьте journalctl -u $BOT" >&2
echo "Откат завершён."
