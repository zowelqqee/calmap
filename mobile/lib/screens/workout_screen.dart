import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../widgets/muscle_map.dart';

class WorkoutScreen extends StatefulWidget {
  const WorkoutScreen({required this.api, super.key});
  final ApiClient api;

  @override
  State<WorkoutScreen> createState() => _WorkoutScreenState();
}

class _WorkoutScreenState extends State<WorkoutScreen> {
  DateTime selectedDay = DateTime.now();
  Map<String, dynamic>? workout;
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _iso(DateTime value) =>
      '${value.year}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final raw = await widget.api.getAny(
        '/v1/workouts/today',
        query: {'day': _iso(selectedDay)},
      );
      workout = raw is Map ? Map<String, dynamic>.from(raw) : null;
    } on ApiException catch (exception) {
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: selectedDay,
      firstDate: DateTime.now().subtract(const Duration(days: 365)),
      lastDate: DateTime.now().add(const Duration(days: 365)),
    );
    if (picked != null) {
      selectedDay = picked;
      await _load();
    }
  }

  Future<void> _openRegistry() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ExerciseRegistryScreen(api: widget.api),
    ),
  );

  Future<void> _openPreferences() async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => WorkoutPreferencesScreen(api: widget.api),
      ),
    );
    if (changed == true) await _load();
  }

  Future<void> _toggle(Map<String, dynamic> exercise, bool value) async {
    if (workout == null) return;
    try {
      final updated = await widget.api.patch(
        '/v1/workouts/${workout!['id']}/exercises/${exercise['id']}',
        {'is_completed': value, 'is_skipped': false},
      );
      if (mounted) setState(() => workout = updated);
    } on ApiException catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(exception.message)));
      }
    }
  }

  Future<void> _start() async {
    if (workout == null) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) =>
            WorkoutExecutionScreen(api: widget.api, initialWorkout: workout!),
      ),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final exercises = List<dynamic>.from(
      workout?['exercises'] as List? ?? const [],
    );
    final total =
        (workout?['total_count'] as num?)?.toInt() ?? exercises.length;
    final done = (workout?['completed_count'] as num?)?.toInt() ?? 0;
    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 120),
          children: [
            ScreenHeading(
              title: 'Тренировки',
              subtitle: _humanDate(selectedDay),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    onPressed: _openRegistry,
                    tooltip: 'Каталог упражнений',
                    icon: const Icon(Icons.menu_book_outlined),
                  ),
                  IconButton(
                    onPressed: _openPreferences,
                    tooltip: 'Настроить тренировки',
                    icon: const Icon(Icons.tune_rounded),
                  ),
                  IconButton(
                    onPressed: _pickDate,
                    tooltip: 'Календарь',
                    icon: const Icon(Icons.calendar_month_outlined),
                  ),
                ],
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
              _MessageCard(icon: Icons.error_outline, text: error!)
            else if (workout == null)
              const _MessageCard(
                icon: Icons.self_improvement,
                text:
                    'Сегодня восстановление. Прогулка и лёгкая растяжка будут отличным выбором.',
              )
            else ...[
              WorkoutMuscleSummary(
                loads: _muscleLoads(exercises),
                bodySex: workout?['body_sex']?.toString() ?? 'male',
              ),
              const SizedBox(height: 16),
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
                  padding: const EdgeInsets.all(22),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const AccentIconTile(
                            Icons.fitness_center_rounded,
                            dark: true,
                          ),
                          const Spacer(),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 11,
                              vertical: 7,
                            ),
                            decoration: BoxDecoration(
                              color: Colors.white.withValues(alpha: .1),
                              borderRadius: BorderRadius.circular(11),
                            ),
                            child: Text(
                              '$done / $total',
                              style: const TextStyle(
                                color: Color(0xFFE7D4AB),
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 22),
                      Text(
                        workout!['title'].toString(),
                        style: Theme.of(context).textTheme.headlineMedium
                            ?.copyWith(color: Colors.white),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${workout!['duration_minutes']} мин · ≈ ${workout!['estimated_kcal']} ккал',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: .68),
                        ),
                      ),
                      const SizedBox(height: 16),
                      LinearProgressIndicator(
                        value: total == 0 ? 0 : done / total,
                        minHeight: 6,
                        borderRadius: BorderRadius.circular(8),
                        color: champagne,
                        backgroundColor: Colors.white.withValues(alpha: .14),
                      ),
                      const SizedBox(height: 7),
                      Text(
                        '$done из $total упражнений',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: .58),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              for (final raw in exercises)
                Card(
                  child: CheckboxListTile(
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 14,
                      vertical: 7,
                    ),
                    value: (raw as Map)['is_completed'] == true,
                    activeColor: olive,
                    onChanged: (value) =>
                        _toggle(Map<String, dynamic>.from(raw), value ?? false),
                    title: Text(
                      raw['name'].toString(),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    subtitle: Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        _exerciseDetail(raw),
                        style: Theme.of(
                          context,
                        ).textTheme.bodyMedium?.copyWith(color: mutedInk),
                      ),
                    ),
                    secondary: Container(
                      width: 44,
                      height: 44,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: sageLight,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: line),
                      ),
                      child: Text(
                        '${raw['position']}',
                        style: const TextStyle(
                          color: olive,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                ),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _start,
                icon: const Icon(Icons.play_arrow),
                label: Text(
                  workout!['status'] == 'in_progress'
                      ? 'Продолжить'
                      : 'Начать тренировку',
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  String _exerciseDetail(Map raw) {
    final target = raw['primary_muscle']?.toString();
    if (raw['duration_seconds'] != null) {
      final value = '${raw['sets']} × ${raw['duration_seconds']} сек';
      return target == null ? value : '$value · $target';
    }
    final value = '${raw['sets']} подхода × ${raw['reps']} повторений';
    return target == null ? value : '$value · $target';
  }

  Map<String, int> _muscleLoads(List<dynamic> exercises) {
    final loads = <String, int>{};
    for (final raw in exercises) {
      final exercise = raw as Map;
      final primary = exercise['primary_muscle']?.toString();
      if (primary != null && primary.isNotEmpty) {
        loads.update(primary, (value) => value + 2, ifAbsent: () => 2);
      }
      for (final muscle in List<dynamic>.from(
        exercise['secondary_muscles'] as List? ?? const [],
      )) {
        final name = muscle.toString();
        loads.update(name, (value) => value + 1, ifAbsent: () => 1);
      }
    }
    return loads;
  }

  String _humanDate(DateTime value) {
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
    return '${value.day} ${months[value.month - 1]} ${value.year}';
  }
}

class ExerciseRegistryScreen extends StatefulWidget {
  const ExerciseRegistryScreen({required this.api, super.key});

  final ApiClient api;

  @override
  State<ExerciseRegistryScreen> createState() => _ExerciseRegistryScreenState();
}

class WorkoutPreferencesScreen extends StatefulWidget {
  const WorkoutPreferencesScreen({required this.api, super.key});

  final ApiClient api;

  @override
  State<WorkoutPreferencesScreen> createState() =>
      _WorkoutPreferencesScreenState();
}

class _WorkoutPreferencesScreenState extends State<WorkoutPreferencesScreen> {
  List<String> equipment = const [];
  List<String> muscles = const [];
  Set<String> selectedEquipment = <String>{};
  Set<String> selectedMuscles = <String>{};
  bool loading = true;
  bool saving = false;
  String? error;

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
      final result = await Future.wait<dynamic>([
        widget.api.get('/v1/exercises/meta'),
        widget.api.get('/v1/workouts/preferences'),
      ]);
      final meta = Map<String, dynamic>.from(result[0] as Map);
      final preferences = Map<String, dynamic>.from(result[1] as Map);
      equipment = List<String>.from(meta['equipment'] as List? ?? const []);
      muscles = List<String>.from(meta['muscle_groups'] as List? ?? const []);
      selectedEquipment = Set<String>.from(
        preferences['equipment'] as List? ?? const [],
      );
      selectedMuscles = Set<String>.from(
        preferences['focus_muscles'] as List? ?? const [],
      );
    } on ApiException catch (exception) {
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void _toggle(Set<String> selected, String value) {
    setState(() {
      if (!selected.add(value)) selected.remove(value);
    });
  }

  Future<void> _save() async {
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.api.patch('/v1/workouts/preferences', {
        'equipment': selectedEquipment.toList()..sort(),
        'focus_muscles': selectedMuscles.toList()..sort(),
        'rebuild_planned': true,
      });
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (exception) {
      if (mounted) setState(() => error = exception.message);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Настроить тренировки')),
    body: SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 36),
          children: [
            Text(
              'Подберём упражнения под вас',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 6),
            Text(
              'Новые будущие тренировки пересоберутся сразу. Уже начатые и выполненные останутся без изменений.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: mutedInk),
            ),
            const SizedBox(height: 20),
            if (loading)
              const Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator(color: olive)),
              )
            else if (error != null)
              _MessageCard(icon: Icons.error_outline, text: error!)
            else ...[
              Text(
                'Доступное оборудование',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 5),
              Text(
                'Ничего не выбирайте, если доступны все варианты из каталога.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: mutedInk),
              ),
              const SizedBox(height: 10),
              _ChoiceWrap(
                values: equipment,
                selected: selectedEquipment,
                onToggle: (value) => _toggle(selectedEquipment, value),
              ),
              const SizedBox(height: 24),
              Text(
                'Мышцы в приоритете',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 5),
              Text(
                'Выбранные группы будут добавляться в начало каждой тренировки.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: mutedInk),
              ),
              const SizedBox(height: 10),
              _ChoiceWrap(
                values: muscles,
                selected: selectedMuscles,
                onToggle: (value) => _toggle(selectedMuscles, value),
              ),
              const SizedBox(height: 28),
              FilledButton.icon(
                onPressed: saving ? null : _save,
                icon: const Icon(Icons.auto_awesome),
                label: Text(
                  saving ? 'Сохраняем…' : 'Применить к будущим тренировкам',
                ),
              ),
            ],
          ],
        ),
      ),
    ),
  );
}

class _ChoiceWrap extends StatelessWidget {
  const _ChoiceWrap({
    required this.values,
    required this.selected,
    required this.onToggle,
  });

  final List<String> values;
  final Set<String> selected;
  final ValueChanged<String> onToggle;

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      for (final value in values)
        FilterChip(
          label: Text(value),
          selected: selected.contains(value),
          onSelected: (_) => onToggle(value),
        ),
    ],
  );
}

class _ExerciseRegistryScreenState extends State<ExerciseRegistryScreen> {
  List<Map<String, dynamic>> exercises = const [];
  List<String> muscles = const [];
  bool loading = true;
  String? error;
  String? selectedMuscle;
  String search = '';

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
      final result = await Future.wait<dynamic>([
        widget.api.get('/v1/exercises/meta'),
        widget.api.getList('/v1/exercises', query: {'limit': '300'}),
      ]);
      final meta = Map<String, dynamic>.from(result[0] as Map);
      final rows = List<dynamic>.from(result[1] as List);
      exercises = rows
          .map((raw) => Map<String, dynamic>.from(raw as Map))
          .toList();
      muscles = List<String>.from(meta['muscle_groups'] as List? ?? const []);
    } on ApiException catch (exception) {
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  List<Map<String, dynamic>> get filteredExercises {
    final query = search.trim().toLowerCase();
    return exercises.where((exercise) {
      final matchesMuscle =
          selectedMuscle == null ||
          exercise['primary_muscle'] == selectedMuscle;
      final name = exercise['name'].toString().toLowerCase();
      return matchesMuscle && (query.isEmpty || name.contains(query));
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final rows = filteredExercises;
    return Scaffold(
      appBar: AppBar(title: const Text('Каталог упражнений')),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 36),
            children: [
              Text(
                'Упражнения по отдельным мышцам',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 4),
              Text(
                '${exercises.length} движений: силовые, кардио и мобильность.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: mutedInk),
              ),
              const SizedBox(height: 16),
              TextField(
                onChanged: (value) => setState(() => search = value),
                decoration: const InputDecoration(
                  hintText: 'Найти упражнение',
                  prefixIcon: Icon(Icons.search),
                ),
              ),
              const SizedBox(height: 14),
              SizedBox(
                height: 38,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: FilterChip(
                        label: const Text('Все'),
                        selected: selectedMuscle == null,
                        onSelected: (_) =>
                            setState(() => selectedMuscle = null),
                      ),
                    ),
                    for (final muscle in muscles)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: FilterChip(
                          label: Text(muscle),
                          selected: selectedMuscle == muscle,
                          onSelected: (_) =>
                              setState(() => selectedMuscle = muscle),
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              if (loading)
                const Padding(
                  padding: EdgeInsets.all(40),
                  child: Center(child: CircularProgressIndicator(color: olive)),
                )
              else if (error != null)
                _MessageCard(icon: Icons.error_outline, text: error!)
              else if (rows.isEmpty)
                const _MessageCard(
                  icon: Icons.search_off_outlined,
                  text:
                      'Ничего не найдено. Попробуйте другое название или мышцу.',
                )
              else
                for (final exercise in rows)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              exercise['name'].toString(),
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 7),
                            Text(
                              _exerciseMeta(exercise),
                              style: Theme.of(
                                context,
                              ).textTheme.bodyMedium?.copyWith(color: mutedInk),
                            ),
                            if (List<dynamic>.from(
                              exercise['secondary_muscles'] as List? ??
                                  const [],
                            ).isNotEmpty) ...[
                              const SizedBox(height: 5),
                              Text(
                                'Дополнительно: ${(exercise['secondary_muscles'] as List).join(', ')}',
                                style: Theme.of(context).textTheme.bodySmall
                                    ?.copyWith(color: mutedInk),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ),
            ],
          ),
        ),
      ),
    );
  }

  String _exerciseMeta(Map<String, dynamic> exercise) {
    final modality = switch (exercise['modality']) {
      'cardio' => 'кардио',
      'mobility' => 'мобильность',
      _ => 'силовое',
    };
    return '${exercise['primary_muscle']} · ${exercise['equipment']} · '
        '${exercise['difficulty']} · $modality';
  }
}

class WorkoutExecutionScreen extends StatefulWidget {
  const WorkoutExecutionScreen({
    required this.api,
    required this.initialWorkout,
    super.key,
  });
  final ApiClient api;
  final Map<String, dynamic> initialWorkout;

  @override
  State<WorkoutExecutionScreen> createState() => _WorkoutExecutionScreenState();
}

class _WorkoutExecutionScreenState extends State<WorkoutExecutionScreen> {
  late Map<String, dynamic> workout;
  Timer? timer;
  int elapsed = 0;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    workout = Map<String, dynamic>.from(widget.initialWorkout);
    _start();
    timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => elapsed++);
    });
  }

  Future<void> _start() async {
    try {
      workout = await widget.api.post('/v1/workouts/${workout['id']}/start');
      if (mounted) setState(() {});
    } on ApiException {
      // Starting only records the start time; the workout itself works offline.
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  List<Map<String, dynamic>> get exercises => List<dynamic>.from(
    workout['exercises'] as List? ?? const [],
  ).map((raw) => Map<String, dynamic>.from(raw as Map)).toList();
  Map<String, dynamic>? get current {
    for (final exercise in exercises) {
      if (exercise['is_completed'] != true && exercise['is_skipped'] != true) {
        return exercise;
      }
    }
    return null;
  }

  Future<void> _mark({required bool complete}) async {
    final exercise = current;
    if (exercise == null) return _finish();
    setState(() => busy = true);
    try {
      workout = await widget.api.patch(
        '/v1/workouts/${workout['id']}/exercises/${exercise['id']}',
        {'is_completed': complete, 'is_skipped': !complete},
      );
      if (mounted) setState(() {});
      if (current == null) await _finish();
    } on ApiException catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(exception.message)));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _finish() async {
    setState(() => busy = true);
    try {
      final result = await widget.api.post(
        '/v1/workouts/${workout['id']}/complete',
      );
      timer?.cancel();
      if (!mounted) return;
      await Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) =>
              _WorkoutCompleteScreen(workout: result, elapsed: elapsed),
        ),
      );
    } on ApiException catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(exception.message)));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final exercise = current;
    final total = exercises.length;
    final done = exercises
        .where(
          (item) => item['is_completed'] == true || item['is_skipped'] == true,
        )
        .length;
    return Scaffold(
      appBar: AppBar(title: Text(workout['title'].toString())),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(22),
          child: Column(
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '${(elapsed ~/ 60).toString().padLeft(2, '0')}:${(elapsed % 60).toString().padLeft(2, '0')}',
                    style: const TextStyle(fontSize: 28, color: olive),
                  ),
                  Text('$done/$total'),
                ],
              ),
              const SizedBox(height: 10),
              LinearProgressIndicator(
                value: total == 0 ? 1 : done / total,
                minHeight: 9,
                borderRadius: BorderRadius.circular(8),
                color: olive,
              ),
              const Spacer(),
              CircleAvatar(
                radius: 66,
                backgroundColor: warmWhite,
                child: const Icon(Icons.fitness_center, size: 58, color: olive),
              ),
              const SizedBox(height: 28),
              Text(
                exercise?['name']?.toString() ?? 'Всё выполнено',
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 30, color: ink),
              ),
              const SizedBox(height: 10),
              if (exercise != null)
                Text(
                  exercise['duration_seconds'] != null
                      ? '${exercise['sets']} × ${exercise['duration_seconds']} секунд'
                      : '${exercise['sets']} × ${exercise['reps']} повторений',
                  style: const TextStyle(fontSize: 18),
                ),
              const Spacer(),
              FilledButton(
                onPressed: busy ? null : () => _mark(complete: true),
                child: Text(exercise == null ? 'Завершить' : 'Выполнено'),
              ),
              TextButton(
                onPressed: busy || exercise == null
                    ? null
                    : () => _mark(complete: false),
                child: const Text('Пропустить упражнение'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WorkoutCompleteScreen extends StatelessWidget {
  const _WorkoutCompleteScreen({required this.workout, required this.elapsed});
  final Map<String, dynamic> workout;
  final int elapsed;

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.check_circle, size: 86, color: olive),
              const SizedBox(height: 20),
              const Text(
                'Тренировка завершена',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 30, color: ink),
              ),
              const SizedBox(height: 18),
              Text(
                '${elapsed ~/ 60} мин · ≈ ${workout['estimated_kcal']} ккал · ${workout['completed_count']} упражнений',
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 28),
              FilledButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('На главную'),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          Icon(icon, size: 46, color: olive),
          const SizedBox(height: 14),
          Text(
            text,
            textAlign: TextAlign.center,
            style: const TextStyle(height: 1.4),
          ),
        ],
      ),
    ),
  );
}
