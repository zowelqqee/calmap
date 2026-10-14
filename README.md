# Calmap

Мобильное приложение (iOS/Android, Flutter) и backend (FastAPI + PostgreSQL) для
планирования питания под бюджет, рынок РФ.

Функции: онбординг-анкета, расчёт норм КБЖУ, рацион на неделю в пределах бюджета,
замена блюд, список покупок, дневник питания (поиск, ручной ввод, распознавание по
фото), тренировки с картой мышц, прогресс веса и замеров, AI-консультант (PRO),
платные тарифы BASE/PRO, удаление аккаунта, правовые документы.

| Документ | Содержание |
|---|---|
| [RELEASE.md](RELEASE.md) | Пошаговый выпуск: сервер, HTTPS, сборка и публикация приложений |
| [INTEGRATIONS.md](INTEGRATIONS.md) | Подключение оплаты, входа через Apple/Google/VK, распознавания, AI |
| [mobile/README.md](mobile/README.md) | Сборка клиента, подпись, конфигурация |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Стороннее содержимое (анатомическая графика) |

## Локальный запуск

Backend (нужны Python 3.11+ и PostgreSQL 16):

```bash
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env
createdb calmap
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed.run
.venv/bin/uvicorn app.main:app --reload
```

Документация API: http://localhost:8000/docs (в production отключена).

Клиент:

```bash
cd mobile
cp config/development.example.json config/development.json
flutter pub get
flutter run --dart-define-from-file=config/development.json
```

## Проверки

```bash
cd backend && .venv/bin/ruff check app tests && .venv/bin/python -m pytest -q   # 98 тестов
cd mobile && flutter analyze && flutter test                                    # 15 тестов + 4 golden (только macOS)
```

Тесты backend создают отдельную БД `calmap_test` и прогоняют те же миграции Alembic,
что и production. Те же проверки и сборка Docker-образа выполняются в GitHub Actions
(`.github/workflows/ci.yml`) на каждый pull request.

## Структура

| Путь | Назначение |
|---|---|
| `backend/app/api/v1/` | 59 операций REST API |
| `backend/app/api/legal.py` | Публичные страницы `/legal/privacy`, `/legal/terms`, `/billing/complete` |
| `backend/app/domain/targets.py` | BMR/TDEE/БЖУ, чистые функции |
| `backend/app/domain/solver/` | Оптимизатор рациона (см. ниже) |
| `backend/app/domain/allergens.py` | Сопоставление аллергенов анкеты с кодами каталога |
| `backend/app/domain/exercises.py` | Реестр из 233 упражнений |
| `backend/app/services/billing/` | ЮKassa, CloudPayments, stub (только вне production) |
| `backend/app/services/oauth.py` | Проверка токенов Apple/Google (JWKS) и VK ID |
| `backend/app/services/vision/` | Распознавание: Gemini, OpenAI-совместимый API, stub |
| `backend/app/seed/data.py` | Курируемый каталог: 69 продуктов, 73 рецепта |
| `backend/docker-compose.yml` | PostgreSQL, backend, Caddy (HTTPS), ежедневный бэкап |
| `mobile/lib/core/api_client.dart` | HTTP, обновление сессии, офлайн-кэш и очередь изменений |
| `mobile/lib/screens/` | Экраны приложения |

## Ключевые решения

**Оптимизатор рациона — два уровня оптимизации, не нейросеть.** Уровень 1
(`menu.py`) выбирает блюда: seeded greedy + локальный поиск. Уровень 2
(`portions.py`) подбирает граммовку: выпуклая квадратичная задача, проекционный
градиентный спуск с точной проекцией на бюджетное полупространство.

**Солвер не отвечает «решения нет».** При недостижимых ограничениях он возвращает
ближайший план и список `relaxations` — что пришлось ослабить и на сколько.

**Аллергены исключаются с запасом.** «Арахис» исключает и орехи, «Морепродукты» —
ракообразных и моллюсков. Неизвестный аллерген отклоняется (422), а не игнорируется.

**LLM не считает числа.** Распознавание возвращает продукт и граммы, КБЖУ считается
по базе. Экран подтверждения обязателен.

**Цены версионированы**, стоимость плана фиксируется в момент генерации; нутриенты
копируются в запись дневника.

**Тарифы — разовая оплата на 30 дней без автосписаний.** Тариф выдаётся только
по проверенному webhook-у провайдера: CloudPayments — подпись HMAC, ЮKassa —
повторный запрос платежа через API. Сумма и провайдер сверяются с платежом.
После окончания срока аккаунт возвращается на бесплатный тариф.

| Тариф | Цена | Фото в день | Дней плана | AI-консультант |
|---|---|---|---|---|
| FREE | 0 ₽ | 1 | 1 | — |
| BASE | 299 ₽ / 30 дней | 5 | 7 | — |
| PRO | 499 ₽ / 30 дней | 30 | 28 | 200 сообщений в месяц |

Лимиты заданы в `backend/app/db/models/billing.py`. Первый рацион после анкеты
составляется на 7 дней на любом тарифе. Повторная отправка того же фото не списывает
лимит.

**Даты по Москве.** «Сегодня», дневные лимиты и даты планов считаются в
`APP_TIMEZONE` (по умолчанию `Europe/Moscow`) — и в процессе, и в сессиях PostgreSQL.

## Известные ограничения

- **Каталог курируемый** (69 продуктов, 73 рецепта, средние цены Москвы). Перед
  масштабированием нужны проверка нутриентов диетологом и региональные цены.
  Импорт Open Food Facts описан в [RELEASE.md](RELEASE.md).
- **Город в профиле** пока только отображается; цены считаются по Москве, это
  указано пользователю.
- **Вход через VK** реализован, но не проверен на устройстве: VK ID при обмене кода
  требует `device_id`, который AppAuth не передаёт. Кнопка VK скрыта, пока в сборке
  не задан `VK_CLIENT_ID`. Подробнее в [INTEGRATIONS.md](INTEGRATIONS.md).
- **Ограничение частоты входа** хранится в памяти процесса: на одном сервере с
  несколькими worker-ами лимит умножается на их число.
- Скриншоты в `mobile/screenshots/` сделаны до последних изменений экрана профиля.
