import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'local_store.dart';

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);

  final int statusCode;
  final String message;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({
    String? baseUrl,
    FlutterSecureStorage? storage,
    http.Client? client,
    LocalStore? localStore,
  }) : baseUrl =
           (baseUrl ??
                   const String.fromEnvironment(
                     'API_BASE_URL',
                     defaultValue: 'http://localhost:8000',
                   ))
               .replaceAll(RegExp(r'/$'), ''),
       _storage = storage ?? _defaultStorage,
       _client = client ?? http.Client(),
       _localStore = localStore ?? LocalStore();

  /// The macOS data protection keychain refuses every write from a build that
  /// is not signed with a developer team, which on the desktop build left the
  /// session — and the intro screen's own "Начать" — silently stuck.  The
  /// legacy file-based keychain has no such requirement and is ignored by iOS.
  static const _defaultStorage = FlutterSecureStorage(
    mOptions: MacOsOptions(usesDataProtectionKeychain: false),
  );

  final String baseUrl;
  final FlutterSecureStorage _storage;
  final http.Client _client;
  final LocalStore _localStore;
  bool _flushingOutbox = false;

  static const _networkTimeout = Duration(seconds: 12);

  String? _accessToken;
  String? _refreshToken;

  Future<void> restore() async {
    await _localStore.open();
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

  Future<void> clearSession() async {
    _accessToken = null;
    _refreshToken = null;
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
    await _storage.delete(key: 'plan_id');
    await _localStore.clear();
  }

  Future<void> savePlanId(String id) =>
      _storage.write(key: 'plan_id', value: id);

  Future<String?> readPlanId() => _storage.read(key: 'plan_id');

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
  ]) => _mutate('POST', path, body ?? {});

  Future<Map<String, dynamic>> patch(String path, Map<String, dynamic> body) =>
      _mutate('PATCH', path, body);

  Future<Map<String, dynamic>> delete(String path) =>
      _mutate('DELETE', path, null);

  Future<Map<String, dynamic>> uploadImage({
    required Uint8List bytes,
    required String filename,
  }) async {
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
          contentType: MediaType('image', 'jpeg'),
        ),
      );
      return http.Response.fromStream(await request.send());
    }

    var response = await send();
    if (response.statusCode == 401 && await _refresh()) response = await send();
    final decoded = _decode(response);
    if (decoded is! Map) {
      throw ApiException(500, 'Некорректный ответ распознавания');
    }
    return Map<String, dynamic>.from(decoded);
  }

  Future<Map<String, dynamic>> _request(
    String method,
    Uri uri,
    Map<String, dynamic>? body, {
    required bool retry,
  }) async {
    final response = await _send(method, uri, body, retry: retry);
    final decoded = _decode(response);
    if (decoded is! Map) throw ApiException(500, 'Некорректный ответ API');
    return Map<String, dynamic>.from(decoded);
  }

  Future<dynamic> _getDecoded(String path, {Map<String, String>? query}) async {
    await _flushOutbox();
    var uri = Uri.parse('$baseUrl$path');
    if (query != null) uri = uri.replace(queryParameters: query);
    final cacheKey = _cacheKey(path, query);
    try {
      final response = await _send('GET', uri, null, retry: true);
      final decoded = _decode(response);
      if (_cacheable(path)) await _localStore.writeResponse(cacheKey, decoded);
      return decoded;
    } catch (error) {
      if (_cacheable(path) && _isConnectivityError(error)) {
        final cached = await _localStore.readResponse(cacheKey);
        if (cached != null) return cached;
      }
      rethrow;
    }
  }

  Future<Map<String, dynamic>> _mutate(
    String method,
    String path,
    Map<String, dynamic>? body,
  ) async {
    await _flushOutbox();
    try {
      return await _request(
        method,
        Uri.parse('$baseUrl$path'),
        body,
        retry: true,
      );
    } catch (error) {
      if (_isConnectivityError(error)) {
        if (_queueableMutation(path)) {
          await _localStore.enqueue(method: method, path: path, body: body);
        }
        throw ApiException(
          0,
          _queueableMutation(path)
              ? 'Нет связи. Изменение сохранено на устройстве и отправится автоматически.'
              : 'Нет связи с сервером. Повторите действие, когда интернет появится.',
        );
      }
      rethrow;
    }
  }

  Future<void> _flushOutbox() async {
    if (_flushingOutbox || _accessToken == null) return;
    _flushingOutbox = true;
    try {
      for (final item in await _localStore.outbox) {
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
          _decode(response);
          await _localStore.removeFirstOutboxItem();
        } catch (_) {
          // Preserve ordering: retry the remaining operations next time.
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

  bool _queueableMutation(String path) =>
      path.startsWith('/v1/onboarding/') ||
      path.startsWith('/v1/diary/') ||
      path.startsWith('/v1/workouts/') ||
      path.startsWith('/v1/progress/') ||
      path.startsWith('/v1/catalog/recipes/') ||
      path == '/v1/auth/me';

  bool _isConnectivityError(Object error) =>
      error is SocketException ||
      error is TimeoutException ||
      error is http.ClientException;

  Future<http.Response> _send(
    String method,
    Uri uri,
    Map<String, dynamic>? body, {
    required bool retry,
  }) async {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (_accessToken != null) headers['Authorization'] = 'Bearer $_accessToken';
    http.Response response;
    switch (method) {
      case 'POST':
        response = await _client
            .post(uri, headers: headers, body: jsonEncode(body))
            .timeout(_networkTimeout);
        break;
      case 'PATCH':
        response = await _client
            .patch(uri, headers: headers, body: jsonEncode(body))
            .timeout(_networkTimeout);
        break;
      case 'DELETE':
        response = await _client
            .delete(uri, headers: headers)
            .timeout(_networkTimeout);
        break;
      default:
        response = await _client
            .get(uri, headers: headers)
            .timeout(_networkTimeout);
        break;
    }
    if (response.statusCode == 401 && retry && await _refresh()) {
      return _send(method, uri, body, retry: false);
    }
    return response;
  }

  Future<bool> _refresh() async {
    if (_refreshToken == null) return false;
    try {
      final response = await _client.post(
        Uri.parse('$baseUrl/v1/auth/refresh'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': _refreshToken}),
      );
      if (response.statusCode < 200 || response.statusCode >= 300) return false;
      await saveTokens(
        Map<String, dynamic>.from(jsonDecode(response.body) as Map),
      );
      return true;
    } catch (_) {
      return false;
    }
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
      throw ApiException(
        response.statusCode,
        detail?.toString() ?? 'Ошибка API ${response.statusCode}',
      );
    }
    return _normalizeLocalUrls(decoded);
  }

  /// The local backend uses loopback URLs for generated media. On a phone,
  /// loopback points to the phone itself, so rewrite only those URLs to the
  /// API host compiled into this build.
  dynamic _normalizeLocalUrls(dynamic value) {
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
      final uri = Uri.parse(value);
      return '$baseUrl${uri.path}${uri.hasQuery ? '?${uri.query}' : ''}';
    }
    return value;
  }
}
