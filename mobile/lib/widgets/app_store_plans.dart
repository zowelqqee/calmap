import 'package:flutter/material.dart';
import 'package:in_app_purchase/in_app_purchase.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/app_store.dart';
import '../core/legal.dart';
import '../core/theme.dart';

/// App Store subscriptions: the plans with their App Store prices, the renewal
/// terms Apple requires next to them, restore and management. Shows nothing
/// where the App Store is unavailable (Android, or products not set up).
class AppStorePlans extends StatefulWidget {
  const AppStorePlans({
    required this.api,
    this.appStoreActive = false,
    this.store,
    super.key,
  });

  final ApiClient api;

  /// An App Store subscription is running: offer to manage it, not to buy.
  final bool appStoreActive;
  final AppStoreSubscriptions? store;

  @override
  State<AppStorePlans> createState() => _AppStorePlansState();
}

class _AppStorePlansState extends State<AppStorePlans> {
  List<ProductDetails> products = const [];
  String? accountId;
  bool loaded = false;

  AppStoreSubscriptions? get store =>
      widget.store ?? AppStoreSubscriptions.shared;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final store = this.store;
    if (store == null || !store.supported) return;
    try {
      final results = await Future.wait<Object>([
        store.products(),
        widget.api.get('/v1/auth/me'),
      ]);
      products = results[0] as List<ProductDetails>;
      accountId = (results[1] as Map<String, dynamic>)['id']?.toString();
    } catch (_) {
      products = const [];
    }
    if (mounted) setState(() => loaded = true);
  }

  Future<void> _restore() async {
    final store = this.store;
    final account = accountId;
    if (store == null || account == null) return;
    await store.restore(account);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Проверяем покупки в App Store…')),
      );
    }
  }

  Future<void> _manage() => launchUrl(
    Uri.parse('https://apps.apple.com/account/subscriptions'),
    mode: LaunchMode.externalApplication,
  );

  @override
  Widget build(BuildContext context) {
    final store = this.store;
    if (store == null || !loaded || accountId == null) {
      return const SizedBox.shrink();
    }
    if (widget.appStoreActive) {
      return Align(
        alignment: Alignment.centerLeft,
        child: TextButton(
          onPressed: _manage,
          child: const Text('Управлять подпиской в App Store'),
        ),
      );
    }
    if (products.isEmpty) return const SizedBox.shrink();
    final small = Theme.of(
      context,
    ).textTheme.bodySmall?.copyWith(color: mutedInk, height: 1.35);
    return ValueListenableBuilder<bool>(
      valueListenable: store.busy,
      builder: (context, busy, _) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Подписка в App Store',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          for (final product in products)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: OutlinedButton(
                onPressed: busy ? null : () => store.buy(product, accountId!),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Column(
                    children: [
                      Text(_title(product)),
                      const SizedBox(height: 2),
                      Text('${product.price} в месяц', style: small),
                    ],
                  ),
                ),
              ),
            ),
          Text(
            'Подписка продлевается автоматически каждый месяц по той же цене, '
            'пока вы не отмените её в настройках App Store не позднее чем за 24 '
            'часа до конца периода. Оплата списывается с вашего Apple ID.',
            style: small,
          ),
          const SizedBox(height: 6),
          LegalLinksText(
            api: widget.api,
            prefix: 'Оформляя подписку, вы принимаете',
            textAlign: TextAlign.start,
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: busy ? null : _restore,
              child: const Text('Восстановить покупки'),
            ),
          ),
        ],
      ),
    );
  }

  /// The App Store title, without the «(Calmap)» suffix StoreKit may add.
  String _title(ProductDetails product) =>
      product.title.replaceAll(RegExp(r'\s*\(.*\)$'), '');
}
