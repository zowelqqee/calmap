import 'dart:io';

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
  Future<List<Map<String, dynamic>>> get outbox async => queued;

  @override
  Future<void> removeFirstOutboxItem() async {
    if (queued.isNotEmpty) queued.removeAt(0);
  }
}

class _OfflineClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    throw const SocketException('offline');
  }
}

void main() {
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
      api.patch('/v1/progress/entries/local', {'weight_kg': 80}),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          contains('сохранено на устройстве'),
        ),
      ),
    );
    expect(store.queued, hasLength(1));
    expect(store.queued.single['path'], '/v1/progress/entries/local');
  });
}
