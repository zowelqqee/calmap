import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../core/api_client.dart';
import '../core/city_catalog.dart';
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

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? me;
  Map<String, dynamic>? targets;
  Map<String, dynamic>? entitlements;
  String city = 'Москва';
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _loadCity();
    _load();
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
      me = await widget.api.get('/v1/auth/me');
      targets = await widget.api.get('/v1/me/targets');
      entitlements = await widget.api.get('/v1/me/entitlements');
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _upgrade() async {
    try {
      final plans = await widget.api.getList('/v1/billing/plans');
      if (!mounted) return;
      final tier = await showModalBottomSheet<String>(
        context: context,
        builder: (_) => Padding(
          padding: const EdgeInsets.all(22),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Выберите подписку', style: TextStyle(fontSize: 26)),
              const SizedBox(height: 14),
              for (final raw in plans)
                Card(
                  child: ListTile(
                    title: Text((raw as Map)['tier'].toString().toUpperCase()),
                    subtitle: Text('${raw['price_rub']} ₽ / месяц'),
                    trailing: const Icon(Icons.arrow_forward),
                    onTap: () => Navigator.pop(context, raw['tier'].toString()),
                  ),
                ),
            ],
          ),
        ),
      );
      if (tier == null) return;
      final checkout = await widget.api.post('/v1/billing/checkout', {
        'tier': tier,
      });
      final uri = Uri.tryParse(checkout['checkout_url'].toString());
      if (uri == null ||
          !await launchUrl(uri, mode: LaunchMode.externalApplication)) {
        throw ApiException(500, 'Не удалось открыть страницу оплаты');
      }
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
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

  Future<void> _cancel() async {
    try {
      await widget.api.post('/v1/billing/cancel');
      await _load();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
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
                    '${me?['email'] ?? ''}\n$city · ${me?['region_code'] ?? 'RU-MOW'}',
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
                        'Тариф ${entitlements?['tier']?.toString().toUpperCase() ?? 'FREE'}',
                        style: const TextStyle(fontSize: 20),
                      ),
                      const SizedBox(height: 6),
                      Text('Статус: ${_statusLabel(entitlements?['status'])}'),
                      const SizedBox(height: 14),
                      FilledButton(
                        onPressed: _upgrade,
                        child: const Text('Выбрать тариф'),
                      ),
                      if (entitlements?['tier'] != 'free')
                        TextButton(
                          onPressed: _cancel,
                          child: const Text('Отключить продление'),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 20),
              if (widget.allowLogout)
                OutlinedButton.icon(
                  onPressed: widget.onLogout,
                  icon: const Icon(Icons.logout),
                  label: const Text('Выйти'),
                ),
            ],
          ],
        ),
      ),
    );
  }

  String _statusLabel(dynamic status) => switch (status?.toString()) {
    'active' => 'активна',
    'expired' => 'истекла',
    'cancelled' => 'продление отключено',
    _ => 'активна',
  };
}
