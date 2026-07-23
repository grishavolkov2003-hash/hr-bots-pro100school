# Почтовая система (inboxrepetitor.ru)

Приём почты для аккаунтов репетиторов на Профи.ру. Один ящик на аккаунт,
только приём (никогда не отправляет), домен и почтовый сервер отдельные
от основного сайта.

**Для кого этот документ.** Ты видишь систему впервые и, возможно, будешь
сам её разворачивать/поддерживать. Читай сверху вниз: сначала архитектура
и «почему так», потом практические команды, в конце — чек-лист деплоя и
список открытых вопросов, которые пока не закрыты никем.

## Оглавление

1. [Архитектура одной картинкой](#архитектура-одной-картинкой)
2. [Ключевые факты (быстрая справка)](#ключевые-факты-быстрая-справка)
3. [Инфраструктура на сервере](#инфраструктура-на-сервере)
4. [Как создать ящик вручную](#как-создать-ящик-вручную)
5. [Как это работает автоматически (из HR-бота)](#как-это-работает-автоматически-из-hr-бота)
6. [Как прочитать почту](#как-прочитать-почту)
7. [Деплой с нуля](#деплой-с-нуля)
8. [Известные грабли](#известные-грабли)
9. [Открытые вопросы и не сделано](#открытые-вопросы-и-не-сделано)
10. [Приложение: main.cf и master.cf](#приложение-maincf-и-mastercf)

## Архитектура одной картинкой

```
Интернет (Profi.ru, Gmail и т.п.)
        │  порт 25 (SMTP)
        ▼
   Postfix (VPS 100.105.143.107 [Tailscale] / 193.124.59.172 [публичный IP])
        │  virtual_mailbox_maps → live SQL-запрос
        ▼
   /etc/postfix/mail.db (SQLite: domains, mailboxes)
        │
        ▼
   /var/mail/vhosts/<domain>/<local_part>/Maildir/{cur,new,tmp}/
        (обычные .eml файлы, владелец vmail:vmail)

Создание ящика:
  hrbot (manager_bot.py, кнопка "✅ Подписан")
        │ INSERT в mail_outbox (candidates.db)
        ▼
  main.py :: mail_provision_loop() — раз в 60 сек
        │ sudo -n /usr/bin/python3 /opt/mailsystem/provision_mailbox.py <local_part> <user_id>
        ▼
  provision_mailbox.py (root) — INSERT в mail.db + mkdir Maildir + chown vmail:vmail
```

Ключевое архитектурное решение: **создание ящика идёт через очередь, а не
напрямую**. Кнопка "Подписан" сразу пишет заявку в `mail_outbox` и
завершается — сам вызов sudo/provision происходит в отдельном фоновом
цикле. Если почтовая подсистема упадёт (диск, sudo, что угодно) — это
никак не может сломать или задержать сам факт подписания договора в
HR-боте.

Оба места, где вызывается `provision_mailbox.py` — автоматический цикл и
sudoers-правило (см. ниже) — используют полный путь `/usr/bin/python3`, а
не просто `python3` из `$PATH`. Это намеренно: sudoers матчит команду по
абсолютному пути, поэтому в коде и в правиле путь должен совпадать
дословно.

## Ключевые факты (быстрая справка)

Всё это раскрыто подробнее в соответствующих разделах ниже — тут просто
свод путей и значений в одном месте.

| Что | Значение |
|---|---|
| Домен | `inboxrepetitor.ru` |
| Сервер | тот же VPS, что hr-bot/brosky-bot (не отдельная машина) |
| Приём | порт 25 (SMTP), только приём, отправка/relay не настроены |
| БД ящиков | `/etc/postfix/mail.db` (SQLite, journal mode `DELETE`, НЕ `candidates.db`) |
| Хранилище писем | `/var/mail/vhosts/<domain>/<local_part>/Maildir/{cur,new,tmp}/` |
| Владелец Maildir | `vmail` (uid/gid 5000, без шелла) |
| Провижининг-скрипт | `/opt/mailsystem/provision_mailbox.py` (root:postfix, 750) |
| Sudo-доступ для бота | `/etc/sudoers.d/hrbot-mailprovision` |
| Retention | 45 дней, `/opt/mailsystem/retention_cleanup.py`, таймер `mail-retention.timer` |
| systemd-лимиты Postfix | `/etc/systemd/system/postfix.service.d/override.conf` |
| Лимиты в main.cf | `message_size_limit=5MB`, `mailbox_size_limit=50MB` |

## Инфраструктура на сервере

Всё стоит на **том же VPS**, что и hr-bot/brosky-bot (не отдельная
машина) — так решили сознательно после разбора рисков (открытый порт 25
на машине с продовыми ботами), закрыли лимитами вместо переезда:

- Postfix, receive-only (никакой отправки/relay не настроено вообще)
- systemd override `/etc/systemd/system/postfix.service.d/override.conf`:
  `MemoryMax=200M`, `MemoryHigh=150M`, `CPUQuota=25%`, `TasksMax=100` —
  чтобы почта не могла придушить ботов при нагрузке/атаке
- `message_size_limit=5MB`, `mailbox_size_limit=50MB` в main.cf
- retention: systemd timer `mail-retention.timer` раз в сутки удаляет
  письма старше 45 дней (`/opt/mailsystem/retention_cleanup.py`) —
  вместо бэкапа, чтобы диск (он тесный, ~6.7ГБ было свободно на момент
  установки) не заполнялся бесконечно

Риск, который стоит держать в голове: `mailbox_size_limit=50MB` — это
потолок на один ящик, а retention чистит письма старше 45 дней раз в
сутки. Если в один ящик за сутки прилетит больше 50MB, он упрётся в
лимит раньше, чем retention успеет что-то освободить. Это арифметика, не
факт из практики — на реальной нагрузке не проверялось (см. «Открытые
вопросы»).

### Хранилище ящиков (SQLite, НЕ то же самое, что candidates.db!)

`/etc/postfix/mail.db` — отдельный файл, специально не смешан с
`candidates.db` ботов (чтобы гонки записи в одном месте не мешали
другому). Две таблицы:

```sql
CREATE TABLE domains (domain TEXT PRIMARY KEY, active INTEGER);
CREATE TABLE mailboxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_part TEXT NOT NULL,
    domain TEXT NOT NULL,
    maildir TEXT NOT NULL,          -- относительный путь, напр. 'inboxrepetitor.ru/ivan/Maildir/'
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    candidate_user_id INTEGER,      -- Telegram user_id кандидата, для трассировки
    UNIQUE(local_part, domain)
);
```

**Journal mode — `DELETE` (обычный), не `WAL`.** Это важно и неочевидно,
поэтому по шагам, почему:

1. Postfix по умолчанию запускает часть своих процессов в
   chroot-песочнице — процесс видит корнем файловой системы не `/`, а
   `/var/spool/postfix/`, и физически не может открыть/создать файлы вне
   этого каталога, даже если путь в конфиге абсолютный.
2. SQLite в режиме WAL создаёт рядом с основным файлом side-car файлы
   `-wal` и `-shm`. Если основной файл (`/etc/postfix/mail.db`) лежит вне
   chroot-каталога процесса, создать side-car файлы рядом с ним из
   chroot-песочницы невозможно — падает с `disk I/O error`.
3. Решение — journal mode `DELETE` (обходится без side-car файлов, только
   временный rollback-journal, который SQLite прибирает сам), и
   дополнительно отключить chroot для трёх процессов Postfix, которым
   реально нужно ходить в SQLite: `smtp`, `cleanup`, `rewrite` — меняя
   `y → n` в колонке chroot в `master.cf`.

Именно эта связка (WAL + дефолтный chroot) была причиной первых падений
при установке — см. «Известные грабли» ниже.

Postfix читает эту базу через `sqlite_table` (`virtual_mailbox_maps`,
`virtual_mailbox_domains` в `main.cf`) — это **живые SQL-запросы на
каждый lookup**, не статический хэш-файл. Значит после `INSERT` в
`mailboxes` новый адрес начинает приниматься **сразу**, без
`postmap`/`systemctl reload postfix`.

### Пользователь vmail

Все Maildir-каталоги принадлежат системному пользователю `vmail`
(uid/gid 5000, домашний каталог `/var/mail/vhosts`, без шелла). Не
настоящие Linux-юзеры на каждого кандидата — так не масштабируется на
сотни ящиков.

## Как создать ящик вручную

Обычно это делает бот автоматически (см. ниже), но руками — тоже можно,
тем же путём, каким пользуется бот:

```bash
sudo -n /usr/bin/python3 /opt/mailsystem/provision_mailbox.py <local_part> [candidate_user_id]
# выведет: <local_part>@inboxrepetitor.ru
```

`local_part` — только `[a-z0-9][a-z0-9_.-]{1,62}[a-z0-9]` (латиница,
цифры, точка/дефис/подчёркивание, 3-64 символа). Скрипт сам:
1. `INSERT` в `/etc/postfix/mail.db :: mailboxes`
2. `mkdir -p /var/mail/vhosts/inboxrepetitor.ru/<local_part>/Maildir/{cur,new,tmp}`
3. `chown -R vmail:vmail ...`

Если ящик с таким именем уже есть — падает с понятной ошибкой (`UNIQUE`
constraint), ничего не перезаписывает. `candidate_user_id` необязателен:
при ручном вызове можно не указывать, при автоматическом (из HR-бота) он
передаётся всегда, чтобы ящик был привязан к кандидату в `mail.db`.

Файл: `/opt/mailsystem/provision_mailbox.py`, владелец `root:postfix`,
права `750`. Это ограничивает прямой (не через sudo) доступ до root и
группы `postfix` — на sudo-доступ бота это не влияет: sudo выполняет
команду от имени root независимо от членства вызывающего пользователя
(`hrbot`) в группе `postfix` (см. следующий раздел).

## Как это работает автоматически (из HR-бота)

Триггер — кнопка **"✅ Подписан"** в `manager_bot.py` (менеджер
подтверждает, что кандидат подписал договор). Именно на этом шаге, а не
раньше и не позже, кандидату реально нужен рабочий email для уведомлений
с Профи.ру.

`local_part` берётся из Telegram-ника кандидата (он уже состоит из
латиницы/цифр/подчёркиваний по правилам самого Telegram, годится как
есть, санитайзинг под те же правила local-part, что и при ручном
создании). Если ника нет или он не проходит валидацию — фолбэк
`tutor<user_id>` (гарантированно валиден и уникален).

```python
# manager_bot.py
def mailbox_local_part_for(candidate):
    username = (candidate.get("username") or "").lstrip("@").lower()
    if MAILBOX_LOCAL_PART_RE.match(username):
        return username
    return f"tutor{candidate['user_id']}"

# в хендлере contractsigned_, сразу после update_candidate_status(...):
queue_mailbox_provision(user_id, mailbox_local_part_for(candidate))
```

`queue_mailbox_provision` пишет строку в таблицу `mail_outbox` (в
`candidates.db`, общей базе ботов — эта таблица про заявки, не про
готовые ящики):

```sql
CREATE TABLE mail_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_user_id INTEGER NOT NULL,
    local_part TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | failed
    created_at TEXT NOT NULL,
    processed_at TEXT,
    error TEXT
);
```

Дальше — `main.py :: mail_provision_loop()` (стартует через 30 сек после
запуска бота, потом раз в 60 сек):

```python
for item in get_pending_mail_outbox():
    result = subprocess.run(
        ["sudo", "-n", "/usr/bin/python3", "/opt/mailsystem/provision_mailbox.py",
         item["local_part"], str(item["candidate_user_id"])],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        email = result.stdout.strip()
        update_candidate(item["candidate_user_id"], email=email)
        mark_mail_outbox_done(item["id"])
    else:
        mark_mail_outbox_failed(item["id"], result.stderr.strip())
```

Готовый адрес сохраняется в `candidates.email`.

Что делает система, если заявка помечена `failed` (диск, sudo-сбой,
что угодно) — повторной попытки или алерта менеджеру сейчас нет, заявка
просто остаётся в статусе `failed` в таблице. Это открытый пробел,
см. «Открытые вопросы».

### Права: почему sudo, а не просто вызов из-под hrbot

Бот (`hrbot`) работает без привилегий и физически не может писать в
`/etc/postfix/mail.db` (владелец `root:postfix`, `640`) и не может
создавать каталоги под `vmail`. Вместо того чтобы раздавать боту широкие
права, ему открыт **ровно один** узкий проход:

```
# /etc/sudoers.d/hrbot-mailprovision
hrbot ALL=(root) NOPASSWD: /usr/bin/python3 /opt/mailsystem/provision_mailbox.py *
```

Проверено явно: `hrbot` не может выполнить через sudo вообще ничего,
кроме этой одной команды (`sudo -n whoami` от имени hrbot — отказ).
Завершающая `*` разрешает любые аргументы после пути к скрипту — sudo
здесь не ограничивает, *какой* `local_part`/`user_id` передаётся, только
*какой скрипт* запускается. Вся защита от мусорного ввода держится на
валидации внутри `provision_mailbox.py`, а не на sudoers.

## Как прочитать почту

Формат хранения — обычный **Maildir** (RFC ничего специального не
требует): `/var/mail/vhosts/inboxrepetitor.ru/<local_part>/Maildir/new/`
— новые непрочитанные письма, каждое — отдельный файл, сырой
RFC822/MIME (то же самое, что скачивается из любого почтового клиента).

Никакого IMAP/Dovecot не поднято — сознательное решение: единственный
предполагаемый читатель — свой код, поднимать отдельный протокольный
сервер ради одного внутреннего клиента избыточно.

Питоновский пример разбора письма целиком, включая вложения и ссылки
(то, чем реально пользовались при проверке письма от Профи.ру):

```python
import email
from email import policy

with open(path_to_eml_file, "rb") as f:
    msg = email.message_from_binary_file(f, policy=policy.default)

subject = msg["Subject"]         # уже раскодирован (=?UTF-8?B?...?= сам приводится к строке)
sender = msg["From"]

for part in msg.walk():
    ctype = part.get_content_type()
    if ctype in ("text/plain", "text/html"):
        body = part.get_content()          # строка
    elif part.get_content_disposition() == "attachment":
        filename = part.get_filename()
        data = part.get_payload(decode=True)   # сырые байты файла/картинки
        # сохранить как обычный файл или обработать дальше
```

Ссылки внутри HTML/текста тела — обычный `re.findall(r'https?://[^\s"\'<>]+', text)`.

## Деплой с нуля

Порядок шагов при установке на чистый сервер (или при восстановлении
после переустановки). Каждый шаг ссылается на раздел выше, где
объясняется «почему» — это не просто чек-лист команд, а
последовательность с причинно-следственными связями: например, шаг про
отключение chroot нельзя переставить раньше SQLite-базы, потому что до
появления `sqlite_table`-конфигов сам факт chroot ещё ни на что не
влияет.

1. **Домен и DNS.** Зарегистрировать домен, добавить 4 записи (пример
   для inboxrepetitor.ru → 193.124.59.172):

   | Тип | Хост | Значение | Приоритет |
   |---|---|---|---|
   | A | mail | `<публичный IP сервера>` | — |
   | MX | @ | `mail.<домен>` | 10 |
   | TXT | @ | `v=spf1 -all` | — |
   | TXT | _dmarc | `v=DMARC1; p=reject` | — |

   Проверка: `dig +short MX <домен>` и `dig +short A mail.<домен>`
   должны отдавать реальные значения (может занять от пары минут до
   пары часов на распространение).

2. **Установка Postfix без интерактивного debconf** (чтобы дебиановский
   конфигуратор не создал свой main.cf поверх нашего):
   ```bash
   export DEBIAN_FRONTEND=noninteractive
   echo "postfix postfix/main_mailer_type select No configuration" | debconf-set-selections
   apt-get update -qq && apt-get install -y postfix postfix-sqlite sqlite3
   ```

3. **Пользователь vmail:**
   ```bash
   groupadd -g 5000 vmail
   useradd -g vmail -u 5000 vmail -d /var/mail/vhosts -m -s /usr/sbin/nologin
   mkdir -p /var/mail/vhosts && chown -R vmail:vmail /var/mail/vhosts && chmod 750 /var/mail/vhosts
   ```

4. **SQLite база** (`/etc/postfix/mail.db`) — схема в разделе
   «Хранилище ящиков», плюс `chown root:postfix mail.db && chmod 640 mail.db`.

5. **Конфиги sqlite-lookup** (`/etc/postfix/sqlite/virtual-domains.cf`,
   `virtual-mailboxes.cf`) — `dbpath` + `query`, см. раздел «Хранилище
   ящиков».

6. **`/etc/postfix/main.cf`** — писать с нуля, включая
   `message_size_limit`/`mailbox_size_limit` и sqlite-lookup из шага 5.
   Полный текст — см. Приложение.

7. **Отключить chroot** для `smtp`/`cleanup`/`rewrite` в
   `/etc/postfix/master.cf` (колонка chroot `y → n`). Без этого шага
   шаг 4 не заработает — см. разбор WAL/chroot выше.

8. **systemd override** — файл `postfix.service.d/override.conf` с
   лимитами (см. выше), особенно важно если сервер общий с другими
   сервисами.

9. **Firewall — ГЛАВНАЯ ловушка.** Порт 25 должен быть открыт на приём
   снаружи. В этом развёртывании блокировку изначально приняли за
   политику хостинг-провайдера (проверяли независимым сервисом с 56
   точек по миру — везде timeout на порт 25) — а реальная причина была
   **локальный `ufw`** на самом сервере. Проверять сначала его:
   ```bash
   ufw status verbose        # если 25/tcp не ALLOW - открыть
   ufw allow 25/tcp
   ```
   Если после этого порт всё ещё не отвечает снаружи — тогда уже писать
   в поддержку хостинга (запрос на разблокировку inbound 25).

10. **Провижининг:** залить `/opt/mailsystem/provision_mailbox.py`
    (`root:postfix`, `750`) и `/opt/mailsystem/retention_cleanup.py`,
    настроить sudoers-файл для юзера, от имени которого работает бот
    (см. «Права: почему sudo»), включить systemd timer ретеншена
    (`systemctl enable --now mail-retention.timer`).

11. **Проверка сквозного пути** — отправить письмо с любого внешнего
    ящика (Gmail и т.п., **не с этого же сервера**) на только что
    созданный тестовый адрес, убедиться что оно легло в `Maildir/new/`
    с правильным владельцем `vmail:vmail`. Если не пришло — сначала
    смотреть `journalctl -u postfix` и `/var/log/mail.log`, потом
    firewall (см. п. 9), и только в последнюю очередь — писать в
    поддержку хостинга.

## Известные грабли (потрачено времени, чтобы найти)

- **WAL + chroot Postfix = `disk I/O error`.** SQLite журнал-режим
  должен быть `DELETE`, не `WAL`.
- **Дефолтный chroot в master.cf ломает sqlite_table.** Нужно явно
  выключать (`y`→`n`) для `smtp`, `cleanup`, `rewrite`.
- **"Блокировка хостинга" оказалась локальным ufw.** Не спешить писать
  в поддержку — сначала `ufw status`. Именно поэтому в деплое (п. 9)
  этот шаг явно вынесен на видное место.
- **`email_confirm`-ссылки (напр. от Профи.ру) привязаны к сессии
  браузера**, не просто к токену в URL — открывать их нужно
  залогиненным в соответствующий аккаунт, простой GET-запрос с сервера
  ничего не подтверждает, просто покажет форму логина. Держи в голове
  при отладке жалоб «ссылка не работает».

## Открытые вопросы и не сделано

- **Доставка контента хантер-боту.** Хантер-бот на Профи.ру (отдельный,
  уже работает, живёт **на другом сервере**) должен получать из этих
  писем не просто сигнал, а **разобранное содержимое заказа**. Способ
  доставки туда пока не реализован — Maildir лежит только локально на
  этом VPS, а хантеру нужен сетевой доступ. Варианты на выбор (не
  выбран, нужно решать отдельно):
  - IMAP (поднять Dovecot) — хантер сам заберёт через стандартный протокол
  - Свой вебхук/API на этом сервере — хантер дёргает нас
  - Мы сами парсим и толкаем (push) хантеру при получении письма
- **Обработка `failed` в mail_outbox.** Нет ретрая и нет алерта
  менеджеру при сбое провижининга — заявка просто остаётся `failed`.
  Стоит проверять таблицу `mail_outbox` вручную время от времени, пока
  это не автоматизировано.
- **Поведение при `mailbox_size_limit=50MB`.** Что видит отправитель,
  когда ящик переполнен (bounce/defer) — не проверено на реальной
  нагрузке, только ожидаемое поведение Postfix по умолчанию.
- **Мониторинг retention.** `mail-retention.timer` ничем не оповещает,
  если падает или не срабатывает — тихий сбой возможен, но
  `systemctl status mail-retention.timer` / `journalctl -u
  mail-retention.service` покажут последний запуск при ручной проверке.

## Приложение: main.cf и master.cf

Актуальный `/etc/postfix/main.cf` с рабочего сервера (домен/IP/лимиты —
частности этого конкретного развёртывания; при переносе на другой
сервер поменять `myhostname`/`mydomain` и лимиты под конкретную
машину):

```
compatibility_level = 3.8

myhostname = mail.inboxrepetitor.ru
mydomain = inboxrepetitor.ru
myorigin = $mydomain

inet_interfaces = all
inet_protocols = ipv4

# Receive-only: никакой локальной unix-доставки, никакого релея наружу
mydestination =
relayhost =
mynetworks = 127.0.0.0/8
smtpd_relay_restrictions = permit_mynetworks, reject_unauth_destination
smtpd_recipient_restrictions = reject_unauth_destination, permit

# Виртуальные ящики через SQLite (отдельный файл от candidates.db)
virtual_mailbox_domains = sqlite:/etc/postfix/sqlite/virtual-domains.cf
virtual_mailbox_maps = sqlite:/etc/postfix/sqlite/virtual-mailboxes.cf
virtual_mailbox_base = /var/mail/vhosts
virtual_uid_maps = static:5000
virtual_gid_maps = static:5000
virtual_minimum_uid = 5000
virtual_transport = virtual

# Консервативные лимиты - VPS тесный, шарится с hr-bot/brosky-bot/manager_bot
message_size_limit = 5242880
mailbox_size_limit = 52428800
smtpd_client_connection_count_limit = 20
smtpd_client_connection_rate_limit = 30
anvil_rate_time_unit = 60s

smtpd_helo_required = yes
disable_vrfy_command = yes
smtpd_banner = $myhostname ESMTP
```

Содержимое `/etc/postfix/sqlite/virtual-domains.cf`:

```
dbpath = /etc/postfix/mail.db
query = SELECT domain FROM domains WHERE domain='%s' AND active=1
```

Содержимое `/etc/postfix/sqlite/virtual-mailboxes.cf`:

```
dbpath = /etc/postfix/mail.db
query = SELECT maildir FROM mailboxes WHERE local_part='%u' AND domain='%d' AND active=1
```

И фрагмент `master.cf` — три строки с отключённым chroot (предпоследняя
колонка перед именем демона: `n` вместо стандартного `y`):

```
smtp      inet  n       -       n       -       -       smtpd
cleanup   unix  n       -       n       -       0       cleanup
rewrite   unix  -       -       n       -       -       trivial-rewrite
```
