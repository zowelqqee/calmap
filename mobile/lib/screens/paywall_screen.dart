import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/legal.dart';
import '../core/subscription.dart';
import '../core/theme.dart';
import 'profile_screen.dart';

/// Shown instead of the app while there is no paid period or trial. Payment
/// happens in the Telegram bot; access returns as soon as the bot reports it.
class PaywallScreen extends StatefulWidget {
  const PaywallScreen({
    required this.api,
    required this.status,
    required this.onRecheck,
    required this.onLogout,
    super.key,
  });

  final ApiClient api;
  final SubscriptionStatus? status;

  /// Re-reads the status; true when access is back (the app then leaves this screen).
  final Future<bool> Function() onRecheck;
  final Future<void> Function() onLogout;

  @override
  State<PaywallScreen> createState() => _PaywallScreenState();
}

class _PaywallScreenState extends State<PaywallScreen> {
  bool checking = false;
  bool openedBot = false;

  Future<void> _pay() async {
    final opened = await openPaymentBot(context, widget.api);
    if (mounted && opened) setState(() => openedBot = true);
  }

  Future<void> _recheck() async {
    setState(() => checking = true);
    var restored = false;
    try {
      restored = await widget.onRecheck();
    } finally {
      if (mounted) setState(() => checking = false);
    }
    if (mounted && !restored) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Оплата пока не поступила. Если вы уже оплатили, подождите минуту.',
          ),
        ),
      );
    }
  }

  void _openProfile() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => SubPage(
        child: ProfileScreen(api: widget.api, onLogout: widget.onLogout),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final status = widget.status;
    final paymentAvailable = status?.paymentAvailable ?? true;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(22, 28, 22, 28),
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: IconButton(
                tooltip: 'Профиль',
                onPressed: _openProfile,
                icon: const Icon(Icons.person_outline_rounded),
              ),
            ),
            const SizedBox(height: 8),
            const Center(
              child: AccentIconTile(Icons.lock_clock_outlined, size: 72),
            ),
            const SizedBox(height: 20),
            Text(
              status?.title ?? 'Подписка закончилась',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineLarge,
            ),
            const SizedBox(height: 10),
            Text(
              status?.blockedMessage ??
                  'Подписка закончилась. Продлите её, чтобы продолжить.',
              textAlign: TextAlign.center,
              style: Theme.of(
                context,
              ).textTheme.bodyLarge?.copyWith(color: mutedInk),
            ),
            const SizedBox(height: 8),
            const Text(
              'Ваши данные сохранены и снова станут доступны после оплаты.',
              textAlign: TextAlign.center,
              style: TextStyle(color: mutedInk, fontSize: 13),
            ),
            const SizedBox(height: 24),
            for (final entry in tariffFeatures.entries) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        entry.key,
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 8),
                      for (final feature in entry.value)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.check_rounded,
                                size: 18,
                                color: olive,
                              ),
                              const SizedBox(width: 8),
                              Expanded(child: Text(feature)),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 10),
            ],
            const SizedBox(height: 10),
            if (paymentAvailable) ...[
              FilledButton.icon(
                onPressed: _pay,
                icon: const Icon(Icons.send_rounded),
                label: const Text('Оплатить в Telegram'),
              ),
              const SizedBox(height: 8),
              const Text(
                'Цены и оплата — в нашем Telegram-боте. Аккаунт привязывается '
                'автоматически, доступ откроется сразу после оплаты.',
                textAlign: TextAlign.center,
                style: TextStyle(color: mutedInk, fontSize: 13),
              ),
            ] else
              const Text(
                'Оплата временно недоступна. Попробуйте позже.',
                textAlign: TextAlign.center,
                style: TextStyle(color: mutedInk),
              ),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: checking ? null : _recheck,
              child: checking
                  ? const SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(
                      openedBot ? 'Я оплатил — проверить' : 'Обновить статус',
                    ),
            ),
            const SizedBox(height: 24),
            LegalLinksText(api: widget.api, prefix: 'Условия оплаты —'),
          ],
        ),
      ),
    );
  }
}
