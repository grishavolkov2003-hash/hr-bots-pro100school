#!/bin/bash
# Формализует то, что этой сессией делалось вручную перед каждой правкой:
# бэкап текущих файлов бота ДО того, как поверх них ляжет новая версия.
#
# Использование (на сервере, ПОСЛЕ того как новые файлы уже загружены на
# сервер в отдельное место, например через scp во временный каталог):
#   scripts/deploy.sh <hr-bot|brosky-bot> [источник новых файлов]
#
# Без второго аргумента только делает бэкап и печатает путь - применение
# новых файлов (scp/cp) остаётся отдельным шагом, как и раньше. Это
# осознанно не полноценный CI/CD, а безопасная обёртка вокруг ручного
# процесса - симлинк-схема между /opt/hr-bot и /opt/brosky-bot (см. README)
# слишком специфична, чтобы автоматизировать вслепую.
set -euo pipefail

BOT="${1:-}"
SRC="${2:-}"

if [[ "$BOT" != "hr-bot" && "$BOT" != "brosky-bot" ]]; then
    echo "Использование: $0 <hr-bot|brosky-bot> [каталог с новыми файлами]" >&2
    exit 1
fi

BOT_DIR="/opt/$BOT"
BACKUP_ROOT="/root/deploy_backups/$BOT"
TS="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$TS"

mkdir -p "$BACKUP_DIR"

# Только реальные файлы этого бота на верхнем уровне (-type f исключает
# symlink'и вроде storage.py/llm.py в brosky-bot, расшаренные из hr-bot -
# их бэкапит деплой hr-bot, дублировать не нужно).
find "$BOT_DIR" -maxdepth 1 -type f \( -name "*.py" -o -name "requirements.txt" \) -exec cp {} "$BACKUP_DIR/" \;

echo "Бэкап: $BACKUP_DIR"
ls -la "$BACKUP_DIR"

if [[ -n "$SRC" ]]; then
    if [[ ! -d "$SRC" ]]; then
        echo "Источник новых файлов не найден: $SRC" >&2
        exit 1
    fi
    echo "Применяю новые файлы из $SRC ..."
    find "$SRC" -maxdepth 1 -type f \( -name "*.py" -o -name "requirements.txt" \) -exec cp {} "$BOT_DIR/" \;
    echo "Готово. Перезапустите сервис(ы) вручную: systemctl restart $BOT"
    echo "Откат при проблеме: scripts/rollback.sh $BOT $TS"
fi
