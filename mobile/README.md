# Calmap — мобильное приложение

Flutter-клиент для API из `../backend`. Платформы: iOS и Android (сборка для macOS
используется только для разработки).

## Конфигурация

Параметры передаются при сборке через `--dart-define-from-file`:

| Ключ | Назначение |
|---|---|
| `API_BASE_URL` | адрес backend; в release — только `https://` |
| `GOOGLE_SERVER_CLIENT_ID` | web client ID Google; пусто — кнопка Google скрыта |
| `VK_CLIENT_ID`, `VK_REDIRECT_URL` | VK ID; пусто — кнопка VK скрыта |

```bash
cp config/development.example.json config/development.json   # локальная разработка
cp config/production.example.json config/production.json     # выпуск
```

Файлы `config/*.json` не коммитятся. Release-сборка без `API_BASE_URL` не
запускается. Для телефона в одной сети с компьютером укажите IP компьютера,
например `http://192.168.1.20:8000`: HTTP разрешён только в debug-сборках.

## Запуск и проверки

```bash
flutter pub get
flutter run --dart-define-from-file=config/development.json
flutter analyze
flutter test
```

Golden-тесты `test/workout_visuals_test.dart` используют системные шрифты macOS и на
других системах пропускаются.

## Выпуск

```bash
flutter build appbundle --release --dart-define-from-file=config/production.json
flutter build ipa --release --dart-define-from-file=config/production.json
```

Подпись Android берётся из `android/key.properties` (не коммитится). Без него
release подписывается debug-ключом, который Google Play не принимает. Полная
инструкция: [../RELEASE.md](../RELEASE.md).

## Поведение без сети

Успешные ответы API кэшируются на устройстве: профиль, рацион, рецепты, тренировки,
дневник и прогресс открываются без интернета. Изменения дневника, тренировок,
прогресса и шагов анкеты без связи сохраняются в очередь и отправляются при
следующем запросе. Изменение, которое сервер отклонил (ошибка 4xx), удаляется из
очереди, чтобы не блокировать остальные.

Без сети не работают: вход, завершение анкеты и составление рациона, оплата,
распознавание фото и AI-консультант. Если запрос превысил время ожидания, он не
повторяется автоматически, чтобы не создать дубликат.

Отсутствие сети при запуске не выходит из аккаунта: показывается кэш или экран
«Повторить». Выход происходит только когда сервер отклонил сессию.

## Экраны

| Файл | Экран |
|---|---|
| `intro_screen.dart` | 3 вводных экрана |
| `auth_screen.dart` | вход и регистрация, Apple/Google/VK, ссылки на документы |
| `onboarding_screen.dart` | анкета из 7 шагов, согласие на обработку данных о здоровье |
| `home_screen.dart` | нижняя навигация: Главная, Питание, Тренировки, Прогресс, Калории |
| `dashboard_screen.dart` | сводка дня; переходы в профиль, дневник, AI-консультанта |
| `plan_screen.dart` | рацион на день, календарь, рецепт, замена блюда, список покупок |
| `workout_screen.dart` | тренировка дня, карта мышц, выполнение |
| `progress_screen.dart` | вес и замеры, отчёт |
| `calorie_tracker_screen.dart`, `diary_screen.dart` | дневник: поиск, ручной ввод, фото |
| `assistant_screen.dart` | AI-консультант (PRO) |
| `profile_screen.dart` | данные, тариф, документы, выход, удаление аккаунта |
