import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/local_store.dart';

const _main = 'https://api.test';
const _fallback = 'https://api2.test';

class _MemoryStore extends LocalStore {
  @override
  Future<void> open() async {}

  @override
  Future<dynamic> readResponse(String key) async => null;

  @override
  Future<void> writeResponse(String key, dynamic value) async {}

  @override
  Future<List<Map<String, dynamic>>> get outbox async => const [];
}

/// Two hosts of the same API; [mainUp] decides whether the main one connects.
class _Network extends http.BaseClient {
  bool mainUp = true;
  final List<String> requests = <String>[];

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final url = request.url.toString();
    requests.add('${request.method} $url');
    if (url.startsWith(_main) && !mainUp) {
      throw const SocketException('connection timed out');
    }
    final body = request.url.path == '/health'
        ? {'status': 'ok'}
        : {
            'host': request.url.host,
            'image_url': '$_main/media/recipes/a.webp',
          };
    return http.StreamedResponse(
      Stream.value(utf8.encode(jsonEncode(body))),
      200,
      headers: {'content-type': 'application/json'},
    );
  }
}

ApiClient _client(_Network network) => ApiClient(
  baseUrl: _main,
  fallbackBaseUrl: _fallback,
  client: network,
  localStore: _MemoryStore(),
);

void main() {
  test('stays on the main address while it answers', () async {
    final network = _Network();
    final api = _client(network);

    final first = await api.get('/v1/catalog/recipes');
    await api.get('/v1/catalog/recipes');

    expect(first['host'], 'api.test');
    expect(api.baseUrl, _main);
    expect(network.requests.where((r) => r.contains(_fallback)), isEmpty);
    // One probe for the session, not one per request.
    expect(network.requests.where((r) => r.endsWith('/health')), hasLength(1));
  });

  test('uses the fallback when the main address does not answer', () async {
    final network = _Network()..mainUp = false;
    final api = _client(network);

    final response = await api.get('/v1/catalog/recipes');

    expect(response['host'], 'api2.test');
    expect(api.baseUrl, _fallback);
    // Media of the main address is loaded through the fallback as well.
    expect(response['image_url'], '$_fallback/media/recipes/a.webp');
  });

  test('a read that loses the main address mid-session moves over', () async {
    final network = _Network();
    final api = _client(network);
    await api.get('/v1/catalog/recipes');

    network.mainUp = false;
    final response = await api.get('/v1/catalog/recipes');

    expect(response['host'], 'api2.test');
    expect(api.baseUrl, _fallback);
  });

  test('a change is not repeated on the other address', () async {
    final network = _Network();
    final api = _client(network);
    await api.get('/v1/catalog/recipes');

    network.mainUp = false;
    await expectLater(
      api.post('/v1/auth/phone/verify', {'phone': '79990000000'}),
      throwsA(isA<ApiException>()),
    );
    expect(
      network.requests.where((r) => r.startsWith('POST $_fallback')),
      isEmpty,
    );

    // The next request chooses again and goes to the fallback.
    final retried = await api.post('/v1/auth/phone/verify', {
      'phone': '79990000000',
    });
    expect(retried['host'], 'api2.test');
  });

  test('returns to the main address once it answers again', () async {
    final network = _Network()..mainUp = false;
    final api = _client(network);
    await api.get('/v1/catalog/recipes');
    expect(api.baseUrl, _fallback);

    // A new session (app start) probes the main address first.
    network.mainUp = true;
    final next = _client(network);
    final response = await next.get('/v1/catalog/recipes');
    expect(response['host'], 'api.test');
  });

  test('without a fallback nothing is probed', () async {
    final network = _Network();
    final api = ApiClient(
      baseUrl: _main,
      client: network,
      localStore: _MemoryStore(),
    );

    await api.get('/v1/catalog/recipes');

    expect(network.requests, ['GET $_main/v1/catalog/recipes']);
  });
}
