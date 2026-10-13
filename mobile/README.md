# Calmap mobile

Готовый Flutter-клиент для API из `../backend`, с нативными проектами iOS и Android.
Скопируйте конфигурационный шаблон и подставьте URL/идентификаторы провайдеров:

```bash
cp config/development.example.json config/development.json
flutter pub get
flutter run --dart-define-from-file=config/development.json
```

Для физического телефона используйте IP машины в LAN, например
`http://192.168.1.20:8000`. В production передайте HTTPS URL API.

Разрешения камеры/галереи, URL scheme `ru.calmap.app`, Apple Sign In entitlement и
AppAuth redirect уже добавлены в native-проекты.

OAuth-кнопки уже подключены. Передайте client IDs:

```bash
flutter run --dart-define-from-file=config/development.json
```

Из внешней консоли Google нужно добавить штатные `GoogleService-Info.plist` (iOS) и
`google-services.json` (Android), а в Apple Developer включить Sign in with Apple для
bundle ID. Это данные провайдеров, их нельзя безопасно положить в репозиторий.

Email/password, splash + 3 intro-экрана, возобновляемый 5-шаговый onboarding, рацион
и замена блюда, список покупок/retail offers, дневник (фото, ручной ввод, повтор,
удаление), подтверждение vision, AI-чат и checkout реализованы.

## Local-first режим

Успешные ответы API сохраняются в контейнере приложения, поэтому уже загруженные
профиль, план, рецепты, тренировки, дневник и прогресс доступны без сети. Изменения
онбординга, дневника, тренировок и прогресса при временном отсутствии связи попадают
в локальную очередь и отправляются при следующем успешном запросе. Изображения
рецептов также кэшируются на устройстве.

Запросы к AI, авторизация, платежи и первая генерация плана требуют backend. Ключи
моделей намеренно не встраиваются в приложение.

Проверки:

```bash
flutter analyze
flutter test
flutter build ios --simulator
```

Сборка приложения для macOS:

```bash
flutter build macos --release
open build/macos/Build/Products/Release/Calmap.app
```

Готовый универсальный пакет для Apple Silicon и Intel находится в
`build/macos/Build/Products/Release/Calmap.app`. Для работы с API запустите backend
на `http://localhost:8000` или передайте другой `API_BASE_URL` через
`--dart-define-from-file`.

Проект проверен на Flutter 3.44.8: `flutter analyze` и widget tests проходят,
собраны iOS Simulator app и Android debug APK. iOS использует Swift Package Manager
без зависимости от CocoaPods.
