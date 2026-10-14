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
openssl rand -hex 32          # значение для SECRET_KEY
```

В `.env` заполните все строки с пометкой `CHANGE`:

| Переменная | Значение |
|---|---|
| `SECRET_KEY` | результат `openssl rand -hex 32` |
| `DOMAIN`, `CORS_ORIGINS`, `RECIPE_IMAGE_PUBLIC_BASE_URL` | ваш домен API |
| `TELEGRAM_BOT_USERNAME`, `TELEGRAM_BOT_API_SECRET` | имя бота оплаты и общий секрет (`openssl rand -hex 32`) |
| `POSTGRES_PASSWORD` и пароль внутри `DATABASE_URL` | одинаковый длинный пароль |
| `LEGAL_OPERATOR_NAME`, `LEGAL_CONTACT_EMAIL` | юрлицо/ИП и почта для обращений по персональным данным |

Запуск с HTTPS и ежедневным бэкапом:

```bash
docker compose --profile https up -d --build
docker compose logs -f backend
curl https://api.example.ru/health      # {"status":"ok","database":"ok",...}
```

При старте контейнер применяет миграции и обновляет каталог; Caddy сам получает и
продлевает сертификат. Backend слушает только `127.0.0.1:8000`, наружу открыт Caddy.

Проверьте в браузере: `https://api.example.ru/legal/privacy` и `/legal/terms` —
в тексте должны стоять ваши реквизиты.

### Бэкапы

Сервис `backup` раз в сутки пишет `pg_dump` в `BACKUP_DIR` (по умолчанию
`/opt/calmap/backups`) и хранит `BACKUP_KEEP_DAYS` дней. Копируйте этот каталог на
другой сервер или в объектное хранилище. Восстановление:

```bash
docker compose exec -T db pg_restore -U calmap -d calmap --clean --if-exists \
  < /opt/calmap/backups/calmap-YYYYMMDD-HHMMSS.dump
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
3. Запустите с профилем `https`. Порт 8000 перестанет быть доступен снаружи. Старые
   сборки приложения с адресом `http://IP:8000` после этого не подключатся — выпустите
   новую сборку с HTTPS-адресом (раздел 3).
4. Временно оставить порт открытым можно через `BACKEND_BIND=0.0.0.0`.

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

- [ ] Telegram-бот оплаты подключён по контракту из INTEGRATIONS.md, раздел 1.
      Пока `TELEGRAM_BOT_USERNAME` не задан, кнопка оплаты скрыта, и после
      пробного периода пользователи не смогут продлить доступ.
- [ ] Вход через Apple/Google: client ID на сервере и в сборке приложения.
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
| Пользовательское соглашение | `https://<домен>/legal/terms` |
| Удаление аккаунта | в приложении: Профиль → Удалить аккаунт; также запрос на `LEGAL_CONTACT_EMAIL` |
| Собираемые данные | email, имя, пол, возраст, рост, вес, цели, аллергии, дневник питания, фото блюд (не хранятся), сообщения AI, платежи |
| Цель | работа функций приложения; реклама и передача для рекламы — нет |

Перед отправкой на проверку:

- [ ] **[решение] Идентификаторы приложения.** Сейчас Android — `ru.calmap.calmap_mobile`,
      iOS — `ru.calmap.calmapMobile`. После первой публикации их нельзя изменить.
- [ ] **[решение] Оплата на iOS.** Правило App Store 3.1.1 требует покупки цифровых
      функций через In-App Purchase, а 3.1.3 запрещает направлять пользователя к
      другим способам оплаты. Кнопка «Оплатить в Telegram» в iOS-версии может стать
      причиной отказа. Варианты: подключить IAP для iOS, убрать из iOS-версии кнопку
      и упоминание оплаты или согласовать исключение с Apple.
- [ ] **[решение] Юридическая проверка** текстов `backend/app/legal/*.md` и
      уведомление Роскомнадзора об обработке персональных данных (152-ФЗ).
- [ ] Вход через Google на iOS: добавьте `GoogleService-Info.plist` и URL scheme
      (reversed client ID) в `ios/Runner/Info.plist`.
- [ ] Sign in with Apple включён для bundle ID в Apple Developer.
- [ ] Иконки и экран запуска: `ios/Runner/Assets.xcassets/LaunchImage.imageset`
      содержит заготовки Flutter — замените своими изображениями.
- [ ] Проверка на реальном устройстве: регистрация, анкета, рацион, фото, оплата в
      боте и возврат в приложение, окончание пробного периода, удаление аккаунта.
