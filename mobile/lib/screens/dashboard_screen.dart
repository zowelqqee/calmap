import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import 'assistant_screen.dart';
import 'diary_screen.dart';
import 'profile_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({
    required this.api,
    required this.onSelectTab,
    required this.onLogout,
    super.key,
  });

  final ApiClient api;
  final ValueChanged<int> onSelectTab;
  final Future<void> Function() onLogout;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic>? me;
  Map<String, dynamic>? targets;
  Map<String, dynamic>? plan;
  Map<String, dynamic>? workout;
  Map<String, dynamic>? progress;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => loading = true);
    try {
      me = await widget.api.get('/v1/auth/me');
      targets = await widget.api.get('/v1/me/targets');
      try {
        plan = await widget.api.get('/v1/meal-plans/current');
      } catch (_) {}
      try {
        final raw = await widget.api.getAny('/v1/workouts/today');
        workout = raw is Map ? Map<String, dynamic>.from(raw) : null;
      } catch (_) {}
      try {
        progress = await widget.api.get('/v1/progress/overview');
      } catch (_) {}
    } on ApiException catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(exception.message)));
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  String get _date {
    final now = DateTime.now();
    const weekdays = [
      'понедельник',
      'вторник',
      'среда',
      'четверг',
      'пятница',
      'суббота',
      'воскресенье',
    ];
    const months = [
      'января',
      'февраля',
      'марта',
      'апреля',
      'мая',
      'июня',
      'июля',
      'августа',
      'сентября',
      'октября',
      'ноября',
      'декабря',
    ];
    return '${weekdays[now.weekday - 1]}, ${now.day} ${months[now.month - 1]}';
  }

  void _push(Widget screen) => Navigator.of(
    context,
  ).push(MaterialPageRoute<void>(builder: (_) => screen));

  @override
  Widget build(BuildContext context) => SafeArea(
    child: RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(20, 22, 20, 112),
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Добрый день, ${me?['name'] ?? 'Алексей'}',
                      style: Theme.of(context).textTheme.headlineLarge,
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _date,
                      style: Theme.of(
                        context,
                      ).textTheme.bodyMedium?.copyWith(color: mutedInk),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: 'Профиль',
                onPressed: () => _push(
                  ProfileScreen(api: widget.api, onLogout: widget.onLogout),
                ),
                icon: const Icon(Icons.person_outline_rounded),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Container(
            decoration: BoxDecoration(
              color: forest,
              borderRadius: BorderRadius.circular(22),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x21173D31),
                  blurRadius: 28,
                  offset: Offset(0, 12),
                ),
              ],
            ),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Row(
                children: [
                  const AccentIconTile(Icons.eco_outlined, dark: true),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Text(
                      'Небольшие ежедневные шаги создают устойчивый результат.',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: const Color(0xFFF5F1E8),
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          if (loading)
            const Padding(
              padding: EdgeInsets.all(40),
              child: Center(child: CircularProgressIndicator(color: olive)),
            )
          else ...[
            _dashboardCard(
              icon: Icons.restaurant_menu,
              title: 'Питание',
              subtitle:
                  '${targets?['target_kcal'] ?? '—'} ккал · Б ${targets?['protein_g'] ?? '—'} / Ж ${targets?['fat_g'] ?? '—'} / У ${targets?['carbs_g'] ?? '—'}',
              progress: .67,
              onTap: () => widget.onSelectTab(1),
            ),
            _dashboardCard(
              icon: Icons.fitness_center,
              title: 'Тренировка',
              subtitle: workout == null
                  ? 'Сегодня день восстановления'
                  : '${workout?['title']} · ${workout?['duration_minutes']} мин',
              progress:
                  workout == null || (workout?['total_count'] as num? ?? 0) == 0
                  ? 0
                  : (workout?['completed_count'] as num? ?? 0) /
                        (workout?['total_count'] as num),
              onTap: () => widget.onSelectTab(2),
            ),
            _dashboardCard(
              icon: Icons.shopping_bag_outlined,
              title: 'Список покупок',
              subtitle: plan == null
                  ? 'Сначала создайте рацион'
                  : 'Примерно ${(plan?['cost_total'] as num?)?.round() ?? 0} ₽ на период',
              progress: 0,
              onTap: () => widget.onSelectTab(1),
            ),
            _dashboardCard(
              icon: Icons.insights_outlined,
              title: 'Прогресс',
              subtitle:
                  '${progress?['current_weight_kg'] ?? '—'} кг · цель ${progress?['target_weight_kg'] ?? '—'} кг',
              progress:
                  ((progress?['progress_pct'] as num?)?.toDouble() ?? 0) / 100,
              onTap: () => widget.onSelectTab(3),
            ),
            _dashboardCard(
              icon: Icons.local_fire_department_outlined,
              title: 'Трекер калорий',
              subtitle: 'Записывайте калории вручную за день',
              progress: 0,
              onTap: () => widget.onSelectTab(4),
            ),
          ],
          const SizedBox(height: 14),
          Text(
            'Быстрые действия',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _quickAction(
                  icon: Icons.camera_alt_outlined,
                  label: 'Дневник',
                  onPressed: () => _push(DiaryScreen(api: widget.api)),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _quickAction(
                  icon: Icons.auto_awesome_outlined,
                  label: 'AI-совет',
                  onPressed: () => _push(AssistantScreen(api: widget.api)),
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );

  Widget _dashboardCard({
    required IconData icon,
    required String title,
    required String subtitle,
    required double progress,
    required VoidCallback onTap,
  }) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    decoration: BoxDecoration(
      color: warmWhite,
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: line),
      boxShadow: const [
        BoxShadow(
          color: Color(0x0D173D31),
          blurRadius: 18,
          offset: Offset(0, 7),
        ),
      ],
    ),
    child: Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(17),
          child: Row(
            children: [
              AccentIconTile(icon),
              const SizedBox(width: 15),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 5),
                    Text(
                      subtitle,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(
                        context,
                      ).textTheme.bodyMedium?.copyWith(color: mutedInk),
                    ),
                    if (progress > 0) ...[
                      const SizedBox(height: 11),
                      ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: LinearProgressIndicator(
                          value: progress.clamp(0.0, 1.0),
                          minHeight: 5,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(
                Icons.arrow_forward_ios_rounded,
                size: 16,
                color: mutedInk,
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _quickAction({
    required IconData icon,
    required String label,
    required VoidCallback onPressed,
  }) => Material(
    color: sageLight,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(17),
      side: const BorderSide(color: line),
    ),
    child: InkWell(
      borderRadius: BorderRadius.circular(17),
      onTap: onPressed,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 15),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: olive, size: 20),
            const SizedBox(width: 9),
            Text(label, style: Theme.of(context).textTheme.labelLarge),
          ],
        ),
      ),
    ),
  );
}
