import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'local_store.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  /// The tariff does not include the feature or its limit is used up.
  bool get isPaymentRequired => statusCode == 402;

  @override
  String toString() => message;
}

/// API base URL compiled into the build. Release builds must receive it through
/// `--dart-define-from-file=config/production.json`; only debug builds fall back
/// to a local backend.
String configuredBaseUrl() {
  const configured = String.fromEnvironment('API_BASE_URL');
  if (kReleaseMode) {
    // Android's usesCleartextTraffic and iOS ATS do not govern dart:io sockets,
    // so a release build refuses anything but HTTPS itself.
    if (Uri.tryParse(configured)?.scheme != 'https') {
      throw StateError(
        'API_BASE_URL must be an https:// URL in release builds '
        '(--dart-define-from-file=config/production.json)',
      );
    }
    return configured;
  }
  return configured.isNotEmpty ? configured : 'http://localhost:8000';
}

/// Russian text for the backend's machine-oriented error details.
String humanizeApiError(int statusCode, dynamic detail) {
  if (detail is Map && detail['message'] is String) {
    // Structured errors (e.g. subscription_required) carry their own Russian text.
    return detail['message'] as String;
  }
  if (detail is List) {
    // FastAPI validation errors: [{loc: [...], msg: ...}, ...]
    return 'Проверьте введённые данные';
  }
  final text = detail?.toString() ?? '';
  const known = <String, String>{
    'token expired': 'Сессия истекла. Войдите снова',
    'invalid token': 'Сессия недействительна. Войдите снова',
    'invalid refresh token': 'Сессия истекла. Войдите снова',
    'missing bearer token': 'Войдите в аккаунт',
    'user not found': 'Аккаунт не найден. Войдите снова',
    'no plan for this date': 'На эту дату рациона нет',
    'plan not found': 'Рацион не найден',
    'recipe not found': 'Рецепт не найден',
    'no targets computed yet': 'Нормы ещё не рассчитаны: завершите анкету',
    'compute targets first': 'Нормы ещё не рассчитаны: завершите анкету',
    'image too large': 'Фото слишком большое (максимум 8 МБ)',
    'unsupported image type': 'Формат фото не поддерживается',
    'no items confirmed': 'Отметьте хотя бы один продукт из каталога',
    'nothing logged for that meal': 'В этот приём пищи ничего не записано',
    'AI consultation requires the pro plan':
        'AI-консультант доступен на тарифе PRO',
    'photo recognition is temporarily unavailable':
        'Распознавание фото временно недоступно. Попробуйте позже',
    'AI consultation is temporarily unavailable':
        'AI-консультант временно недоступен. Попробуйте позже',
    'unsupported provider': 'Этот способ входа недоступен',
    'phone must be a Russian mobile number':
        'Введите российский мобильный номер',
    'invalid code': 'Неверный код',
    'code expired': 'Код устарел. Запросите новый',
    'code was sent recently': 'Код уже отправлен. Подождите минуту',
    'too many codes for this number':
        'Слишком много кодов на этот номер. Попробуйте через час',
    'sms limit reached': 'Отправка SMS временно недоступна. Попробуйте позже',
    'sms delivery failed': 'Не удалось отправить SMS. Попробуйте позже',
    'personal data consent is required':
        'Для регистрации нужно согласие на обработку персональных данных',
  };
  for (final entry in known.entries) {
    if (text.startsWith(entry.key)) return entry.value;
  }
  if (text.startsWith('daily photo limit reached')) {
    return 'Лимит распознаваний на сегодня исчерпан. Больше фото — на тарифе PRO';
  }
  if (text.startsWith('monthly assistant limit reached')) {
    return 'Лимит сообщений AI-консультанту на этот месяц исчерпан';
  }
  if (text.startsWith('onboarding is not complete')) {
    return 'Завершите анкету, чтобы продолжить';
  }
  if (text.startsWith('too many') || statusCode == 429) {
    return 'Слишком много попыток. Повторите через минуту';
  }
  if (text.startsWith('invalid OAuth') ||
      text.contains('identity verification failed') ||
      text.contains('rejected the access token')) {
    return 'Не удалось подтвердить вход через внешний сервис';
  }
  if (text.contains('_CLIENT_ID is not configured')) {
    return 'Этот способ входа пока не подключён';
  }
  // Messages written for people (Russian) pass through unchanged.
  if (RegExp('[а-яА-ЯёЁ]').hasMatch(text)) return text;
  return switch (statusCode) {
    401 => 'Сессия истекла. Войдите снова',
    402 => 'Функция доступна на платном тарифе',
    403 => 'Недостаточно прав',
    404 => 'Данные не найдены',
    409 => 'Действие сейчас недоступно. Обновите экран',
    >= 500 => 'Сервер временно недоступен. Попробуйте позже',
    _ => 'Не удалось выполнить запрос',
  };
}

class ApiClient {
  ApiClient({
    String? baseUrl,
    FlutterSecureStorage? storage,
    http.Client? client,
    LocalStore? localStore,
  }) : baseUrl = (baseUrl ?? configuredBaseUrl()).replaceAll(RegExp(r'/$'), ''),
       _storage = storage ?? _defaultStorage,
       _client = client ?? http.Client(),
       _localStore = localStore ?? LocalStore();

  /// iOS: tokens stay on this device — not migrated through backups — and are
  /// readable after the first unlock (needed for requests from the background).
  /// macOS: the data protection keychain refuses every write from a build that
  /// is not signed with a developer team, so the desktop development build uses
  /// the legacy keychain.
  static const _defaultStorage = FlutterSecureStorage(
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.first_unlock_this_device,
    ),
    mOptions: MacOsOptions(usesDataProtectionKeychain: false),
  );

  final String baseUrl;
  final FlutterSecureStorage _storage;
  final http.Client _client;
  final LocalStore _localStore;
  bool _flushingOutbox = false;
  Future<bool>? _refreshing;

  /// Called once when the session can no longer be refreshed (expired, revoked or
  /// deleted account). The app returns to the sign-in screen.
  VoidCallback? onSessionExpired;

  /// Called when the server refuses a feature because there is no paid period or
  /// trial (402 `subscription_required`). The app shows the paywall.
  VoidCallback? onSubscriptionRequired;

  static const _networkTimeout = Duration(seconds: 15);
  static const _slowTimeout = Duration(seconds: 75);

  String? _accessToken;
  String? _refreshToken;

  /// Changes whenever the signed-in session starts or ends. Responses and queued
  /// changes that belong to an older session are dropped instead of being cached
  /// or replayed into the next user's account.
  int _session = 0;

  Future<void> restore() async {
    await _localStore.open();
    // The keychain survives an app reinstall; the app's files do not. A missing
    // install marker therefore means a fresh install: forget stale tokens.
    if (await _localStore.isFirstLaunch()) {
      await _storage.deleteAll();
      await _localStore.markLaunched();
    }
    _accessToken = await _storage.read(key: 'access_token');
    _refreshToken = await _storage.read(key: 'refresh_token');
  }

  bool get hasSession => _accessToken != null;

  Future<void> saveTokens(Map<String, dynamic> payload) async {
    _accessToken = payload['access_token'] as String?;
    _refreshToken = payload['refresh_token'] as String?;
    await _storage.write(key: 'access_token', value: _accessToken);
    await _storage.write(key: 'refresh_token', value: _refreshToken);
  }

  /// Tokens from a successful sign-in: whatever is cached locally belongs to an
  /// earlier session and is discarded first.
  Future<void> startSession(Map<String, dynamic> payload) async {
    _session++;
    await _localStore.clear();
    await saveTokens(payload);
  }

  /// Ends the session on the server (best effort: offline sign-out still works
  /// locally), then forgets it on the device.
  Future<void> signOut() async {
    final token = _accessToken;
    if (token != null) {
      try {
        await _client
            .post(
              Uri.parse('$baseUrl/v1/auth/logout'),
              headers: {'Authorization': 'Bearer $token'},
            )
            .timeout(const Duration(seconds: 5));
      } catch (_) {
        // The refresh token still expires on its own.
      }
    }
    await clearSession();
  }

  Future<void> clearSession() async {
    _session++;
    _accessToken = null;
    _refreshToken = null;
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
    await _storage.delete(key: 'plan_id');
    await _localStore.clear();
  }

  /// Offline changes not yet delivered to the server.
  Future<int> pendingChanges() async => (await _localStore.outbox).length;

  Future<bool> hasSeenIntro() async =>
      await _storage.read(key: 'intro_seen') == 'true';

  Future<void> markIntroSeen() =>
      _storage.write(key: 'intro_seen', value: 'true');

  /// City is a local display preference for now; it is intentionally not sent
  /// to the backend until city-specific availability is supported.
  Future<String?> readPreferredCity() => _storage.read(key: 'preferred_city');

  Future<void> savePreferredCity(String city) =>
      _storage.write(key: 'preferred_city', value: city);

  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, String>? query,
  }) async {
    final decoded = await _getDecoded(path, query: query);
    if (decoded is! Map) throw ApiException(500, 'Некорректный кэш API');
    return Map<String, dynamic>.from(decoded);
  }

  Future<dynamic> getAny(String path, {Map<String, String>? query}) async {
    return _getDecoded(path, query: query);
  }

  Future<List<dynamic>> getList(
    String path, {
    Map<String, String>? query,
  }) async {
    final decoded = await _getDecoded(path, query: query);
    if (decoded is! List) throw ApiException(500, 'Ожидался список от API');
    return decoded;
  }

  Future<Map<String, dynamic>> post(
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final decoded = await _mutate('POST', path, body ?? {});
    if (decoded is! Map) throw ApiException(500, 'Некорректный ответ сервера');
    return Map<String, dynamic>.from(decoded);
  }

  /// POST for endpoints that answer with a list.
  Future<List<dynamic>> postList(
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final decoded = await _mutate('POST', path, body ?? {});
    if (decoded is! List) throw ApiException(500, 'Некорректный ответ сервера');
    return decoded;
  }

  Future<Map<String, dynamic>> patch(
    String path,
    Map<String, dynamic> body,
  ) async {
    final decoded = await _mutate('PATCH', path, body);
    if (decoded is! Map) throw ApiException(500, 'Некорректный ответ сервера');
    return Map<String, dynamic>.from(decoded);
  }

  Future<Map<String, dynamic>> delete(String path) async {
    final decoded = await _mutate('DELETE', path, null);
    return decoded is Map ? Map<String, dynamic>.from(decoded) : {};
  }

  /// Permanently deletes the account on the server, then all local data.
  Future<void> deleteAccount() async {
    await _mutate('DELETE', '/v1/auth/me', null);
    await clearSession();
  }

  Future<Map<String, dynamic>> uploadImage({
    required Uint8List bytes,
    required String filename,
  }) async {
    final lower = filename.toLowerCase();
    final subtype = lower.endsWith('.png')
        ? 'png'
        : lower.endsWith('.webp')
        ? 'webp'
        : lower.endsWith('.heic')
        ? 'heic'
        : 'jpeg';

    Future<http.Response> send() async {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$baseUrl/v1/vision/recognize'),
      );
      if (_accessToken != null) {
        request.headers['Authorization'] = 'Bearer $_accessToken';
      }
      request.files.add(
        http.MultipartFile.fromBytes(
          'image',
          bytes,
          filename: filename,
          contentType: MediaType('image', subtype),
        ),
      );
      final streamed = await _client.send(request).timeout(_slowTimeout);
      return http.Response.fromStream(streamed).timeout(_slowTimeout);
    }

    try {
      var response = await send();
      if (response.statusCode == 401) {
        if (await _refresh()) {
          response = await send();
        } else {
          _expireSession();
        }
      }
      final decoded = _decode(response);
      if (decoded is! Map) {
        throw ApiException(500, 'Некорректный ответ распознавания');
      }
      return Map<String, dynamic>.from(decoded);
    } catch (error) {
      if (_isConnectivityError(error)) {
        throw ApiException(
          0,
          'Нет связи с сервером. Повторите, когда появится интернет.',
        );
      }
      rethrow;
    }
  }

  Future<dynamic> _getDecoded(String path, {Map<String, String>? query}) async {
    final session = _session;
    await _flushOutbox();
    var uri = Uri.parse('$baseUrl$path');
    if (query != null) uri = uri.replace(queryParameters: query);
    final cacheKey = _cacheKey(path, query);
    try {
      final response = await _send('GET', uri, null, retry: true);
      final decoded = _decode(response);
      if (_cacheable(path) && session == _session) {
        await _localStore.writeResponse(cacheKey, decoded);
      }
      return decoded;
    } catch (error) {
      if (_isConnectivityError(error)) {
        if (_cacheable(path)) {
          final cached = await _localStore.readResponse(cacheKey);
          if (cached != null) return cached;
        }
        throw ApiException(0, 'Нет связи с сервером. Проверьте интернет.');
      }
      rethrow;
    }
  }

  Future<dynamic> _mutate(
    String method,
    String path,
    Map<String, dynamic>? body,
  ) async {
    final session = _session;
    await _flushOutbox();
    try {
      final response = await _send(
        method,
        Uri.parse('$baseUrl$path'),
        body,
        retry: true,
      );
      return _decode(response);
    } on TimeoutException {
      // The request may have reached the server; replaying it could duplicate data.
      throw ApiException(
        0,
        'Сервер не ответил вовремя. Обновите экран и проверьте, сохранилось ли изменение.',
      );
    } catch (error) {
      if (_isConnectivityError(error)) {
        if (_queueableMutation(method, path) && session == _session) {
          await _localStore.enqueue(method: method, path: path, body: body);
          throw ApiException(
            0,
            'Нет связи. Изменение сохранено на устройстве и отправится автоматически.',
          );
        }
        throw ApiException(
          0,
          'Нет связи с сервером. Повторите действие, когда интернет появится.',
        );
      }
      rethrow;
    }
  }

  /// Replays offline changes in order. A change the server permanently rejects
  /// (4xx) is dropped so it cannot block everything queued after it; network
  /// failures and 5xx keep it for the next attempt.
  Future<void> _flushOutbox() async {
    if (_flushingOutbox || _accessToken == null) return;
    _flushingOutbox = true;
    final session = _session;
    try {
      for (final item in await _localStore.outbox) {
        // Signed out or switched account mid-flush: the rest is not ours to send.
        if (session != _session) break;
        try {
          final method = item['method'] as String;
          final path = item['path'] as String;
          final body = item['body'] is Map
              ? Map<String, dynamic>.from(item['body'] as Map)
              : null;
          final response = await _send(
            method,
            Uri.parse('$baseUrl$path'),
            body,
            retry: true,
          );
          final status = response.statusCode;
          final retryLater =
              status >= 500 || status == 401 || status == 408 || status == 429;
          if (retryLater) break;
          if (status >= 400) {
            debugPrint('Dropping rejected offline change $method $path');
          }
          await _localStore.removeFirstOutboxItem();
        } catch (_) {
          // Still offline: keep the order and retry on the next request.
          break;
        }
      }
    } finally {
      _flushingOutbox = false;
    }
  }

  String _cacheKey(String path, Map<String, String>? query) {
    if (query == null || query.isEmpty) return path;
    final sorted = Map<String, String>.fromEntries(
      query.entries.toList()..sort((a, b) => a.key.compareTo(b.key)),
    );
    return Uri(path: path, queryParameters: sorted).toString();
  }

  bool _cacheable(String path) => path.startsWith('/v1/');

  /// Offline queue: only changes that are safe to apply later. Plan generation,
  /// onboarding completion, payments, chat and photo recognition need the server
  /// right away and are never queued.
  bool _queueableMutation(String method, String path) {
    if (path == '/v1/onboarding/complete') return false;
    if (path.startsWith('/v1/onboarding/')) return method == 'PATCH';
    return path.startsWith('/v1/diary/') ||
        path.startsWith('/v1/workouts/') ||
        path.startsWith('/v1/progress/') ||
        path.startsWith('/v1/catalog/recipes/') ||
        (path == '/v1/auth/me' && method == 'PATCH');
  }

  bool _isConnectivityError(Object error) =>
      error is SocketException ||
      error is TimeoutException ||
      error is http.ClientException ||
      error is HandshakeException;

  Duration _timeoutFor(String path) =>
      path.startsWith('/v1/assistant/') || path.startsWith('/v1/vision/')
      ? _slowTimeout
      : _networkTimeout;

  Future<http.Response> _send(
    String method,
    Uri uri,
    Map<String, dynamic>? body, {
    required bool retry,
  }) async {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (_accessToken != null) headers['Authorization'] = 'Bearer $_accessToken';
    final timeout = _timeoutFor(uri.path);
    final response = await switch (method) {
      'POST' => _client.post(uri, headers: headers, body: jsonEncode(body)),
      'PATCH' => _client.patch(uri, headers: headers, body: jsonEncode(body)),
      'DELETE' => _client.delete(uri, headers: headers),
      _ => _client.get(uri, headers: headers),
    }.timeout(timeout);
    if (response.statusCode == 401 && retry && _refreshToken != null) {
      if (await _refresh()) return _send(method, uri, body, retry: false);
      _expireSession();
    }
    return response;
  }

  /// One refresh at a time: parallel 401s from several tabs share the same call.
  Future<bool> _refresh() {
    return _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);
  }

  Future<bool> _doRefresh() async {
    final token = _refreshToken;
    if (token == null) return false;
    try {
      final response = await _client
          .post(
            Uri.parse('$baseUrl/v1/auth/refresh'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'refresh_token': token}),
          )
          .timeout(_networkTimeout);
      if (response.statusCode < 200 || response.statusCode >= 300) return false;
      await saveTokens(
        Map<String, dynamic>.from(jsonDecode(response.body) as Map),
      );
      return true;
    } catch (error) {
      // Offline is not an expired session: keep the tokens for later.
      if (_isConnectivityError(error)) {
        throw ApiException(0, 'Нет связи с сервером. Проверьте интернет.');
      }
      return false;
    }
  }

  void _expireSession() {
    if (_accessToken == null) return;
    final callback = onSessionExpired;
    clearSession().whenComplete(() => callback?.call());
  }

  dynamic _decode(http.Response response) {
    dynamic decoded = <String, dynamic>{};
    if (response.body.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(response.bodyBytes));
      } catch (_) {
        decoded = {'detail': response.body};
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map ? decoded['detail'] : null;
      if (response.statusCode == 402 &&
          detail is Map &&
          detail['code'] == 'subscription_required') {
        onSubscriptionRequired?.call();
      }
      throw ApiException(
        response.statusCode,
        humanizeApiError(response.statusCode, detail),
      );
    }
    return _normalizeLocalUrls(decoded);
  }

  /// The local backend uses loopback URLs for generated media. On a phone,
  /// loopback points to the phone itself, so rewrite only those URLs to the
  /// API host compiled into this build.
  dynamic _normalizeLocalUrls(dynamic value) {
    // Release builds talk to an HTTPS API and never receive loopback URLs.
    if (kReleaseMode) return value;
    if (value is List) {
      return value.map(_normalizeLocalUrls).toList();
    }
    if (value is Map) {
      return <String, dynamic>{
        for (final entry in value.entries)
          entry.key.toString(): _normalizeLocalUrls(entry.value),
      };
    }
    if (value is String &&
        (value.startsWith('http://127.0.0.1:8000') ||
            value.startsWith('http://localhost:8000'))) {
      final uri = Uri.tryParse(value);
      if (uri == null) return value;
      return '$baseUrl${uri.path}${uri.hasQuery ? '?${uri.query}' : ''}';
    }
    return value;
  }
}
