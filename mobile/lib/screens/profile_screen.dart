import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

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

  /// In-app consents currently given (documents from [ConsentRequest.all]).
  Set<String> givenConsents = {};
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
      givenConsents = {
        for (final raw in consents)
          if (raw is Map) raw['document'].toString(),
      };
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
    if (confirmed != true || !mounted) return;
    final Map<String, dynamic> request;
    try {
      request = await widget.api.requestAccountDeletion();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
      return;
    }
    if (!mounted) return;
    if (request['method'] == 'sms') {
      final deleted = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (context) => _DeletionCodeDialog(
          api: widget.api,
          phoneMasked: request['phone_masked'] as String? ?? '',
          resendIn: (request['resend_in'] as num?)?.toInt() ?? 60,
        ),
      );
      if (deleted == true) await widget.onLogout();
      return;
    }
    // No phone number (VK ID): a sign-in made in the last minutes confirms.
    try {
      await widget.api.deleteAccount();
      await widget.onLogout();
    } on ApiException catch (exception) {
      if (!mounted) return;
      if (exception.statusCode != 403) {
        _snack(exception.message);
        return;
      }
      final signOut = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Подтвердите вход'),
          content: const Text(
            'Для удаления аккаунта войдите заново через VK ID и сразу повторите '
            'удаление в профиле.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Войти заново'),
            ),
          ],
        ),
      );
      if (signOut == true) await widget.onLogout();
    }
  }

  Future<void> _toggleConsent(ConsentRequest request) async {
    if (!givenConsents.contains(request.document)) {
      try {
        if (await askConsent(context, widget.api, request) && mounted) {
          setState(() => givenConsents.add(request.document));
        }
      } on ApiException catch (exception) {
        if (mounted) _snack(exception.message);
      }
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Отозвать согласие?'),
        content: Text(
          '«${request.title}» перестанет работать до нового согласия. '
          'Остальные функции продолжат работать.',
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
      await widget.api.delete('/v1/me/consents/${request.document}');
      if (mounted) setState(() => givenConsents.remove(request.document));
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
  }

  String? _phoneLabel(dynamic raw) {
    final n = raw?.toString() ?? '';
    if (n.length != 11) return null;
    return '+7 ${n.substring(1, 4)} ${n.substring(4, 7)}-'
        '${n.substring(7, 9)}-${n.substring(9)}';
  }

  String _subscriptionLabel() {
    final status = subscription;
    if (status == null) return '';
    if (!status.hasAccess) return status.blockedMessage;
    return 'Действует до ${status.untilLabel}';
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
                    '${_phoneLabel(me?['phone']) ?? me?['email'] ?? 'Вход через VK ID'}\n$city',
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
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.fromLTRB(16, 16, 16, 4),
                      child: Text(
                        'Документы и согласия',
                        style: TextStyle(fontSize: 18),
                      ),
                    ),
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
                      leading: const Icon(Icons.monitor_heart_outlined),
                      title: const Text(
                        'Согласие на обработку данных о здоровье',
                      ),
                      trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                      onTap: () =>
                          openLegalPage(context, widget.api, 'health-consent'),
                    ),
                    ListTile(
                      leading: const Icon(Icons.tune_outlined),
                      title: const Text('Как подбираются рекомендации'),
                      trailing: const Icon(Icons.open_in_new_rounded, size: 18),
                      onTap: () =>
                          openLegalPage(context, widget.api, 'recommendations'),
                    ),
                    for (final request in ConsentRequest.all)
                      ListTile(
                        leading: Icon(
                          request == ConsentRequest.aiAssistant
                              ? Icons.auto_awesome_outlined
                              : Icons.photo_camera_outlined,
                        ),
                        title: Text(request.title),
                        subtitle: Text(
                          givenConsents.contains(request.document)
                              ? 'Согласие дано · отозвать'
                              : 'Согласие не дано · дать',
                        ),
                        trailing: IconButton(
                          tooltip: 'Текст согласия',
                          icon: const Icon(Icons.open_in_new_rounded, size: 18),
                          onPressed: () =>
                              openLegalPage(context, widget.api, request.page),
                        ),
                        onTap: () => _toggleConsent(request),
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

/// Second step of account deletion: the code from the SMS sent to the account's
/// number. A wrong code keeps the dialog open; success closes it with `true`.
class _DeletionCodeDialog extends StatefulWidget {
  const _DeletionCodeDialog({
    required this.api,
    required this.phoneMasked,
    required this.resendIn,
  });

  final ApiClient api;
  final String phoneMasked;
  final int resendIn;

  @override
  State<_DeletionCodeDialog> createState() => _DeletionCodeDialogState();
}

class _DeletionCodeDialogState extends State<_DeletionCodeDialog> {
  final code = TextEditingController();
  bool loading = false;
  String? error;
  int resendIn = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _startTimer(widget.resendIn);
  }

  @override
  void dispose() {
    _timer?.cancel();
    code.dispose();
    super.dispose();
  }

  void _startTimer(int seconds) {
    _timer?.cancel();
    resendIn = seconds;
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted || resendIn <= 1) {
        timer.cancel();
        if (mounted) setState(() => resendIn = 0);
        return;
      }
      setState(() => resendIn -= 1);
    });
  }

  Future<void> _resend() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final sent = await widget.api.requestAccountDeletion();
      if (!mounted) return;
      code.clear();
      _startTimer((sent['resend_in'] as num?)?.toInt() ?? 60);
    } on ApiException catch (exception) {
      if (mounted) setState(() => error = exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _delete() async {
    if (code.text.length != 6 || loading) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await widget.api.deleteAccount(code: code.text);
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (exception) {
      if (mounted) {
        setState(() {
          error = exception.message;
          loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Код из SMS'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Отправили код подтверждения на ${widget.phoneMasked}. '
            'После ввода кода аккаунт будет удалён без возможности восстановления.',
          ),
          const SizedBox(height: 16),
          TextField(
            controller: code,
            autofocus: true,
            enabled: !loading,
            keyboardType: TextInputType.number,
            autofillHints: const [AutofillHints.oneTimeCode],
            inputFormatters: [
              FilteringTextInputFormatter.digitsOnly,
              LengthLimitingTextInputFormatter(6),
            ],
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 24, letterSpacing: 6),
            decoration: const InputDecoration(hintText: '••••••'),
            onChanged: (_) => setState(() {}),
            onSubmitted: (_) => _delete(),
          ),
          if (error != null) ...[
            const SizedBox(height: 10),
            Text(error!, style: const TextStyle(color: Colors.redAccent)),
          ],
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: loading || resendIn > 0 ? null : _resend,
              child: Text(
                resendIn > 0
                    ? 'Новый код через $resendIn с'
                    : 'Отправить снова',
              ),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: loading ? null : () => Navigator.pop(context, false),
          child: const Text('Отмена'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
          onPressed: loading || code.text.length != 6 ? null : _delete,
          child: loading
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Удалить аккаунт'),
        ),
      ],
    );
  }
}
