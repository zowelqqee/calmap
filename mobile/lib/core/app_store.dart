import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:in_app_purchase/in_app_purchase.dart';

import 'api_client.dart';
import 'subscription.dart';

/// App Store subscriptions (In-App Purchase), iOS only.
///
/// StoreKit hands every purchase, renewal and restore to [_purchases]; each one
/// goes to the server, which verifies Apple's signature and updates access. The
/// transaction is finished only after the server accepted it, so a purchase made
/// while offline is delivered again on the next launch.
class AppStoreSubscriptions {
  AppStoreSubscriptions(this.api, {InAppPurchase? store, bool? supported})
    : _store = store,
      supported = supported ?? (!kIsWeb && Platform.isIOS);

  /// Product IDs as created in App Store Connect.
  static const baseProduct = String.fromEnvironment(
    'APPLE_PRODUCT_BASE',
    defaultValue: 'ru.calmap.app.base.month',
  );
  static const proProduct = String.fromEnvironment(
    'APPLE_PRODUCT_PRO',
    defaultValue: 'ru.calmap.app.pro.month',
  );

  /// The app-wide instance (set in main), shared by the screens that sell.
  static AppStoreSubscriptions? shared;

  final ApiClient api;
  final bool supported;

  /// True from tapping «Оформить» until the purchase is delivered or fails.
  final ValueNotifier<bool> busy = ValueNotifier<bool>(false);
  final InAppPurchase? _store;
  StreamSubscription<List<PurchaseDetails>>? _purchases;

  InAppPurchase get store => _store ?? InAppPurchase.instance;

  /// New status after a purchase or restore was accepted by the server.
  void Function(SubscriptionStatus status)? onStatus;

  /// A purchase failed or was refused; the text is for the user.
  void Function(String message)? onError;

  /// Called while a purchase waits (e.g. «Ask to Buy»).
  VoidCallback? onPending;

  void start() {
    if (!supported || _purchases != null) return;
    _purchases = store.purchaseStream.listen(
      handle,
      onError: (Object error) => onError?.call('Покупка не удалась'),
    );
  }

  Future<void> dispose() async => _purchases?.cancel();

  /// Products in the App Store order of price, cheapest first. Empty when the
  /// store is unavailable or the products are not set up yet.
  Future<List<ProductDetails>> products() async {
    if (!supported || !await store.isAvailable()) return const [];
    final response = await store.queryProductDetails({baseProduct, proProduct});
    final products = [...response.productDetails]
      ..sort((a, b) => a.rawPrice.compareTo(b.rawPrice));
    return products;
  }

  /// Starts the purchase; the result arrives through [onStatus] or [onError].
  /// [accountId] becomes the transaction's appAccountToken, which ties the Apple
  /// subscription to this Calmap account.
  Future<void> buy(ProductDetails product, String accountId) async {
    busy.value = true;
    try {
      final started = await store.buyNonConsumable(
        purchaseParam: PurchaseParam(
          productDetails: product,
          applicationUserName: accountId,
        ),
      );
      if (!started) busy.value = false;
    } catch (_) {
      busy.value = false;
      onError?.call('Покупка не удалась. Попробуйте ещё раз');
    }
  }

  Future<void> restore(String accountId) =>
      store.restorePurchases(applicationUserName: accountId);

  @visibleForTesting
  Future<void> handle(List<PurchaseDetails> purchases) async {
    for (final purchase in purchases) {
      if (purchase.status != PurchaseStatus.pending) busy.value = false;
      switch (purchase.status) {
        case PurchaseStatus.pending:
          onPending?.call();
        case PurchaseStatus.canceled:
          if (purchase.pendingCompletePurchase) {
            await complete(purchase);
          }
        case PurchaseStatus.error:
          if (purchase.pendingCompletePurchase) {
            await complete(purchase);
          }
          onError?.call('Покупка не удалась. Попробуйте ещё раз');
        case PurchaseStatus.purchased:
        case PurchaseStatus.restored:
          await _deliver(purchase);
      }
    }
  }

  /// Finishes the transaction in StoreKit.
  @visibleForTesting
  Future<void> complete(PurchaseDetails purchase) =>
      store.completePurchase(purchase);

  Future<void> _deliver(PurchaseDetails purchase) async {
    try {
      final status = SubscriptionStatus.fromJson(
        await api.post('/v1/appstore/transactions', {
          'signed_transaction':
              purchase.verificationData.serverVerificationData,
        }),
      );
      if (purchase.pendingCompletePurchase) {
        await complete(purchase);
      }
      onStatus?.call(status);
    } on ApiException catch (exception) {
      if (exception.statusCode == 409) {
        // Bought on another Calmap account: finishing the transaction is safe,
        // the server keeps it with that account.
        if (purchase.pendingCompletePurchase) {
          await complete(purchase);
        }
        onError?.call(
          'Эта подписка App Store уже привязана к другому аккаунту Calmap',
        );
      } else if (exception.statusCode >= 400 &&
          exception.statusCode < 500 &&
          exception.statusCode != 401) {
        if (purchase.pendingCompletePurchase) {
          await complete(purchase);
        }
        onError?.call('Не удалось подтвердить покупку');
      } else {
        // Offline, signed out or a server error: the transaction stays
        // unfinished and StoreKit delivers it again later.
        onError?.call(
          'Покупка прошла, но сервер пока не ответил. Доступ появится автоматически',
        );
      }
    }
  }
}
