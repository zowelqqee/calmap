import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/theme.dart';

class ProgressScreen extends StatefulWidget {
  const ProgressScreen({required this.api, super.key});
  final ApiClient api;

  @override
  State<ProgressScreen> createState() => _ProgressScreenState();
}

class _ProgressScreenState extends State<ProgressScreen> {
  Map<String, dynamic>? overview;
  bool loading = true;
  String? error;
  int tab = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      overview = await widget.api.get('/v1/progress/overview');
    } on ApiException catch (exception) {
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _addResult() async {
    final weight = TextEditingController(
      text: overview?['current_weight_kg']?.toString() ?? '',
    );
    final waist = TextEditingController();
    final note = TextEditingController();
    DateTime day = DateTime.now();
    final save = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Добавить результат'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Дата'),
                  subtitle: Text(_iso(day)),
                  trailing: const Icon(Icons.calendar_today),
                  onTap: () async {
                    final picked = await showDatePicker(
                      context: context,
                      initialDate: day,
                      firstDate: DateTime.now().subtract(
                        const Duration(days: 3650),
                      ),
                      lastDate: DateTime.now(),
                    );
                    if (picked != null) setDialogState(() => day = picked);
                  },
                ),
                TextField(
                  controller: weight,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(labelText: 'Вес, кг'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: waist,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Талия, см (необязательно)',
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: note,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: 'Заметка'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Сохранить'),
            ),
          ],
        ),
      ),
    );
    if (save == true) {
      final weightValue = double.tryParse(weight.text.replaceAll(',', '.'));
      if (weightValue == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Введите корректный вес')),
          );
        }
      } else {
        try {
          await widget.api.post('/v1/progress/entries', {
            'day': _iso(day),
            'weight_kg': weightValue,
            'waist_cm': double.tryParse(waist.text.replaceAll(',', '.')),
            'note': note.text.trim().isEmpty ? null : note.text.trim(),
          });
          await _load();
        } on ApiException catch (exception) {
          if (mounted) {
            ScaffoldMessenger.of(
              context,
            ).showSnackBar(SnackBar(content: Text(exception.message)));
          }
        }
      }
    }
    weight.dispose();
    waist.dispose();
    note.dispose();
  }

  Future<void> _showReport() async {
    try {
      final report = await widget.api.get('/v1/progress/report');
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (_) => Padding(
          padding: const EdgeInsets.fromLTRB(24, 8, 24, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Отчёт о прогрессе', style: TextStyle(fontSize: 26)),
              const SizedBox(height: 16),
              Text('Изменение веса: ${report['weight_change_kg']} кг'),
              Text(
                'Изменение талии: ${report['waist_change_cm'] ?? 'недостаточно данных'}${report['waist_change_cm'] == null ? '' : ' см'}',
              ),
              Text(
                'Тренировок выполнено: ${report['summary']?['workouts_completed'] ?? 0}',
              ),
              const SizedBox(height: 14),
              Text(
                report['notice'].toString(),
                style: TextStyle(color: ink.withValues(alpha: .58)),
              ),
            ],
          ),
        ),
      );
    } on ApiException catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(exception.message)));
      }
    }
  }

  String _iso(DateTime value) =>
      '${value.year}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final entries = List<dynamic>.from(
      overview?['entries'] as List? ?? const [],
    );
    final points = entries
        .map((raw) => ((raw as Map)['weight_kg'] as num).toDouble())
        .toList();
    final progress = ((overview?['progress_pct'] as num?)?.toDouble() ?? 0)
        .clamp(0.0, 100.0);
    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 120),
          children: [
            ScreenHeading(
              title: 'Прогресс',
              subtitle: 'Ваш путь к цели',
              trailing: IconButton(
                onPressed: _showReport,
                tooltip: 'Отчёт',
                icon: const Icon(Icons.ios_share_outlined),
              ),
            ),
            const SizedBox(height: 22),
            if (loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(40),
                  child: CircularProgressIndicator(color: olive),
                ),
              )
            else if (error != null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Text(error!),
                ),
              )
            else ...[
              Container(
                decoration: BoxDecoration(
                  color: forest,
                  borderRadius: BorderRadius.circular(24),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x24173D31),
                      blurRadius: 28,
                      offset: Offset(0, 12),
                    ),
                  ],
                ),
                child: Padding(
                  padding: const EdgeInsets.all(21),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 86,
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              '${progress.round()}%',
                              maxLines: 1,
                              style: const TextStyle(
                                fontSize: 15,
                                height: 1,
                                color: Colors.white,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(height: 9),
                            SizedBox(
                              width: 66,
                              height: 66,
                              child: CircularProgressIndicator(
                                value: progress / 100,
                                strokeWidth: 7,
                                color: champagne,
                                backgroundColor: Colors.white.withValues(
                                  alpha: .13,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 18),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _goalLabel(overview?['goal']?.toString()),
                              style: Theme.of(context).textTheme.titleLarge
                                  ?.copyWith(color: Colors.white),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              _dateRange(
                                overview?['start_date'],
                                overview?['end_date'],
                              ),
                              style: TextStyle(
                                color: Colors.white.withValues(alpha: .58),
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              '${overview?['current_weight_kg']} кг → ${overview?['target_weight_kg']} кг',
                              style: const TextStyle(
                                color: Color(0xFFE7D4AB),
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 18),
              SegmentedButton<int>(
                segments: const [
                  ButtonSegment(value: 0, label: Text('Вес')),
                  ButtonSegment(value: 1, label: Text('Замеры')),
                  ButtonSegment(value: 2, label: Text('Тренировки')),
                ],
                selected: {tab},
                onSelectionChanged: (value) =>
                    setState(() => tab = value.first),
              ),
              const SizedBox(height: 16),
              if (tab == 0)
                _chartCard(
                  'Динамика веса',
                  points,
                  target: (overview?['target_weight_kg'] as num?)?.toDouble(),
                )
              else if (tab == 1)
                _chartCard(
                  'Талия',
                  entries
                      .where((raw) => (raw as Map)['waist_cm'] != null)
                      .map(
                        (raw) => ((raw as Map)['waist_cm'] as num).toDouble(),
                      )
                      .toList(),
                )
              else
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(22),
                    child: Column(
                      children: [
                        const Icon(
                          Icons.fitness_center,
                          color: olive,
                          size: 40,
                        ),
                        const SizedBox(height: 10),
                        Text(
                          '${overview?['workouts_completed'] ?? 0}',
                          style: const TextStyle(fontSize: 30, color: olive),
                        ),
                        const Text('тренировок выполнено'),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(
                    child: _stat('Вес', '${overview?['current_weight_kg']} кг'),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _stat(
                      'Тренировки',
                      '${overview?['workouts_completed'] ?? 0}',
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _stat(
                      'Средние ккал',
                      '${(overview?['average_kcal'] as num?)?.round() ?? 0}',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              FilledButton.icon(
                onPressed: _addResult,
                icon: const Icon(Icons.add),
                label: const Text('Добавить результат'),
              ),
              const SizedBox(height: 18),
              const Text('История', style: TextStyle(fontSize: 22)),
              const SizedBox(height: 8),
              if (entries.isEmpty)
                const Card(
                  child: Padding(
                    padding: EdgeInsets.all(20),
                    child: Text(
                      'Добавьте первое измерение, чтобы увидеть динамику.',
                    ),
                  ),
                )
              else
                for (final raw in entries.reversed)
                  Card(
                    child: ListTile(
                      leading: const Icon(
                        Icons.monitor_weight_outlined,
                        color: olive,
                      ),
                      title: Text(
                        '${raw['weight_kg']} кг${raw['waist_cm'] == null ? '' : ' · талия ${raw['waist_cm']} см'}',
                      ),
                      subtitle: Text(
                        '${raw['day']}${raw['note'] == null ? '' : ' · ${raw['note']}'}',
                      ),
                    ),
                  ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _chartCard(String title, List<double> values, {double? target}) =>
      Card(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 18),
              SizedBox(
                height: 150,
                width: double.infinity,
                child: values.length < 2
                    ? const Center(child: Text('Нужно минимум два измерения'))
                    : CustomPaint(painter: _LineChartPainter(values, target)),
              ),
            ],
          ),
        ),
      );

  Widget _stat(String title, String value) => Card(
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 16),
      child: Column(
        children: [
          Text(
            value,
            textAlign: TextAlign.center,
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(color: olive),
          ),
          const SizedBox(height: 4),
          Text(
            title,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    ),
  );

  String _goalLabel(String? value) => switch (value) {
    'lose' => 'Цель: похудеть',
    'gain' => 'Цель: набрать',
    _ => 'Цель: поддерживать',
  };

  String _dateRange(dynamic startRaw, dynamic endRaw) {
    final start = DateTime.tryParse(startRaw?.toString() ?? '');
    final end = DateTime.tryParse(endRaw?.toString() ?? '');
    if (start == null || end == null) return 'Период программы';
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
    return '${start.day} ${months[start.month - 1]} — '
        '${end.day} ${months[end.month - 1]} ${end.year}';
  }
}

class _LineChartPainter extends CustomPainter {
  const _LineChartPainter(this.values, this.target);
  final List<double> values;
  final double? target;

  @override
  void paint(Canvas canvas, Size size) {
    final all = [...values, ?target];
    final minValue = all.reduce((a, b) => a < b ? a : b) - 1;
    final maxValue = all.reduce((a, b) => a > b ? a : b) + 1;
    double y(double value) =>
        size.height - (value - minValue) / (maxValue - minValue) * size.height;
    if (target != null) {
      canvas.drawLine(
        Offset(0, y(target!)),
        Offset(size.width, y(target!)),
        Paint()
          ..color = olive.withValues(alpha: .35)
          ..strokeWidth = 2,
      );
    }
    final path = Path();
    for (var index = 0; index < values.length; index++) {
      final point = Offset(
        size.width * index / (values.length - 1),
        y(values[index]),
      );
      if (index == 0) {
        path.moveTo(point.dx, point.dy);
      } else {
        path.lineTo(point.dx, point.dy);
      }
      canvas.drawCircle(point, 4, Paint()..color = olive);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = olive
        ..strokeWidth = 3
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(covariant _LineChartPainter oldDelegate) =>
      oldDelegate.values != values || oldDelegate.target != target;
}
