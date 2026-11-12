import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/local_store.dart';
import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/plan_screen.dart';

class _NoStore extends LocalStore {
  @override
  Future<void> open() async {}

  @override
  Future<dynamic> readResponse(String key) async => null;

  @override
  Future<void> writeResponse(String key, dynamic value) async {}

  @override
  Future<List<Map<String, dynamic>>> get outbox async => const [];
}

String _today() {
  final now = DateTime.now();
  return '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
}

/// A plan with one lunch; «Съел» logs it in the diary and the undo removes it.
class _PlanServer extends http.BaseClient {
  bool eaten = false;
  final List<String> calls = <String>[];

  Map<String, dynamic> get _plan => {
    'id': 'plan-1',
    'days': [
      {
        'day': _today(),
        'kcal': 2000,
        'protein_g': 100,
        'fat_g': 70,
        'carbs_g': 220,
        'cost': 600,
        'items': [
          {
            'id': 'item-1',
            'recipe_slug': 'buckwheat-chicken',
            'recipe_name': 'Гречка с курицей',
            'meal_type': 'lunch',
            'grams': 350,
            'kcal': 520,
            'protein_g': 40,
            'fat_g': 12,
            'carbs_g': 60,
            'cost': 180,
            'image_url': null,
            'eaten': eaten,
          },
        ],
      },
    ],
  };

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final path = request.url.path;
    calls.add('${request.method} $path');
    Object? body;
    var status = 200;
    if (path == '/v1/meal-plans/current') {
      body = _plan;
    } else if (path.startsWith('/v1/diary/')) {
      body = {'kcal': eaten ? 520 : 0, 'entries': []};
    } else if (path == '/v1/meal-plans/plan-1/items/item-1/eaten') {
      eaten = request.method == 'POST';
      status = eaten ? 201 : 204;
      body = eaten ? {'id': 'entry-1'} : null;
    } else {
      status = 404;
      body = {'detail': 'not found'};
    }
    return http.StreamedResponse(
      Stream.value(body == null ? <int>[] : utf8.encode(jsonEncode(body))),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

void main() {
  testWidgets('«Съел» logs the planned meal and can be undone', (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final server = _PlanServer();
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Scaffold(
          body: PlanScreen(
            api: ApiClient(
              baseUrl: 'http://api.test',
              client: server,
              localStore: _NoStore(),
              storage: const FlutterSecureStorage(),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('Съел'));
    await tester.pumpAndSettle();
    expect(
      server.calls,
      contains('POST /v1/meal-plans/plan-1/items/item-1/eaten'),
    );
    expect(find.text('Съедено · отменить'), findsOneWidget);
    expect(find.text('Записано в дневник: Гречка с курицей'), findsOneWidget);

    await tester.tap(find.text('Съедено · отменить'));
    await tester.pumpAndSettle();
    expect(
      server.calls,
      contains('DELETE /v1/meal-plans/plan-1/items/item-1/eaten'),
    );
    expect(find.text('Съел'), findsOneWidget);
  });
}
