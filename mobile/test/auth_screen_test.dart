import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/local_store.dart';
import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/auth_screen.dart';

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

class _NoSecrets extends FlutterSecureStorage {
  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => null;
}

class _ChannelsServer extends http.BaseClient {
  _ChannelsServer(this.channels);

  final Map<String, dynamic> channels;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final found = request.url.path == '/v1/auth/phone/channels';
    return http.StreamedResponse(
      Stream.value(utf8.encode(jsonEncode(found ? channels : {}))),
      found ? 200 : 404,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

Future<void> _pump(WidgetTester tester, Map<String, dynamic> channels) async {
  await tester.binding.setSurfaceSize(const Size(430, 1400));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
    MaterialApp(
      theme: buildTheme(),
      home: AuthScreen(
        api: ApiClient(
          baseUrl: 'http://api.test',
          client: _ChannelsServer(channels),
          localStore: _NoStore(),
          storage: _NoSecrets(),
        ),
        onAuthenticated: () async {},
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('offers the Telegram code first and SMS as the second option', (
    tester,
  ) async {
    await _pump(tester, {
      'sms': true,
      'telegram_url': 'https://t.me/calmap_bot?start=login',
    });
    expect(find.text('Получить код в Telegram'), findsOneWidget);
    expect(find.text('Получить код по SMS'), findsOneWidget);
  });

  testWidgets('Telegram only: no SMS button', (tester) async {
    await _pump(tester, {
      'sms': false,
      'telegram_url': 'https://t.me/calmap_bot?start=login',
    });
    expect(find.text('Получить код в Telegram'), findsOneWidget);
    expect(find.text('Получить код по SMS'), findsNothing);
    expect(find.textContaining('код пришлёт бот Calmap'), findsOneWidget);
  });

  testWidgets('without the bot the SMS flow stays as before', (tester) async {
    await _pump(tester, {'sms': true, 'telegram_url': null});
    expect(find.text('Получить код'), findsOneWidget);
    expect(find.text('Получить код в Telegram'), findsNothing);
  });
}
