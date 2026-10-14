# Подключение внешних интеграций

Все переменные задаются в `backend/.env` на сервере. После изменения:
`docker compose --profile https up -d`.

## 1. Оплата

Тарифы продаются разовыми платежами на 30 дней, без автосписаний. Тариф включается
только по проверенному webhook-у; переход пользователя на страницу возврата ничего
не выдаёт.

### ЮKassa

```dotenv
BILLING_PROVIDER=yookassa
BILLING_RETURN_URL=https://api.example.ru/billing/complete
YOOKASSA_SHOP_ID=...
YOOKASSA_SECRET_KEY=...
```

В личном кабинете ЮKassa → HTTP-уведомления: URL
`https://api.example.ru/v1/billing/webhooks/yookassa`, события `payment.succeeded`
и `payment.canceled`.

Уведомления ЮKassa не подписаны, поэтому backend не доверяет телу запроса: он
запрашивает платёж через API ЮKassa с ключами магазина и берёт статус, сумму и
metadata из ответа API.

### CloudPayments

```dotenv
BILLING_PROVIDER=cloudpayments
BILLING_RETURN_URL=https://api.example.ru/billing/complete
CLOUDPAYMENTS_PUBLIC_ID=...
CLOUDPAYMENTS_SECRET=...
CLOUDPAYMENTS_CHECKOUT_URL=https://pay.example.ru/checkout
```

`CLOUDPAYMENTS_CHECKOUT_URL` — ваша страница с виджетом CloudPayments. Backend
открывает её с параметрами `invoice_id`, `account_id`, `tier`, `amount`, `public_id`;
страница должна передать `invoice_id` в виджет как `invoiceId`, а `account_id` — как
`accountId`. Уведомление Pay: `https://api.example.ru/v1/billing/webhooks/cloudpayments`.
Подпись `Content-HMAC` проверяется; ответ — `{"code": 0}`.

### Общие правила

- Принимается только провайдер из `BILLING_PROVIDER`; `stub` в production отключён
  полностью (и оформление, и webhook).
- Сумма из уведомления сверяется с суммой платежа; провайдер — с провайдером платежа.
- Повторное уведомление игнорируется (журнал `billing_events`).
- Оплата до окончания срока продлевает доступ на следующие 30 дней.

## 2. Вход через Apple, Google, VK

Клиент отправляет токен провайдера в `POST /v1/auth/oauth/{apple|google|vk}`.
Аккаунт привязывается к существующему только по email, который провайдер отметил как
подтверждённый.

```dotenv
APPLE_CLIENT_ID=ru.calmap.calmapMobile     # bundle ID iOS-приложения
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
VK_CLIENT_ID=...
```

| Провайдер | Сервер | Сборка приложения (`config/production.json`) |
|---|---|---|
| Apple | `APPLE_CLIENT_ID` = bundle ID | — (кнопка видна только на iOS) |
| Google | `GOOGLE_CLIENT_ID` = **web** client ID | `GOOGLE_SERVER_CLIENT_ID` = тот же web client ID |
| VK | `VK_CLIENT_ID` | `VK_CLIENT_ID`, `VK_REDIRECT_URL` |

Кнопка Google или VK появляется в приложении, только если в сборке задан
соответствующий ID.

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
