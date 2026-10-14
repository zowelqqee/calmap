import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/subscription.dart';
import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/paywall_screen.dart';

String _iso(Duration fromNow) =>
    DateTime.now().add(fromNow).toUtc().toIso8601String();

class _PaywallServer extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    const body =
        '{"detail": {"code": "subscription_required", "state": "expired", '
        '"message": "Подписка закончилась. Продлите её, чтобы продолжить."}}';
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      402,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );
  }
}

void main() {
  test('active and trial statuses grant access until access_until', () {
    final active = SubscriptionStatus.fromJson({
      'state': 'active',
      'has_access': true,
      'tier': 'pro',
      'access_until': _iso(const Duration(days: 10)),
    });
    expect(active.hasAccess, isTrue);
    expect(active.title, 'Подписка PRO');
    expect(active.daysLeft, 10);

    final trial = SubscriptionStatus.fromJson({
      'state': 'trial',
      'has_access': true,
      'tier': 'trial',
      'access_until': _iso(const Duration(hours: 30)),
    });
    expect(trial.isTrial, isTrue);
    expect(trial.daysLeft, 2);
  });

  test('a cached status stops granting access once its period ends', () {
    final stale = SubscriptionStatus.fromJson({
      'state': 'active',
      'has_access': true,
      'tier': 'base',
      'access_until': _iso(const Duration(minutes: -5)),
    });
    expect(stale.hasAccess, isFalse);
    expect(stale.title, 'Подписка закончилась');

    final staleTrial = SubscriptionStatus.fromJson({
      'state': 'trial',
      'has_access': true,
      'access_until': _iso(const Duration(minutes: -5)),
    });
    expect(staleTrial.title, 'Пробный период закончился');
  });

  test('blocked states explain why', () {
    for (final entry in {
      'trial_ended': 'Пробный период закончился',
      'expired': 'Подписка закончилась',
      'revoked': 'Подписка отменена',
    }.entries) {
      final status = SubscriptionStatus.fromJson({
        'state': entry.key,
        'has_access': false,
      });
      expect(status.hasAccess, isFalse);
      expect(status.title, entry.value);
      expect(status.blockedMessage, startsWith(entry.value));
    }
  });

  test('a 402 subscription_required response opens the paywall', () async {
    var paywall = 0;
    final api = ApiClient(baseUrl: 'http://api.test', client: _PaywallServer())
      ..onSubscriptionRequired = () => paywall++;
    await expectLater(
      api.post('/v1/meal-plans/generate', {'days': 7}),
      throwsA(
        isA<ApiException>()
            .having((e) => e.statusCode, 'status', 402)
            .having(
              (e) => e.message,
              'message',
              contains('Подписка закончилась'),
            ),
      ),
    );
    expect(paywall, 1);
  });

  testWidgets('paywall states the reason and offers Telegram payment', (
    tester,
  ) async {
    var rechecks = 0;
    await tester.binding.setSurfaceSize(const Size(430, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: PaywallScreen(
          api: ApiClient(baseUrl: 'http://api.test'),
          status: SubscriptionStatus.fromJson({
            'state': 'trial_ended',
            'has_access': false,
            'payment_available': true,
          }),
          onRecheck: () async {
            rechecks++;
            return false;
          },
          onLogout: () async {},
        ),
      ),
    );
    expect(find.text('Пробный период закончился'), findsOneWidget);
    expect(find.text('Оплатить в Telegram'), findsOneWidget);
    expect(find.text('BASE'), findsOneWidget);
    expect(find.text('PRO'), findsOneWidget);

    await tester.tap(find.text('Обновить статус'));
    await tester.pumpAndSettle();
    expect(rechecks, 1);
    expect(find.textContaining('Оплата пока не поступила'), findsOneWidget);
  });
}
