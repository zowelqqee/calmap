import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/local_store.dart';

class _MemoryStore extends LocalStore {
  final Map<String, dynamic> responses = <String, dynamic>{};
  final List<Map<String, dynamic>> queued = <Map<String, dynamic>>[];

  @override
  Future<void> open() async {}

  @override
  Future<dynamic> readResponse(String key) async => responses[key];

  @override
  Future<void> writeResponse(String key, dynamic value) async {
    responses[key] = value;
  }

  @override
  Future<void> enqueue({
    required String method,
    required String path,
    Map<String, dynamic>? body,
  }) async {
    queued.add(<String, dynamic>{'method': method, 'path': path, 'body': body});
  }

  @override
  Future<List<Map<String, dynamic>>> get outbox async => List.of(queued);

  @override
  Future<void> removeFirstOutboxItem() async {
    if (queued.isNotEmpty) queued.removeAt(0);
  }

  @override
  Future<void> clear() async {
    responses.clear();
    queued.clear();
  }
}

/// Fails like an offline network, but only after [delay].
class _SlowOfflineClient extends http.BaseClient {
  _SlowOfflineClient(this.delay);

  final Duration delay;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    await Future<void>.delayed(delay);
    throw const SocketException('offline');
  }
}

class _OfflineClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    throw const SocketException('offline');
  }
}

class _MemorySecureStorage extends FlutterSecureStorage {
  final values = <String, String>{};

  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => values[key];

  @override
  Future<void> write({
    required String key,
    required String? value,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    values.remove(key);
  }
}

/// Answers each request with the status chosen by [statusFor].
class _ScriptedClient extends http.BaseClient {
  _ScriptedClient(this.statusFor);

  final int Function(http.BaseRequest request) statusFor;
  final requests = <String>[];

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests.add('${request.method} ${request.url.path}');
    final status = statusFor(request);
    final body = status >= 400 ? '{"detail": "rejected"}' : '{}';
    return http.StreamedResponse(Stream.value(body.codeUnits), status);
  }
}

void main() {
  test('backend error details are shown in Russian', () {
    expect(humanizeApiError(401, 'invalid code'), 'Неверный код');
    expect(
      humanizeApiError(
        402,
        "daily photo limit reached for the 'free' plan (1/day)",
      ),
      contains('Лимит распознаваний'),
    );
    expect(
      humanizeApiError(422, [
        {
          'loc': ['body', 'password'],
          'msg': 'too short',
        },
      ]),
      'Проверьте введённые данные',
    );
    expect(humanizeApiError(503, 'something internal'), contains('Сервер'));
    expect(humanizeApiError(400, 'Оплата недоступна'), 'Оплата недоступна');
  });

  test(
    'a permanently rejected offline change does not block the queue',
    () async {
      final store = _MemoryStore()
        ..queued.addAll([
          {
            'method': 'POST',
            'path': '/v1/diary/entries',
            'body': {'bad': true},
          },
          {'method': 'POST', 'path': '/v1/progress/entries', 'body': {}},
        ]);
      final secure = _MemorySecureStorage();
      final client = _ScriptedClient(
        (request) => request.url.path == '/v1/diary/entries' ? 422 : 200,
      );
      final api = ApiClient(
        baseUrl: 'http://api.test',
        client: client,
        localStore: store,
        storage: secure,
      );
      await api.saveTokens({'access_token': 'a', 'refresh_token': 'r'});

      await api.get('/v1/auth/me');
      expect(store.queued, isEmpty);
      expect(client.requests.take(2), [
        'POST /v1/diary/entries',
        'POST /v1/progress/entries',
      ]);
    },
  );

  test('server errors keep offline changes for a later retry', () async {
    final store = _MemoryStore()
      ..queued.add({'method': 'POST', 'path': '/v1/diary/entries', 'body': {}});
    final api = ApiClient(
      baseUrl: 'http://api.test',
      client: _ScriptedClient(
        (request) => request.url.path == '/v1/diary/entries' ? 503 : 200,
      ),
      localStore: store,
      storage: _MemorySecureStorage(),
    );
    await api.saveTokens({'access_token': 'a', 'refresh_token': 'r'});

    await api.get('/v1/auth/me');
    expect(store.queued, hasLength(1));
  });

  test(
    'account deletion sends the SMS code; a wrong code keeps the session',
    () async {
      final bodies = <String>[];
      final api = ApiClient(
        baseUrl: 'http://api.test',
        client: _ScriptedClient((request) {
          if (request.method != 'DELETE') return 200;
          final body = (request as http.Request).body;
          bodies.add(body);
          return body.contains('123456') ? 204 : 403;
        }),
        localStore: _MemoryStore(),
        storage: _MemorySecureStorage(),
      );
      await api.saveTokens({'access_token': 'a', 'refresh_token': 'r'});

      await expectLater(
        api.deleteAccount(code: '000000'),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'status', 403)),
      );
      expect(api.hasSession, isTrue);

      await api.deleteAccount(code: '123456');
      expect(bodies.last, '{"code":"123456"}');
      expect(api.hasSession, isFalse);
    },
  );

  test('an unrefreshable session signs the user out once', () async {
    final secure = _MemorySecureStorage();
    var expired = 0;
    final api = ApiClient(
      baseUrl: 'http://api.test',
      client: _ScriptedClient((_) => 401),
      localStore: _MemoryStore(),
      storage: secure,
    )..onSessionExpired = () => expired++;
    await api.saveTokens({'access_token': 'a', 'refresh_token': 'r'});

    await expectLater(api.get('/v1/auth/me'), throwsA(isA<ApiException>()));
    await Future<void>.delayed(Duration.zero);
    expect(expired, 1);
    expect(api.hasSession, isFalse);
    expect(secure.values.containsKey('refresh_token'), isFalse);
  });

  test(
    'a change in flight during sign-out is not queued for the next user',
    () async {
      final store = _MemoryStore();
      final api = ApiClient(
        baseUrl: 'http://api.test',
        client: _SlowOfflineClient(const Duration(milliseconds: 50)),
        localStore: store,
        storage: _MemorySecureStorage(),
      );
      await api.saveTokens({'access_token': 'a', 'refresh_token': 'r'});
      final pending = api.post('/v1/diary/entries', {'name': 'secret'});
      await api.clearSession();
      await expectLater(pending, throwsA(isA<ApiException>()));
      expect(store.queued, isEmpty);
    },
  );

  test('a new sign-in discards the previous session\'s offline data', () async {
    final store = _MemoryStore()
      ..queued.add({'method': 'POST', 'path': '/v1/diary/entries', 'body': {}})
      ..responses['/v1/auth/me'] = {'id': 'previous-user'};
    final api = ApiClient(
      baseUrl: 'http://api.test',
      client: _OfflineClient(),
      localStore: store,
      storage: _MemorySecureStorage(),
    );
    await api.startSession({'access_token': 'b', 'refresh_token': 'r'});
    expect(store.queued, isEmpty);
    expect(store.responses, isEmpty);
  });

  test('completing onboarding is never queued offline', () async {
    final store = _MemoryStore();
    final api = ApiClient(client: _OfflineClient(), localStore: store);

    await expectLater(
      api.post('/v1/onboarding/complete'),
      throwsA(isA<ApiException>()),
    );
    expect(store.queued, isEmpty);
  });

  test('returns cached API data when the network is unavailable', () async {
    final store = _MemoryStore();
    store.responses['/v1/meal-plans/current'] = <String, dynamic>{
      'id': 'cached-plan',
    };
    final api = ApiClient(client: _OfflineClient(), localStore: store);

    expect(await api.get('/v1/meal-plans/current'), <String, dynamic>{
      'id': 'cached-plan',
    });
  });

  test('queues data mutations when the network is unavailable', () async {
    final store = _MemoryStore();
    final api = ApiClient(client: _OfflineClient(), localStore: store);

    await expectLater(
      api.post('/v1/progress/entries', {'weight_kg': 80}),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          contains('сохранено на устройстве'),
        ),
      ),
    );
    expect(store.queued, hasLength(1));
    expect(store.queued.single['path'], '/v1/progress/entries');
  });
}
