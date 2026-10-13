# Подключение внешних интеграций

Внутреннее API и entitlement-логика уже готовы. В production нужно только выбрать
провайдера, задать секреты и направить callback-и на backend.

## 1. Биллинг

В `.env`:

```dotenv
BILLING_PROVIDER=yookassa
BILLING_RETURN_URL=https://app.example.ru/billing/complete
YOOKASSA_SHOP_ID=...
YOOKASSA_SECRET_KEY=...
```

Для CloudPayments:

```dotenv
BILLING_PROVIDER=cloudpayments
CLOUDPAYMENTS_PUBLIC_ID=...
CLOUDPAYMENTS_SECRET=...
CLOUDPAYMENTS_CHECKOUT_URL=https://pay.example.ru/checkout
```

Клиентский flow:

1. `POST /v1/billing/checkout` с `{ "tier": "base" }` или `{ "tier": "pro" }`.
2. Открыть `checkout_url` во внешнем браузере/webview.
3. Provider webhook направить на
   `POST /v1/billing/webhooks/yookassa` или
   `POST /v1/billing/webhooks/cloudpayments`.
4. После webhook читать `GET /v1/me/entitlements`.

Webhook обрабатывается идемпотентно по `(provider, event_id)`. Для CloudPayments
проверяется `Content-HMAC`; для YooKassa endpoint дополнительно нужно ограничить на
ingress/firewall по официальным сетевым правилам провайдера.

## 2. OAuth

```dotenv
APPLE_CLIENT_ID=ru.example.app
GOOGLE_CLIENT_ID=...
VK_USERINFO_URL=https://id.vk.com/oauth2/user_info
```

Клиент передаёт identity token в `POST /v1/auth/oauth/{apple|google|vk}`. Apple и
Google проверяются по подписи, issuer, audience и rotating JWKS. VK проверяется
серверным запросом к user-info endpoint. `test:<subject>` работает только в local и
staging.

## 3. Vision

Gemini:

```dotenv
VISION_PROVIDER=gemini
GEMINI_API_KEY=...
```

OpenAI-compatible gateway:

```dotenv
VISION_PROVIDER=openai_compatible
VISION_API_KEY=...
VISION_BASE_URL=https://api.openai.com/v1
VISION_MODEL=gpt-4o-mini
```

Endpoint `POST /v1/vision/recognize` принимает multipart image. Ответ всегда требует
подтверждения; клиент отправляет исправленный набор на
`POST /v1/vision/{recognition_id}/confirm`.

## 4. AI-консультация

```dotenv
ASSISTANT_PROVIDER=openai_compatible
ASSISTANT_API_KEY=...
ASSISTANT_BASE_URL=https://api.openai.com/v1
ASSISTANT_MODEL=gpt-4o-mini
```

`POST /v1/assistant/chat` принимает `message` и опциональный
`conversation_id`. В prompt автоматически передаются профиль, текущие цели и
последние записи дневника. Free/base получают 402, pro — 200 сообщений в месяц.

## 5. Retail offers

До партнёрского API работает безопасный `curated_estimate`. Он возвращает
расчётную стоимость из внутреннего каталога с `price_type=estimate`,
`available=null` и подписью «Расчёт по каталогу». Эти значения нельзя показывать
как цены или наличие конкретной сети:

```dotenv
RETAIL_PROVIDER=stub
```

Для внутреннего агрегатора:

```dotenv
RETAIL_PROVIDER=http
RETAIL_BASE_URL=https://retail-gateway.example.ru
RETAIL_API_KEY=...
```

Backend отправляет `POST {RETAIL_BASE_URL}/offers` с `region_code`, `currency` и
массивом товаров shopping list. Ожидаемый ответ:

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

Для HTTP-провайдера backend сам выставляет `price_type=retailer`. `url`,
`package_size_g` и `observed_at` настоятельно рекомендуется заполнять: без веса и
момента наблюдения цену нельзя корректно сравнивать или проверять. Если `name` не
пришёл, backend подставит русское название из shopping list.

## Production checklist

- выставить `ENV=production`, `DEBUG=false`, настоящий `SECRET_KEY`;
- ограничить `CORS_ORIGINS` на уровне deployment вместо wildcard в debug;
- добавить rate limiting/WAF перед auth, vision и webhook маршрутами;
- проверить 152-ФЗ/согласия на обработку health data;
- настроить TLS, резервные копии PostgreSQL и мониторинг provider errors;
- выполнить `alembic upgrade head` и `python -m app.seed.run` перед первым запуском.
