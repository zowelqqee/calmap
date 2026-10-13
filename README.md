# calmap

Мобильное приложение и backend для питания с подбором рациона под бюджет (рынок РФ).

Реализовано приложение по продуктовому ТЗ: онбординг, главная, питание и календарь,
**оптимизатор рациона под бюджет**, рецепты, покупки, тренировки, прогресс,
дневник, распознавание по фото, AI-консультант и подписки. Flutter-клиент находится
в `mobile/`.

## Быстрый старт

```bash
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env
createdb calmap
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed.run
.venv/bin/uvicorn app.main:app --reload
```

Документация API: http://localhost:8000/docs

## Выгрузка backend на сервер

В backend добавлена готовая Docker Compose-конфигурация для VPS с Docker. На сервер
нужно загрузить папку `backend` без `.env` и `.venv`, затем выполнить:

```bash
cd backend
cp .env.production.example .env
```

В `.env` обязательно замените `SECRET_KEY`, `POSTGRES_PASSWORD` и такое же значение
пароля внутри `DATABASE_URL`. Укажите домен в `CORS_ORIGINS` и
`RECIPE_IMAGE_PUBLIC_BASE_URL`, если они нужны приложению.

Запуск:

```bash
docker compose up -d --build
docker compose logs -f backend
```

При первом запуске контейнер автоматически дождётся PostgreSQL, применит миграции и
заполнит каталог продуктов и рецептов. Проверка:

```bash
curl http://YOUR_SERVER_IP:8000/health
```

Должен вернуться JSON со статусом `ok`. Для публичного production-доступа направьте
домен через Nginx или Caddy с HTTPS на `127.0.0.1:8000`; открытый порт 8000 годится
только для первичной проверки. После этого передайте HTTPS-адрес API в Flutter через
`API_BASE_URL`.

### Загрузка базового каталога продуктов

Open Food Facts можно скачать на сервер и импортировать потоково, без загрузки
архива целиком в оперативную память. Файл `/opt/calmap/data/openfoodfacts-products.csv.gz`
подключается в контейнер как `/data`.

После копирования обновлённого backend выполните на сервере:

```bash
cd /opt/calmap/backend
sudo docker compose up -d --build
sudo docker compose run --rm --entrypoint python backend \
  -m app.jobs.import_openfoodfacts \
  --path /data/openfoodfacts-products.csv.gz \
  --limit 50000 \
  --replace
```

Импорт берёт товары с Россией в поле стран, русское название (если оно есть),
штрихкод и КБЖУ на 100 г, а также очищает HTML-коды в названиях. Повторный запуск
обновляет уже импортированные строки, а не создаёт дубликаты. Флаг `--replace`
убирает из выдачи устаревшие строки предыдущего импорта. Для проверки без записи
используйте `--dry-run`.

### Генерация фотографий блюд

В `.env` на сервере включите провайдер и укажите ключ совместимого Images API:

```dotenv
RECIPE_IMAGE_PROVIDER=openai_compatible
RECIPE_IMAGE_API_KEY=ваш_ключ
RECIPE_IMAGE_BASE_URL=https://api.openai.com/v1
RECIPE_IMAGE_MODEL=gpt-image-2
# Shared proxy for OpenAI-compatible requests (images, vision, assistant):
OPENAI_PROXY_URL=http://user:password@proxy-host:proxy-port
RECIPE_IMAGE_STORAGE_DIR=media/recipes
RECIPE_IMAGE_PUBLIC_BASE_URL=http://194.87.44.175:8000
```

После этого перезапустите backend и один раз запустите задачу вручную:

```bash
sudo docker compose up -d --build backend
sudo docker compose run --rm --entrypoint python backend -m app.jobs.recipe_images
```

Задача создаёт отсутствующие фотографии для всех дней готовых планов и сохраняет их
в Docker volume. Повторный запуск уже готовые фотографии не перегенерирует.

Остановка и обновление:

```bash
docker compose down
docker compose up -d --build
```

Данные PostgreSQL и загруженные медиа сохраняются в Docker volumes и не удаляются
при обычном `down`. Не используйте `docker compose down -v`, если нужно сохранить
данные.

Подключение внешних ключей и webhook-ов: [INTEGRATIONS.md](INTEGRATIONS.md).

Стороннее содержимое (анатомическая графика карты мышц):
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Flutter-клиент:

```bash
cd mobile
cp config/development.example.json config/development.json
flutter pub get
flutter run --dart-define-from-file=config/development.json
```

Нативные проекты iOS/Android уже включены. Клиент проходит `flutter analyze`, widget
tests и полный UI-прогон на iPhone Simulator.

```bash
.venv/bin/python -m pytest        # 75 тестов, поднимает отдельную БД calmap_test
```

## Что где лежит

| Путь | Назначение |
|---|---|
| `mobile/lib/` | Flutter UI: auth, onboarding, главная, питание, тренировки, прогресс и сохранённые MVP-модули |
| `mobile/screenshots/partner_gallery_document/` | Проверенная галерея из 25 актуальных экранов |
| `app/domain/targets.py` | BMR/TDEE/БЖУ. Чистые функции, без I/O, покрыты тестами |
| `app/domain/solver/` | Двухуровневый оптимизатор рациона (см. ниже) |
| `app/db/models/` | 23 таблицы, миграции Alembic |
| `app/services/catalog.py` | БД → объекты солвера, расчёт цены блюда по региону |
| `app/services/planning.py` | Связка анкета → цели → солвер → сохранение плана |
| `app/services/workouts.py` | Адаптивное расписание тренировок и шаблоны упражнений |
| `app/domain/exercises.py` | Реестр из 226 упражнений по 28 целевым мышцам; доступен в API как `/v1/exercises` |
| `app/services/vision/` | Провайдеры распознавания: `stub`, Gemini и OpenAI-compatible |
| `app/services/billing/` | Checkout/webhook adapters: stub, ЮKassa, CloudPayments |
| `app/services/assistant.py` | AI-чат: stub или OpenAI-compatible gateway |
| `app/services/oauth.py` | JWKS-проверка Apple/Google и user-info проверка VK |
| `app/seed/data.py` | Курируемый каталог: 69 продуктов, 73 рецепта |

## Ключевые технические решения

**Оптимизатор рациона — не нейросеть, а два уровня оптимизации.**
Уровень 1 (`menu.py`) выбирает блюда — комбинаторная задача, решается seeded greedy +
локальный поиск. Уровень 2 (`portions.py`) подбирает граммовку — выпуклая
квадратичная задача, решается проекционным градиентным спуском; проекция на
пересечение бокса и бюджетного полупространства считается точно бисекцией по
множителю. Без numpy и OR-Tools: ставить бинарный солвер на РФ-хостинг незачем,
а 3–6 переменных решаются за доли миллисекунды.

**Солвер никогда не отвечает «решения нет».** При недостижимых ограничениях он
возвращает ближайший достижимый план плюс `relaxations` — что именно пришлось
ослабить и на сколько. Это половина продуктовой ценности фичи.

**LLM не считает числа.** Vision-провайдер возвращает `product_slug` + граммы;
КБЖУ считается из нашей базы. Иначе цифры плавают между запусками и историю нельзя
пересчитать при уточнении каталога.

**Экран подтверждения обязателен.** `requires_confirmation` всегда `true`,
автолог оценки не предусмотрен. Дельта между `candidates` и `confirmed_items`
сохраняется — это единственный источник ground truth по точности распознавания.

**Цены версионированы** (`product_prices.valid_from/valid_to`), а стоимость плана
замораживается на момент генерации. Без этого нельзя ответить на вопрос
«почему мой бюджет изменился».

**Нутриенты копируются в запись дневника**, а не джойнятся при чтении: правка
каталога не должна задним числом переписывать то, что человек съел месяц назад.

**Цели следуют финальному ТЗ.** Похудение — −15% от TDEE, поддержание — 0%,
набор — +15%; БЖУ распределяются как 30/25/45. Пользовательский `rate_pct`
принимается только для обратной совместимости и не меняет расчёт.

## Экономика вызовов

Лимиты по тарифам заданы в `app/db/models/billing.py` (`TIER_LIMITS`) — free 1 фото/день,
base 5, pro 30. Это то, что удерживает расходы на vision ниже выручки от подписки.
Дедупликация по хэшу изображения выполняется **до** проверки квоты: повторная
отправка того же фото не стоит ничего и не должна списывать лимит.

## Известные ограничения

- **OAuth требует client ID и настройки VK user-info.** Apple/Google теперь проходят
  проверку подписи, issuer и audience через JWKS; VK проверяется серверным запросом к
  `VK_USERINFO_URL`. `test:<subject>` остаётся только для local/staging.
- **Каталог пока курируемый, а не промышленный food database**: 69 продуктов и 73
  рецепта покрывают тестовую первую волну, но перед публичным запуском нужны проверка
  нутриентов диетологом, бренды/упаковки и региональные цены. Если конкретные
  ограничения отфильтруют почти весь набор, солвер честно репортит это в
  `relaxations`.
- **Границы порции одинаковы для всех приёмов пищи** (0.6–1.5 от базовой). Перекус
  на 400 г технически возможен. Следующий шаг — границы, зависящие от `meal_type`.
- **Биллинг готов как adapter layer, но требует ключей.** `/v1/billing/checkout`,
  `/v1/billing/webhooks/{provider}` и идемпотентный ledger готовы для stub/ЮKassa/
  CloudPayments. В production нужно задать merchant secrets и callback URL.
- **План питания считается синхронно**, `/onboarding/complete` обычно занимает
  миллисекунды и не вызывает LLM. Генерация изображений вынесена в отдельный
  ежедневный scheduler с повтором только для блюд без готовой картинки.

## Что остаётся подключить перед production

- Подставить секреты внешних провайдеров и ограничить webhook-ы на уровне ingress.
- Настроить объектное хранилище для `image_key`, если изображения нужно хранить для
  переобучения; сейчас сохраняются hash и нормализованный ответ.
- Изображения блюд генерируются backend job ежедневно в 05:00 по Europe/Moscow для
  ближайшего дня каждого пользователя. Один уникальный рецепт вызывает один запрос
  к image API, после чего файл сохраняется и используется всеми планами. Для OpenAI-
  совместимого API задайте `RECIPE_IMAGE_PROVIDER=openai_compatible`,
  `RECIPE_IMAGE_API_KEY` и при необходимости `RECIPE_IMAGE_BASE_URL`/`RECIPE_IMAGE_MODEL`.
- Провести legal/privacy review для health data и добавить rate limiting/WAF.

## Integration-ready модули

Функция «где купить» (в) имеет adapter route
`GET /v1/meal-plans/{id}/shopping-list/offers`; по умолчанию это curated estimate,
который явно помечается как приблизительный и не заявляет наличие в магазинах.
Для реального источника предусмотрены два безопасных варианта:

- `RETAIL_PROVIDER=http` — официальный или агрегаторный API с единым контрактом;
- `RETAIL_PROVIDER=parse_bot` — поддерживаемый API-адаптер к публичному каталогу
  Пятёрочки. Нужны `RETAIL_PARSE_API_KEY`, `RETAIL_PARSE_5KA_SCRAPER_ID` и
  обязательный `RETAIL_PARSE_5KA_STORE_ID`, поэтому «в наличии» всегда означает
  конкретную выбранную точку.

В режиме `parse_bot` живая цена/наличие Пятёрочки заменяют только совпавшие
позиции; остальная корзина остаётся честно помеченной оценкой. Backend не
обходит CAPTCHA и антибот-защиту сайтов ритейлеров.

AI-консультация (г) имеет `/v1/assistant/chat`; бесплатный и base тарифы отключены,
pro получает 200 сообщений в месяц. Провайдер подключается через
`ASSISTANT_PROVIDER=openai_compatible`.

Тренировки доступны через `/v1/workouts/*`, прогресс и отчёт — через
`/v1/progress/*`, подробный рецепт и избранное — через `/v1/catalog/recipes/*`.
Всего приложение публикует 53 API endpoint-а.
