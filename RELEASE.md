# Выпуск Calmap в production

Порядок: сервер → внешние сервисы → сборка приложений → публикация в магазинах.
Отмеченные **[решение]** пункты код не решает: их выбирает владелец продукта.

## 1. Сервер

Нужны: VPS с Docker Compose v2, домен (например `api.example.ru`) с A-записью на IP
сервера, открытые порты 80 и 443.

```bash
git clone <репозиторий> /opt/calmap
cd /opt/calmap/backend
cp .env.production.example .env
cp .env.bot.example .env.bot
chmod 600 .env .env.bot
openssl rand -hex 32          # значение для SECRET_KEY и TELEGRAM_BOT_API_SECRET
openssl rand -hex 24          # пароли PostgreSQL
```

В `.env` заполните все строки с пометкой `CHANGE`:

| Переменная | Значение |
|---|---|
| `SECRET_KEY` | результат `openssl rand -hex 32` |
| `DOMAIN`, `CORS_ORIGINS`, `RECIPE_IMAGE_PUBLIC_BASE_URL` | ваш домен API |
| `SMSRU_API_ID`, `SMS_SENDER` | ключ SMS.ru и имя отправителя для кодов входа |
| `TELEGRAM_BOT_API_SECRET` | общий секрет с ботом оплаты (`openssl rand -hex 32`), то же значение в `.env.bot` |
| `POSTGRES_PASSWORD` | пароль суперпользователя (обслуживание, бэкапы) |
| `APP_DB_PASSWORD` и пароль внутри `DATABASE_URL` | роль backend-а `calmap_app` без прав суперпользователя |
| `BOT_DB_PASSWORD` и пароль внутри `DATABASE_URL` в `.env.bot` | роль бота `calmap_bot`, видит только схему `bot` |
| `BACKUP_PASSPHRASE` | пароль шифрования бэкапов; хранить также вне сервера |
| `LEGAL_OPERATOR_NAME`, `LEGAL_CONTACT_EMAIL` | юрлицо/ИП и почта для обращений по персональным данным |
| `ASSISTANT_PROCESSOR_NAME`, `ASSISTANT_PROCESSOR_COUNTRY` | кто и в какой стране обрабатывает запросы AI-консультанта (текст согласия) |
| `VISION_PROCESSOR_NAME`, `VISION_PROCESSOR_COUNTRY` | то же для распознавания фото; пусто — как у AI-консультанта |

Запуск с HTTPS и ежедневным бэкапом:

```bash
docker compose --profile https up -d --build
docker compose logs -f backend
curl https://api.example.ru/health      # {"status":"ok","database":"ok",...}
```

При старте контейнер применяет миграции и обновляет каталог; Caddy сам получает и
продлевает сертификат. Backend слушает только `127.0.0.1:8000`, наружу открыт Caddy.
Роли `calmap_app` и `calmap_bot` создаются при первом запуске пустой базы
(`docker/db-roles.sh`). Меры защиты и остаточные риски —
[docs/security/audit.md](docs/security/audit.md).

Проверьте в браузере: `https://api.example.ru/legal/privacy` и `/legal/terms` —
в тексте должны стоять ваши реквизиты.

### Сертификат через DNS (если Let's Encrypt не достучался до сервера)

Признак — в `docker compose logs caddy` ошибки `Timeout after connect`: часть
зарубежных сетей не доходит до российского сервера, а Let's Encrypt проверяет домен
из нескольких стран. Тогда сертификат получается через DNS REG.RU: контейнер `certs`
(lego) записывает TXT-запись через API REG.RU, к серверу никто не подключается.
Продление — само, за 30 дней до окончания; Caddy подхватывает новый сертификат.

1. Домен должен обслуживаться DNS-серверами REG.RU `ns1.reg.ru` и `ns2.reg.ru`
   (карточка домена → «DNS-серверы»). Если указаны другие — переключите на
   «DNS-серверы REG.RU» и заново создайте A-записи (`@` и `api` → IP сервера);
   переключение `.ru` занимает до суток.
2. REG.RU → «Настройки» → «Настройки API»: задайте альтернативный пароль для API и
   разрешите доступ с IP сервера.
3. В `.env`:
   ```dotenv
   COMPOSE_FILE=docker-compose.yml:docker-compose.dns-certs.yml
   REGRU_USERNAME=логин REG.RU
   REGRU_PASSWORD=пароль для API из шага 2
   ```
4. `docker compose --profile https up -d`, затем `docker compose logs -f certs`:
   получение занимает до 30 минут (REG.RU применяет изменения DNS не сразу).
   Caddy стартует, когда сертификат готов.

### Сертификат через DNS вручную (если API REG.RU недоступен с сервера)

`COMPOSE_FILE` как выше, `REGRU_USERNAME` и `REGRU_PASSWORD` пустые. Получение:

```bash
docker compose run --rm -it --entrypoint /lego certs \
  --accept-tos --email <LEGAL_CONTACT_EMAIL> --dns manual \
  --dns.propagation-wait 60s \
  --domains <DOMAIN> --path /certs run
```

lego покажет запись вида `_acme-challenge.api.calmap.ru. 120 IN TXT "…"`. В панели
DNS REG.RU создайте TXT-запись: имя `_acme-challenge.api`, значение — строка в
кавычках (без кавычек); при каждом запуске значение новое. Проверьте запись прямо
на DNS-серверах REG.RU, с любого компьютера (публичные DNS кэшируют старое значение
до часа): `dig +short TXT _acme-challenge.api.calmap.ru @ns1.reg.ru` и то же с
`@ns2.reg.ru`. Когда оба показывают новое значение, нажмите Enter.
`--dns.propagation-wait` отключает проверку записи с сервера (он не достаёт до DNS
REG.RU) и просто ждёт минуту перед запросом к Let's Encrypt. Затем
`docker compose --profile https up -d`: Caddy запустится с сертификатом.

Сертификат действует 90 дней. **Через 60 дней** повторите ту же команду с `renew
--days 30` вместо `run` — Caddy подхватит новый сертификат сам. Поставьте
напоминание; `docker compose logs certs` пишет дату последнего сертификата.

### Прокси для OpenAI через SSH

Серверы в России обращаются к OpenAI только через сервер за рубежом. Обычный SOCKS
до зарубежного сервера по пути режется, SSH проходит: контейнер `egress` держит
SSH-туннель и даёт backend-у SOCKS-прокси `egress:1080` внутри сети compose.

1. На московском сервере создайте ключ туннеля и выведите публичную часть:
   ```bash
   cd /opt/calmap/backend
   ssh-keygen -t ed25519 -N "" -C calmap-egress -f docker/egress/id_ed25519
   cat docker/egress/id_ed25519.pub
   ```
2. На зарубежном сервере — пользователь, которому разрешена только переадресация:
   ```bash
   useradd -m -s /usr/sbin/nologin tunnel
   mkdir -p /home/tunnel/.ssh
   echo 'restrict,port-forwarding <строка из id_ed25519.pub>' > /home/tunnel/.ssh/authorized_keys
   chown -R tunnel:tunnel /home/tunnel/.ssh && chmod 700 /home/tunnel/.ssh && chmod 600 /home/tunnel/.ssh/authorized_keys
   ```
3. В `.env` московского сервера:
   ```dotenv
   COMPOSE_FILE=docker-compose.yml:docker-compose.dns-certs.yml:docker-compose.egress.yml
   EGRESS_HOST=<IP зарубежного сервера>
   OPENAI_PROXY_URL=socks5://egress:1080
   ```
4. `docker compose up -d --build egress backend`; проверка:
   `docker compose exec backend python -c "import httpx;print(httpx.get('https://api.openai.com/v1/models',proxy='socks5://egress:1080').status_code)"`
   — `401` значит, что туннель работает (OpenAI отвечает «нет ключа»).

### Бэкапы

Сервис `backup` раз в сутки пишет `pg_dump` в `BACKUP_DIR` (по умолчанию
`/opt/calmap/backups`) и хранит `BACKUP_KEEP_DAYS` дней. Файлы доступны только
владельцу; при заданном `BACKUP_PASSPHRASE` они зашифрованы (`*.dump.enc`).
Копируйте каталог на другой сервер или в объектное хранилище. Восстановление:

```bash
cd /opt/calmap/backend
docker compose stop backend bot
# только для зашифрованного файла:
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in ../backups/calmap-YYYYMMDD-HHMMSS.dump.enc -out /tmp/calmap.dump
docker compose exec -T db pg_restore -U calmap -d calmap --clean --if-exists \
  < /tmp/calmap.dump        # или ../backups/calmap-YYYYMMDD-HHMMSS.dump
rm /tmp/calmap.dump
docker compose --profile https up -d
```

### Обновление

```bash
cd /opt/calmap && git pull
cd backend && docker compose --profile https up -d --build
```

Не используйте `docker compose down -v`: флаг `-v` удаляет базу данных и медиафайлы.

### Переход со старой схемы (порт 8000 по IP, без HTTPS)

1. Образ теперь работает от непривилегированного пользователя. Один раз выдайте ему
   права на уже существующий том с фотографиями блюд:
   ```bash
   docker compose run --rm --user root --entrypoint chown backend -R 10001:10001 /app/media
   ```
2. В `.env` добавьте `DOMAIN`, `LEGAL_*`, обновите `CORS_ORIGINS`,
   `RECIPE_IMAGE_PUBLIC_BASE_URL` на `https://`-адрес. Миграция БД при старте
   удаляет таблицы ЮKassa/CloudPayments и выдаёт всем существующим аккаунтам
   пробный период 3 дня от момента обновления; оплаченные периоды сохраняются.
   Вход по email и паролю удалён: старые тестовые аккаунты с email больше не
   открываются, вход по номеру телефона создаёт новый аккаунт.
3. Запустите с профилем `https`. Порт 8000 перестанет быть доступен снаружи. Старые
   сборки приложения с адресом `http://IP:8000` после этого не подключатся — выпустите
   новую сборку с HTTPS-адресом (раздел 3).
4. Роли БД и отдельный `.env.bot` (база уже существует, поэтому роли создаются
   вручную):
   ```bash
   # в .env: APP_DB_PASSWORD, BOT_DB_PASSWORD, DATABASE_URL с calmap_app,
   # переменные бота перенести в .env.bot (см. .env.bot.example)
   docker compose down          # без -v: сеть compose теперь с фиксированной подсетью
   docker compose up -d db
   docker compose exec db sh /db-roles.sh
   docker compose --profile https up -d --build
   ```

### Каталог Open Food Facts (необязательно)

```bash
docker compose run --rm --entrypoint python backend \
  -m app.jobs.import_openfoodfacts --path /data/openfoodfacts-products.csv.gz \
  --limit 50000 --replace
```

Файл кладётся в `/opt/calmap/data/`. Импорт берёт товары для России, обновляет уже
импортированные строки; `--dry-run` — проверка без записи.

## 2. Внешние сервисы

Настройка — в [INTEGRATIONS.md](INTEGRATIONS.md). Минимум для запуска продаж:

- [ ] SMS-вход: договор с SMS.ru, пополненный баланс, согласованное имя отправителя,
      `SMS_PROVIDER=smsru`. Без этого пользователи не смогут войти.
- [ ] Telegram-бот оплаты (`bot/`, запускается профилем `https`):
      Все переменные бота — в `.env.bot`, не в `.env`.
      1. @BotFather → `/newbot`, токен в `BOT_TOKEN`; `YOOKASSA_RETURN_URL` =
         `https://t.me/<имя_бота>`.
      2. Магазин ЮKassa: `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`; включить чеки
         (54-ФЗ) и указать `YOOKASSA_VAT_CODE` по системе налогообложения.
      3. ЮKassa → HTTP-уведомления: `https://<домен>/yookassa/webhook`, события
         `payment.succeeded`, `payment.canceled`, `refund.succeeded`.
      4. Проверка тестовым магазином ЮKassa: оплата → сообщение «Оплата получена»
         → доступ в приложении.
      Без бота после пробного периода продлить доступ нельзя.
- [ ] Вход через VK ID отложен: на экране входа кнопка неактивна с подписью
      «Будет доступно позже». Включение — INTEGRATIONS.md, раздел 2.
- [ ] Распознавание фото и AI-консультант: ключи провайдеров. Без них пользователь
      видит «временно недоступно»: заглушки в production отключены.

При старте backend пишет в лог предупреждение о каждом оставшемся stub-провайдере.

## 3. Сборка приложений

```bash
cd mobile
cp config/production.example.json config/production.json   # API_BASE_URL = https://<домен>
```

Release-сборка без `API_BASE_URL` намеренно не запускается.

**Android** — один раз создайте ключ загрузки и `android/key.properties`
(не коммитится):

```bash
keytool -genkey -v -keystore ~/calmap-upload.jks -keyalg RSA -keysize 2048 \
  -validity 10000 -alias upload
```

```properties
storeFile=/абсолютный/путь/calmap-upload.jks
storePassword=...
keyAlias=upload
keyPassword=...
```

```bash
flutter build appbundle --release --dart-define-from-file=config/production.json
# build/app/outputs/bundle/release/app-release.aab
```

Без `key.properties` сборка подписывается debug-ключом — Google Play такой файл не
примет.

**iOS** — в Xcode выберите свою команду разработчика (Signing & Capabilities),
затем:

```bash
flutter build ipa --release --dart-define-from-file=config/production.json
```

Номер версии — строка `version:` в `mobile/pubspec.yaml` (`1.0.0+1`: версия + номер
сборки). Номер сборки увеличивайте при каждой загрузке в магазин.

## 4. Публикация

Данные для карточек магазинов:

| Поле | Значение |
|---|---|
| Политика конфиденциальности | `https://<домен>/legal/privacy` |
| Согласие на обработку ПДн | `https://<домен>/legal/consent` |
| Пользовательское соглашение | `https://<домен>/legal/terms` |
| Удаление аккаунта | в приложении: Профиль → Удалить аккаунт; также запрос на `LEGAL_CONTACT_EMAIL` |
| Собираемые данные | номер телефона, имя, пол, возраст, рост, вес, цели, аллергии, дневник питания, фото блюд (не хранятся), сообщения AI, сведения о подписке, Telegram ID |
| Возрастной рейтинг | 18+ (анкета не принимает возраст младше 18 лет) |
| Цель | работа функций приложения; реклама и передача для рекламы — нет |

Перед отправкой на проверку:

- [ ] Идентификатор приложения `ru.calmap.app` (Android и iOS). Зарегистрировать в
      Apple Developer → Identifiers; в Google Play и RuStore он закрепляется первой
      загрузкой сборки. После первой публикации его нельзя изменить.
- [ ] **Оплата на iOS.** Приложение не ссылается на внешнюю оплату и не называет
      способ оплаты (правило App Store 3.1.3 о направлении к другим способам оплаты
      соблюдено). Остаётся риск по 3.1.1: Apple может потребовать In-App Purchase
      для функций, открываемых подпиской.
- [ ] **[решение] Вход через VK ID на iOS** (при включении в будущем). Правило App
      Store 4.8 требует при входе через сторонний сервис предложить равноценный
      приватный способ, а Sign in with Apple в России запрещён (149-ФЗ, ст. 13.55
      КоАП). Вариант: не включать VK ID в iOS-сборке (останется вход по SMS).
- [ ] **[решение] Юридическая проверка** текстов `backend/app/legal/*.md` юристом и
      уведомление Роскомнадзора об обработке персональных данных (152-ФЗ).
- [ ] Требования РКН до запуска: [docs/legal/rkn-review.md](docs/legal/rkn-review.md),
      раздел «Что сделать оператору».
- [ ] Иконки и экран запуска: `ios/Runner/Assets.xcassets/LaunchImage.imageset`
      содержит заготовки Flutter — замените своими изображениями.
- [ ] Проверка на реальном устройстве: вход по SMS (автоподстановка кода), анкета,
      рацион, фото, оплата в боте и возврат в приложение, окончание пробного
      периода, удаление аккаунта.
