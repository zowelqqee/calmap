import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/city_catalog.dart';
import '../core/legal.dart';
import '../core/subscription.dart';
import '../core/theme.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({
    required this.api,
    required this.onLogout,
    this.allowLogout = true,
    super.key,
  });

  final ApiClient api;
  final Future<void> Function() onLogout;
  final bool allowLogout;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen>
    with WidgetsBindingObserver {
  Map<String, dynamic>? me;
  Map<String, dynamic>? targets;
  SubscriptionStatus? subscription;
  bool aiConsentGiven = false;
  String city = 'Москва';
  bool loading = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadCity();
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Back from the payment bot: the status may have changed.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load();
  }

  Future<void> _loadCity() async {
    final saved = await widget.api.readPreferredCity();
    if (mounted && saved != null && saved.isNotEmpty) {
      setState(() => city = saved);
    }
  }

  Future<void> _chooseCity() async {
    final selected = await showCityPicker(context, selectedCity: city);
    if (selected == null || selected.name == city) return;
    await widget.api.savePreferredCity(selected.name);
    if (mounted) setState(() => city = selected.name);
  }

  Future<void> _load() async {
    setState(() => loading = true);
    try {
      // Independent requests: targets are unavailable without a subscription,
      // which must not hide the account itself.
      final results = await Future.wait<Map<String, dynamic>?>([
        widget.api.get('/v1/auth/me'),
        widget.api
            .get('/v1/me/targets')
            .then<Map<String, dynamic>?>(
              (value) => value,
              onError: (_) => null,
            ),
        widget.api.get('/v1/me/subscription'),
      ]);
      me = results[0];
      targets = results[1];
      subscription = SubscriptionStatus.fromJson(results[2]!);
      final consents = await widget.api
          .getList('/v1/me/consents')
          .catchError((Object _) => <dynamic>[]);
      aiConsentGiven = consents.any(
        (raw) => raw is Map && raw['document'] == 'ai_assistant',
      );
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _editProfile() async {
    final name = TextEditingController(text: me?['name']?.toString() ?? '');
    final save = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Профиль'),
        content: TextField(
          controller: name,
          decoration: const InputDecoration(labelText: 'Имя'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    if (save == true && name.text.trim().isNotEmpty) {
      try {
        me = await widget.api.patch('/v1/auth/me', {'name': name.text.trim()});
        if (mounted) setState(() {});
      } on ApiException catch (exception) {
        if (mounted) _snack(exception.message);
      }
    }
    name.dispose();
  }

  Future<void> _confirmLogout() async {
    final pending = await widget.api.pendingChanges();
    if (!mounted) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Выйти из аккаунта?'),
        content: Text(
          pending > 0
              ? 'На устройстве есть неотправленные изменения ($pending). '
                    'После выхода они будут потеряны.'
              : 'Данные аккаунта останутся на сервере.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Выйти'),
          ),
        ],
      ),
    );
    if (confirmed == true) await widget.onLogout();
  }

  Future<void> _deleteAccount() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить аккаунт?'),
        content: const Text(
          'Будут безвозвратно удалены профиль, рацион, дневник, тренировки, '
          'прогресс и привязка к Telegram. Оплаченный срок подписки не возвращается '
          'автоматически. Действие нельзя отменить.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить навсегда'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.api.deleteAccount();
      await widget.onLogout();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
  }

  Future<void> _withdrawAiConsent() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Отозвать согласие?'),
        content: const Text(
          'Данные больше не будут передаваться AI-консультанту. Остальные '
          'функции продолжат работать.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Отозвать'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.api.delete('/v1/me/consents/ai_assistant');
      if (mounted) setState(() => aiConsentGiven = false);
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
  }

  String _subscriptionLabel() {
    final status = subscription;
    if (status == null) return '';
    if (!status.hasAccess) return status.blockedMessage;
    final telegram = status.telegramLinked
        ? 'Оплата привязана к Telegram.'
        : 'Оплата проходит в Telegram-боте.';
    return 'Действует до ${status.untilLabel}. $telegram';
  }

  void _snack(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 120),
          children: [
            const ScreenHeading(
              title: 'Профиль',
              subtitle: 'Настройки и персональные данные',
            ),
            const SizedBox(height: 22),
            if (loading)
              const Center(child: CircularProgressIndicator(color: olive))
            else ...[
              Container(
                decoration: BoxDecoration(
                  color: forest,
                  borderRadius: BorderRadius.circular(22),
                ),
                child: ListTile(
                  contentPadding: const EdgeInsets.all(16),
                  leading: const AccentIconTile(
                    Icons.person_outline_rounded,
                    dark: true,
                    size: 52,
                  ),
                  title: Text(
                    me?['name']?.toString() ?? 'Пользователь',
                    style: Theme.of(
                      context,
                    ).textTheme.titleLarge?.copyWith(color: Colors.white),
                  ),
                  subtitle: Text(
                    '${me?['email'] ?? 'Вход через внешний сервис'}\n$city',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: .62),
                    ),
                  ),
                  isThreeLine: true,
                  trailing: IconButton(
                    onPressed: _editProfile,
                    style: IconButton.styleFrom(
                      backgroundColor: Colors.white.withValues(alpha: .1),
                      foregroundColor: Colors.white,
                      side: BorderSide(
                        color: Colors.white.withValues(alpha: .08),
                      ),
                    ),
                    icon: const Icon(Icons.edit_outlined),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: ListTile(
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 6,
                  ),
                  leading: const AccentIconTile(
                    Icons.location_on_outlined,
                    size: 46,
                  ),
                  title: const Text('Город'),
                  subtitle: Text('$city · только на этом устройстве'),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: _chooseCity,
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Текущая цель',
                        style: TextStyle(fontSize: 20),
                      ),
                      const SizedBox(height: 12),
                      Text('${targets?['target_kcal'] ?? '—'} ккал в день'),
                      Text(
                        'Б ${targets?['protein_g'] ?? '—'} · Ж ${targets?['fat_g'] ?? '—'} · У ${targets?['carbs_g'] ?? '—'} г',
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        subscription?.title ?? 'Подписка',
                        style: const TextStyle(fontSize: 20),
                      ),
                      const SizedBox(height: 6),
                      Text(_subscriptionLabel()),
                      if (subscription?.paymentAvailable ?? false) ...[
                        const SizedBox(height: 14),
                        FilledButton.icon(
                          onPressed: () => openPaymentBot(context, widget.api),
                          icon: const Icon(Icons.send_rounded),
                          label: Text(
                            subscription?.state == 'active'
                                ? 'Продлить в Telegram'
                                : 'Оплатить в Telegram',
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Column(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.description_outlined),
                      title: const Text('Пользовательское соглашение'),
                      trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                      onTap: () => openLegalPage(context, widget.api, 'terms'),
                    ),
                    ListTile(
                      leading: const Icon(Icons.privacy_tip_outlined),
                      title: const Text('Политика обработки данных'),
                      trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                      onTap: () =>
                          openLegalPage(context, widget.api, 'privacy'),
                    ),
                    ListTile(
                      leading: const Icon(Icons.verified_user_outlined),
                      title: const Text('Согласие на обработку данных'),
                      trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                      onTap: () =>
                          openLegalPage(context, widget.api, 'consent'),
                    ),
                    ListTile(
                      leading: const Icon(Icons.tune_outlined),
                      title: const Text('Как подбираются рекомендации'),
                      trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                      onTap: () =>
                          openLegalPage(context, widget.api, 'recommendations'),
                    ),
                    if (aiConsentGiven)
                      ListTile(
                        leading: const Icon(Icons.auto_awesome_outlined),
                        title: const Text('Передача данных AI-консультанту'),
                        subtitle: const Text('Согласие дано · отозвать'),
                        onTap: _withdrawAiConsent,
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              if (widget.allowLogout) ...[
                OutlinedButton.icon(
                  onPressed: _confirmLogout,
                  icon: const Icon(Icons.logout),
                  label: const Text('Выйти'),
                ),
                const SizedBox(height: 8),
                TextButton(
                  onPressed: _deleteAccount,
                  style: TextButton.styleFrom(
                    foregroundColor: Colors.red.shade700,
                  ),
                  child: const Text('Удалить аккаунт'),
                ),
              ],
              const SizedBox(height: 12),
              const Text(
                'Рекомендации Calmap не заменяют консультацию врача.',
                textAlign: TextAlign.center,
                style: TextStyle(color: mutedInk, fontSize: 12),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
