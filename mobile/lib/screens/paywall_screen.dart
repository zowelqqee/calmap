import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/legal.dart';
import '../core/subscription.dart';
import '../core/theme.dart';
import 'profile_screen.dart';

/// Shown instead of the app while there is no paid period or trial. The app only
/// states it; access returns as soon as the payment status in the database says so.
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
        const SnackBar(content: Text('Подписка пока не продлена')),
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
            const SizedBox(height: 40),
            const Center(
              child: AccentIconTile(Icons.lock_clock_outlined, size: 72),
            ),
            const SizedBox(height: 24),
            Text(
              status?.title ?? 'Подписка закончилась',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineLarge,
            ),
            const SizedBox(height: 12),
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
              'Ваши данные сохранены и снова станут доступны после продления.',
              textAlign: TextAlign.center,
              style: TextStyle(color: mutedInk, fontSize: 13),
            ),
            const SizedBox(height: 32),
            OutlinedButton(
              onPressed: checking ? null : _recheck,
              child: checking
                  ? const SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('Обновить статус'),
            ),
            const SizedBox(height: 32),
            LegalLinksText(api: widget.api, prefix: 'Документы —'),
          ],
        ),
      ),
    );
  }
}
