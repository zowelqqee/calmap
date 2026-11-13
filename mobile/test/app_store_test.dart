import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:in_app_purchase/in_app_purchase.dart';

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/app_store.dart';
import 'package:calmap_mobile/core/local_store.dart';
import 'package:calmap_mobile/core/subscription.dart';
import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/widgets/app_store_plans.dart';

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

/// The backend: answers the transaction endpoint with [status].
class _Server extends http.BaseClient {
  _Server(this.status);

  int status;
  final List<String> transactions = <String>[];

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    Object body = {'detail': 'not found'};
    var code = 404;
    if (request.url.path == '/v1/appstore/transactions') {
      final sent = jsonDecode((request as http.Request).body) as Map;
      transactions.add(sent['signed_transaction'] as String);
      code = status;
      body = status == 200
          ? {
              'state': 'active',
              'has_access': true,
              'tier': 'pro',
              'app_store_active': true,
            }
          : {'detail': 'refused'};
    } else if (request.url.path == '/v1/auth/me') {
      code = 200;
      body = {'id': '11111111-1111-1111-1111-111111111111'};
    }
    return http.StreamedResponse(
      Stream.value(utf8.encode(jsonEncode(body))),
      code,
      headers: {'content-type': 'application/json'},
    );
  }
}

/// StoreKit stand-in: products and bought products are recorded, nothing real.
class _Subscriptions extends AppStoreSubscriptions {
  _Subscriptions(super.api) : super(supported: true);

  final List<String> completed = <String>[];
  final List<String> bought = <String>[];

  @override
  Future<void> complete(PurchaseDetails purchase) async {
    completed.add(purchase.purchaseID!);
  }

  @override
  Future<List<ProductDetails>> products() async => [
    ProductDetails(
      id: AppStoreSubscriptions.baseProduct,
      title: 'Calmap BASE (Calmap)',
      description: '',
      price: '299,00 ₽',
      rawPrice: 299,
      currencyCode: 'RUB',
    ),
    ProductDetails(
      id: AppStoreSubscriptions.proProduct,
      title: 'Calmap PRO',
      description: '',
      price: '499,00 ₽',
      rawPrice: 499,
      currencyCode: 'RUB',
    ),
  ];

  @override
  Future<void> buy(ProductDetails product, String accountId) async {
    bought.add('${product.id}:$accountId');
  }
}

PurchaseDetails _purchase(String id, PurchaseStatus status) => PurchaseDetails(
  purchaseID: id,
  productID: AppStoreSubscriptions.proProduct,
  verificationData: PurchaseVerificationData(
    localVerificationData: '',
    serverVerificationData: 'jws-$id',
    source: 'app_store',
  ),
  transactionDate: '0',
  status: status,
)..pendingCompletePurchase = true;

(ApiClient, _Server) _api(int status) {
  final server = _Server(status);
  return (
    ApiClient(
      baseUrl: 'http://api.test',
      client: server,
      localStore: _NoStore(),
      storage: const FlutterSecureStorage(),
    ),
    server,
  );
}

void main() {
  test('a purchase is finished only after the server accepted it', () async {
    final (api, server) = _api(200);
    final store = _Subscriptions(api);
    SubscriptionStatus? status;
    store.onStatus = (value) => status = value;

    await store.handle([_purchase('t1', PurchaseStatus.purchased)]);

    expect(server.transactions, ['jws-t1']);
    expect(store.completed, ['t1']);
    expect(status?.tier, 'pro');
    expect(status?.appStoreActive, isTrue);
  });

  test(
    'a server outage leaves the purchase for StoreKit to deliver again',
    () async {
      final (api, _) = _api(503);
      final store = _Subscriptions(api);
      String? error;
      store.onError = (value) => error = value;

      await store.handle([_purchase('t2', PurchaseStatus.purchased)]);

      expect(store.completed, isEmpty);
      expect(error, contains('Доступ появится автоматически'));
    },
  );

  test('a subscription of another account is finished and explained', () async {
    final (api, _) = _api(409);
    final store = _Subscriptions(api);
    String? error;
    store.onError = (value) => error = value;

    await store.handle([_purchase('t3', PurchaseStatus.restored)]);

    expect(store.completed, ['t3']);
    expect(error, contains('другому аккаунту'));
  });

  testWidgets('plans show App Store prices, renewal terms and restore', (
    tester,
  ) async {
    final (api, _) = _api(200);
    final store = _Subscriptions(api);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: AppStorePlans(api: api, store: store),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Calmap BASE'), findsOneWidget);
    expect(find.text('499,00 ₽ в месяц'), findsOneWidget);
    expect(find.textContaining('продлевается автоматически'), findsOneWidget);
    expect(find.text('Восстановить покупки'), findsOneWidget);

    await tester.tap(find.text('Calmap PRO'));
    expect(store.bought, [
      '${AppStoreSubscriptions.proProduct}:11111111-1111-1111-1111-111111111111',
    ]);
  });
}
