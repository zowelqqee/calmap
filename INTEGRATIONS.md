# Подключение внешних интеграций

Все переменные задаются в `backend/.env` на сервере. После изменения:
`docker compose --profile https up -d`.

## 1. Подписка через Telegram-бота

Оплата проходит в Telegram-боте. Бот — единственный источник статуса оплаты:
он сообщает backend-у каждое изменение, а приложение только читает итог.

```dotenv
TRIAL_DAYS=3
TELEGRAM_BOT_API_SECRET=...                   # openssl rand -hex 32
```

Приложение не ссылается на бота и не показывает кнопок оплаты: при окончании
подписки пользователь видит «Подписка закончилась. Продлите её, чтобы продолжить».

### Схема

1. Пользователь входит в приложение по номеру телефона (SMS-код), номер
   подтверждён.
2. В боте пользователь нажимает кнопку «Поделиться контактом» (`request_contact`).
   Бот проверяет, что контакт принадлежит отправителю (`contact.user_id == from.id`),
   и вызывает `POST /v1/bot/link` с этим номером. Telegram-аккаунт привязывается к
   аккаунту приложения с тем же номером (один к одному; повторная привязка
   переносит связь).
3. После оплаты бот вызывает `POST /v1/bot/subscription/events` со статусом `paid`.
4. Приложение перечитывает статус при возврате в приложение и открывает доступ.

### API для бота

Все запросы — с заголовком `X-Bot-Secret: <TELEGRAM_BOT_API_SECRET>`. Без настроенного
секрета эндпоинты отвечают 404, с неверным — 401.

**`POST /v1/bot/link`** — привязка по номеру телефона.

```json
{"phone": "+79991234567", "telegram_user_id": 123456789, "telegram_username": "ivan"}
```

Ответ 200: `{"user_id": "...", "subscription": {...}}`. 404 — в приложении нет
аккаунта с этим номером (попросите войти в приложение по этому номеру); 422 — номер
не российский мобильный.

**`POST /v1/bot/subscription/events`** — изменение статуса оплаты.

```json
{
  "event_id": "tg-charge-6a1f...",
  "telegram_user_id": 123456789,
  "status": "paid",
  "tier": "pro",
  "paid_until": "2026-11-14T12:00:00+03:00",
  "amount": 499,
  "currency": "RUB",
  "telegram_payment_charge_id": "6a1f..."
}
```

| Поле | Правило |
|---|---|
| `event_id` | уникален; повтор того же события возвращает `processed: false` и ничего не меняет |
| `status` | `paid` — доступ до `paid_until`; `revoked` — отмена/возврат, доступ закрывается сразу |
| `tier` | `base` или `pro`; обязателен для `paid` |
| `paid_until` | обязателен для `paid`; с часовым поясом; в будущем, не дальше 400 дней |
| `currency` | `RUB` или `XTR` (Telegram Stars) |

Последнее событие задаёт статус как есть: продление считает бот (например,
`paid_until` = текущий `paid_until` + 30 дней). Ответ:
`{"processed": true, "subscription": {...}}`. 404 — Telegram-аккаунт не привязан.

**`GET /v1/bot/subscription/{telegram_user_id}`** — текущий статус (для команды
«Моя подписка» в боте).

**`GET /v1/bot/subscriptions/expiring?within_hours=24`** — привязанные пользователи,
у которых доступ (оплата или пробный период) заканчивается в этом окне. Для
напоминаний из бота.

### Статус в ответах

`subscription` во всех ответах совпадает с `GET /v1/me/subscription`:

```json
{
  "state": "active",
  "has_access": true,
  "tier": "pro",
  "payment_status": "paid",
  "paid_until": "2026-11-14T09:00:00Z",
  "trial_ends_at": "2026-10-17T09:00:00Z",
  "access_until": "2026-11-14T09:00:00Z",
  "days_left": 31,
  "limits": {"vision_per_day": 30, "plan_days": 28, "assistant_messages_per_month": 200},
  "message": null,
  "telegram_linked": true,
  "payment_available": true
}
```

`state`: `trial`, `active`, `trial_ended`, `expired`, `revoked`. Без доступа
`message` содержит текст для пользователя.

### Безопасность

- Укажите IP сервера бота в `BOT_ALLOWED_IPS`: Caddy отклонит `/v1/bot/*` с других адресов.
- Секрет храните только в `.env` backend-а и бота; при утечке смените в обоих.
- Удаление аккаунта удаляет и привязку к Telegram, и журнал событий оплаты
  пользователя. Платёжные документы (чеки) хранит платёжный сервис бота.

## 2. Вход: SMS-код и VK ID

Основной способ — номер мобильного телефона российского оператора и код из SMS:
149-ФЗ прямо называет этот способ авторизации. Вход через Google и Apple ID удалён
(штраф по ст. 13.55 КоАП с 7 июля 2026 года). Подробнее —
[docs/legal/rkn-review.md](docs/legal/rkn-review.md).

```dotenv
SMS_PROVIDER=smsru
SMSRU_API_ID=...          # ключ из личного кабинета SMS.ru
SMS_SENDER=               # согласованное имя отправителя; пусто — по умолчанию
SMS_DAILY_LIMIT=2000      # потолок SMS в сутки на весь сервис
```

| Эндпоинт | Назначение |
|---|---|
| `POST /v1/auth/phone/code` `{"phone": "+79991234567"}` | отправить код; ответ `{"expires_in": 300, "resend_in": 60}` |
| `POST /v1/auth/phone/verify` `{"phone", "code", "personal_data_consent"}` | обменять код на токены; первый вход создаёт аккаунт |

Защита: код из 6 цифр, действует 5 минут, 5 попыток; не чаще раза в минуту и 5 кодов
в час на номер; общий лимит попыток на IP; суточный потолок SMS. Принимаются только
номера `+7 9XX`. Коды хранятся в виде HMAC и удаляются через сутки. Если аккаунта
нет, а согласие не отмечено, ответ 422 и код не расходуется — приложение показывает
отметку согласия и повторяет запрос.

`SMS_PROVIDER=stub` (разработка) пишет код в лог; в production отклоняется.

Вход через VK ID (необязательно):

```dotenv
VK_CLIENT_ID=...
```

Сборка приложения: `VK_CLIENT_ID`, `VK_REDIRECT_URL` в `config/production.json`.
Кнопка VK ID появляется, только если ID задан. Первый вход через VK требует
согласия (`personal_data_consent: true`). Аккаунт привязывается к существующему
только по email, подтверждённому VK.

**VK: требуется проверка на устройстве.** Backend проверяет токен через VK ID
`POST /oauth2/user_info` с `client_id`. Клиент получает токен через AppAuth; VK ID
при обмене кода дополнительно ожидает `device_id` и `state`, которые AppAuth не
передаёт. Перед включением VK в production проверьте вход на телефоне; при ошибке
обмена кода клиентскую часть нужно перевести на VK ID SDK.

Токены `test:<id>` работают только при `ENV=local` или `staging`.

## 3. Распознавание фото

Gemini:

```dotenv
VISION_PROVIDER=gemini
GEMINI_API_KEY=...
```

OpenAI-совместимый API:

```dotenv
VISION_PROVIDER=openai_compatible
VISION_API_KEY=...
VISION_BASE_URL=https://api.openai.com/v1
VISION_MODEL=gpt-4o-mini
OPENAI_PROXY_URL=        # необязательный прокси для запросов к провайдеру
```

`POST /v1/vision/recognize` — фото до 8 МБ; результат всегда подтверждает
пользователь (`POST /v1/vision/{id}/confirm`). Ошибки провайдера пишутся в лог, а
пользователь получает «временно недоступно».

## 4. AI-консультант (тариф PRO)

```dotenv
ASSISTANT_PROVIDER=openai_compatible
ASSISTANT_API_KEY=...
ASSISTANT_BASE_URL=https://api.openai.com/v1
ASSISTANT_MODEL=gpt-4o-mini
```

В запрос передаются анкета, нормы и последние записи дневника, без имени и email.
Free/BASE получают 402, PRO — 200 сообщений в месяц.

## 5. Фотографии блюд

```dotenv
RECIPE_IMAGE_PROVIDER=openai_compatible
RECIPE_IMAGE_API_KEY=...
RECIPE_IMAGE_BASE_URL=https://api.openai.com/v1
RECIPE_IMAGE_MODEL=gpt-image-2
```

Задача запускается ежедневно в 05:00 МСК и создаёт картинку один раз на рецепт.
Ручной запуск:

```bash
docker compose run --rm --entrypoint python backend -m app.jobs.recipe_images
```

## 6. Цены магазинов

По умолчанию (`RETAIL_PROVIDER=stub`) список покупок показывает расчётную стоимость
по каталогу с пометкой «Расчёт по каталогу», без заявлений о наличии.

Собственный агрегатор:

```dotenv
RETAIL_PROVIDER=http
RETAIL_BASE_URL=https://retail-gateway.example.ru
RETAIL_API_KEY=...
```

Backend отправляет `POST {RETAIL_BASE_URL}/offers` с `region_code`, `currency` и
товарами списка покупок. Ожидаемый ответ:

```json
{
  "offers": [
    {
      "slug": "chicken_breast",
      "name": "Куриная грудка, филе",
      "retailer": "Перекрёсток",
      "available": true,
      "price": 604.99,
      "currency": "RUB",
      "url": "https://store.example/item/123",
      "package_size_g": 1000,
      "observed_at": "2026-08-03T18:00:00+03:00"
    }
  ]
}
```

Пятёрочка через управляемый адаптер: `RETAIL_PROVIDER=parse_bot`,
`RETAIL_PARSE_API_KEY`, `RETAIL_PARSE_5KA_SCRAPER_ID`, `RETAIL_PARSE_5KA_STORE_ID`
(обязателен: наличие относится к конкретному магазину). Backend не обходит CAPTCHA
и защиту сайтов.
