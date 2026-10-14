import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/theme.dart';
import '../widgets/recipe_photo.dart';
import 'diary_screen.dart';

class PlanScreen extends StatefulWidget {
  const PlanScreen({required this.api, super.key});
  final ApiClient api;

  @override
  State<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends State<PlanScreen> {
  Map<String, dynamic>? plan;
  Map<String, dynamic>? diary;
  DateTime selectedDate = DateTime.now();
  bool loading = true;
  String? error;

  String _iso(DateTime value) =>
      '${value.year}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

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
      // The plan covering today is the source of truth. When the previous plan has
      // run out, the next one starts today (its length follows the tariff).
      try {
        plan = await widget.api.get(
          '/v1/meal-plans/current',
          query: {'day': _iso(DateTime.now())},
        );
      } on ApiException catch (exception) {
        if (exception.statusCode != 404) rethrow;
        plan = await widget.api.post('/v1/meal-plans/generate', {
          'date_from': _iso(DateTime.now()),
          'days': 7,
        });
      }
      _selectAvailableDate();
      await _loadDiary();
    } on ApiException catch (exception) {
      // 402 (no subscription) is handled app-wide by the paywall.
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void _selectAvailableDate() {
    final days = List<dynamic>.from(plan?['days'] as List? ?? const []);
    if (days.isEmpty) return;
    if (!days.any((raw) => (raw as Map)['day'] == _iso(selectedDate))) {
      selectedDate = DateTime.parse((days.first as Map)['day'].toString());
    }
  }

  Future<void> _loadDiary() async {
    try {
      diary = await widget.api.get('/v1/diary/${_iso(selectedDate)}');
    } catch (_) {
      diary = null;
    }
  }

  Map<String, dynamic>? get selectedDay {
    for (final raw in List<dynamic>.from(plan?['days'] as List? ?? const [])) {
      if ((raw as Map)['day'] == _iso(selectedDate)) {
        return Map<String, dynamic>.from(raw);
      }
    }
    return null;
  }

  Future<void> _pickDate() async {
    final picked = await showModalBottomSheet<DateTime>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) =>
          _NutritionCalendar(api: widget.api, initialDate: selectedDate),
    );
    if (picked == null || !mounted) return;
    setState(() {
      selectedDate = picked;
      loading = true;
      error = null;
    });
    try {
      plan = await widget.api.get(
        '/v1/meal-plans/current',
        query: {'day': _iso(picked)},
      );
      await _loadDiary();
    } on ApiException catch (exception) {
      error = exception.statusCode == 404
          ? 'На выбранный день рацион ещё не составлен'
          : exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _regenerate() async {
    setState(() => loading = true);
    try {
      final generated = await widget.api.post('/v1/meal-plans/generate', {
        'date_from': _iso(selectedDate),
        'days': 7,
      });
      plan = generated;
      _selectAvailableDate();
      await _loadDiary();
    } on ApiException catch (exception) {
      // 402 (no subscription) is handled app-wide by the paywall.
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _swap(String itemId) async {
    setState(() => loading = true);
    try {
      plan = await widget.api.post(
        '/v1/meal-plans/${plan!['id']}/items/$itemId/swap',
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Блюдо заменено, рацион пересчитан')),
        );
      }
    } on ApiException catch (exception) {
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void _openSubPage(Widget screen) => _open(SubPage(child: screen));

  void _open(Widget screen) => Navigator.of(
    context,
  ).push(MaterialPageRoute<void>(builder: (_) => screen));

  @override
  Widget build(BuildContext context) {
    final day = selectedDay;
    final items = List<dynamic>.from(day?['items'] as List? ?? const []);
    items.sort(
      (a, b) => _mealOrder(
        (a as Map)['meal_type'].toString(),
      ).compareTo(_mealOrder((b as Map)['meal_type'].toString())),
    );
    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 120),
          children: [
            ScreenHeading(
              title: 'Питание',
              subtitle: _humanDate(selectedDate),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    onPressed: _pickDate,
                    tooltip: 'Календарь',
                    icon: const Icon(Icons.calendar_month_outlined),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    onPressed: () => _showNutritionInfo(context),
                    tooltip: 'Как составлен рацион',
                    icon: const Icon(Icons.info_outline_rounded),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 22),
            if (loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(44),
                  child: CircularProgressIndicator(color: olive),
                ),
              )
            else if (error != null)
              _ErrorCard(message: error!, retry: _load)
            else if (day == null)
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(22),
                  child: Text('Рацион на этот день отсутствует.'),
                ),
              )
            else ...[
              _nutritionSummary(day),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () =>
                          _openSubPage(DiaryScreen(api: widget.api)),
                      icon: const Icon(Icons.camera_alt_outlined),
                      label: const Text('Записать еду'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _open(
                        ShoppingListScreen(
                          api: widget.api,
                          plan: plan!,
                          selectedDay: selectedDate,
                        ),
                      ),
                      icon: const Icon(Icons.shopping_bag_outlined),
                      label: const Text('Где купить'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 22),
              Text(
                'План на день',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 11),
              for (final raw in items)
                _mealCard(Map<String, dynamic>.from(raw as Map)),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _regenerate,
                icon: const Icon(Icons.refresh),
                label: const Text('Обновить рацион'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _nutritionSummary(Map<String, dynamic> day) {
    final consumed = (diary?['kcal'] as num?)?.toDouble() ?? 0;
    final target = (plan?['target_kcal'] as num?)?.toDouble() ?? 1;
    return Container(
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
        child: Column(
          children: [
            Row(
              children: [
                SizedBox(
                  width: 84,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '${consumed.round()} ккал',
                        maxLines: 1,
                        style: const TextStyle(
                          fontSize: 13,
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
                          value: (consumed / target).clamp(0.0, 1.0),
                          strokeWidth: 7,
                          color: champagne,
                          backgroundColor: Colors.white.withValues(alpha: .12),
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
                        'Цель ${target.round()} ккал',
                        style: Theme.of(
                          context,
                        ).textTheme.titleLarge?.copyWith(color: Colors.white),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        'План ${(day['kcal'] as num?)?.round()} ккал · примерно ${(day['cost'] as num?)?.round()} ₽',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: .67),
                        ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        'Осталось ${((target - consumed).clamp(0, target)).round()} ккал',
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
            const SizedBox(height: 18),
            Row(
              children: [
                Expanded(
                  child: _macro(
                    'Белки',
                    diary?['protein_g'],
                    day['protein_g'],
                    'Б',
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _macro('Жиры', diary?['fat_g'], day['fat_g'], 'Ж'),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _macro(
                    'Углеводы',
                    diary?['carbs_g'],
                    day['carbs_g'],
                    'У',
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _macro(
    String title,
    dynamic consumedRaw,
    dynamic targetRaw,
    String short,
  ) {
    final consumed = (consumedRaw as num?)?.toDouble() ?? 0;
    final target = (targetRaw as num?)?.toDouble() ?? 1;
    return Column(
      children: [
        Text(
          short,
          style: const TextStyle(
            color: Color(0xFFE7D4AB),
            fontSize: 15,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: (consumed / target).clamp(0.0, 1.0),
            minHeight: 4,
            color: const Color(0xFFE7D4AB),
            backgroundColor: Colors.white.withValues(alpha: .14),
          ),
        ),
        const SizedBox(height: 7),
        Text(
          '${consumed.round()}/${target.round()} г',
          style: const TextStyle(
            color: Colors.white,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
        Text(
          title,
          style: TextStyle(
            fontSize: 10,
            color: Colors.white.withValues(alpha: .55),
          ),
        ),
      ],
    );
  }

  Widget _mealCard(Map<String, dynamic> item) {
    final type = item['meal_type'].toString();
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: () => _open(
          RecipeDetailScreen(
            api: widget.api,
            item: item,
            plan: plan!,
            selectedDay: selectedDate,
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(13),
          child: Row(
            children: [
              RecipePhoto(
                mealType: type,
                recipeName: item['recipe_name']?.toString(),
                imageUrl: item['image_url']?.toString(),
                width: 70,
                height: 70,
                borderRadius: BorderRadius.circular(16),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${_mealLabel(type)} · ${_mealTime(type)}',
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: mutedInk),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      item['recipe_name'].toString(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '${(item['kcal'] as num?)?.round()} ккал · примерно ${(item['cost'] as num?)?.round()} ₽',
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: mutedInk),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: () => _swap(item['id'].toString()),
                tooltip: 'Заменить',
                icon: const Icon(Icons.swap_horiz_rounded, color: olive),
              ),
            ],
          ),
        ),
      ),
    );
  }

  int _mealOrder(String type) => switch (type) {
    'breakfast' => 0,
    'snack' => 1,
    'lunch' => 2,
    _ => 3,
  };
  String _mealLabel(String type) => switch (type) {
    'breakfast' => 'Завтрак',
    'snack' => 'Перекус',
    'lunch' => 'Обед',
    _ => 'Ужин',
  };
  String _mealTime(String type) => switch (type) {
    'breakfast' => '08:00',
    'snack' => '11:30',
    'lunch' => '14:00',
    _ => '19:00',
  };
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

  void _showNutritionInfo(BuildContext context) => showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (_) => const Padding(
      padding: EdgeInsets.fromLTRB(24, 8, 24, 30),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('О рационе', style: TextStyle(fontSize: 26)),
          SizedBox(height: 12),
          Text(
            'Калории рассчитаны по формуле Mifflin–St Jeor. БЖУ распределены в пропорции 30/25/45. Цены примерные и могут отличаться от фактических.',
            style: TextStyle(height: 1.5),
          ),
        ],
      ),
    ),
  );
}

class _NutritionCalendar extends StatefulWidget {
  const _NutritionCalendar({required this.api, required this.initialDate});

  final ApiClient api;
  final DateTime initialDate;

  @override
  State<_NutritionCalendar> createState() => _NutritionCalendarState();
}

class _NutritionCalendarState extends State<_NutritionCalendar> {
  late DateTime month;
  late DateTime selected;
  List<dynamic> days = const [];
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    selected = widget.initialDate;
    month = DateTime(selected.year, selected.month);
    _load();
  }

  String _iso(DateTime value) =>
      '${value.year}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  Future<void> _load() async {
    setState(() {
      loading = true;
      error = null;
    });
    final last = DateTime(month.year, month.month + 1, 0);
    try {
      days = await widget.api.getList(
        '/v1/meal-plans/calendar',
        query: {'date_from': _iso(month), 'date_to': _iso(last)},
      );
    } on ApiException catch (exception) {
      error = exception.message;
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void _changeMonth(int delta) {
    month = DateTime(month.year, month.month + delta);
    _load();
  }

  @override
  Widget build(BuildContext context) {
    const monthNames = [
      'Январь',
      'Февраль',
      'Март',
      'Апрель',
      'Май',
      'Июнь',
      'Июль',
      'Август',
      'Сентябрь',
      'Октябрь',
      'Ноябрь',
      'Декабрь',
    ];
    const weekdayNames = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
    final lastDay = DateTime(month.year, month.month + 1, 0).day;
    final offset = month.weekday - 1;
    final records = {
      for (final raw in days)
        (raw as Map)['day'].toString(): Map<String, dynamic>.from(raw),
    };
    return SafeArea(
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * .72,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(22, 0, 22, 20),
          child: Column(
            children: [
              Row(
                children: [
                  IconButton(
                    onPressed: () => _changeMonth(-1),
                    icon: const Icon(Icons.chevron_left),
                  ),
                  Expanded(
                    child: Text(
                      '${monthNames[month.month - 1]} ${month.year}',
                      textAlign: TextAlign.center,
                      style: const TextStyle(fontSize: 24),
                    ),
                  ),
                  IconButton(
                    onPressed: () => _changeMonth(1),
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  for (final label in weekdayNames)
                    Expanded(
                      child: Text(
                        label,
                        textAlign: TextAlign.center,
                        style: TextStyle(color: ink.withValues(alpha: .5)),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              if (loading)
                const Expanded(
                  child: Center(child: CircularProgressIndicator(color: olive)),
                )
              else if (error != null)
                Expanded(
                  child: Center(
                    child: Text(error!, textAlign: TextAlign.center),
                  ),
                )
              else
                Expanded(
                  child: GridView.builder(
                    physics: const NeverScrollableScrollPhysics(),
                    gridDelegate:
                        const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 7,
                          childAspectRatio: .82,
                        ),
                    itemCount: offset + lastDay,
                    itemBuilder: (_, index) {
                      if (index < offset) return const SizedBox.shrink();
                      final dayNumber = index - offset + 1;
                      final value = DateTime(
                        month.year,
                        month.month,
                        dayNumber,
                      );
                      final record = records[_iso(value)];
                      final isSelected = _iso(value) == _iso(selected);
                      return InkWell(
                        borderRadius: BorderRadius.circular(18),
                        onTap: record == null
                            ? null
                            : () => setState(() => selected = value),
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Container(
                              width: 38,
                              height: 38,
                              alignment: Alignment.center,
                              decoration: BoxDecoration(
                                color: isSelected ? olive : Colors.transparent,
                                shape: BoxShape.circle,
                              ),
                              child: Text(
                                '$dayNumber',
                                style: TextStyle(
                                  color: isSelected
                                      ? Colors.white
                                      : record == null
                                      ? Colors.black26
                                      : ink,
                                ),
                              ),
                            ),
                            const SizedBox(height: 3),
                            Container(
                              width: 6,
                              height: 6,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: record?['has_weight_record'] == true
                                    ? olive
                                    : Colors.transparent,
                              ),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
              Row(
                children: [
                  const SizedBox(
                    width: 10,
                    height: 10,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: olive,
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Expanded(child: Text('Есть запись веса')),
                  TextButton(
                    onPressed: () {
                      final now = DateTime.now();
                      setState(() {
                        selected = now;
                        month = DateTime(now.year, now.month);
                      });
                      _load();
                    },
                    child: const Text('Сегодня'),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: records.containsKey(_iso(selected))
                    ? () => Navigator.pop(context, selected)
                    : null,
                child: const Text('Открыть рацион'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class RecipeDetailScreen extends StatefulWidget {
  const RecipeDetailScreen({
    required this.api,
    required this.item,
    required this.plan,
    required this.selectedDay,
    super.key,
  });
  final ApiClient api;
  final Map<String, dynamic> item;
  final Map<String, dynamic> plan;
  final DateTime selectedDay;

  @override
  State<RecipeDetailScreen> createState() => _RecipeDetailScreenState();
}

class _RecipeDetailScreenState extends State<RecipeDetailScreen> {
  Map<String, dynamic>? recipe;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      recipe = await widget.api.get(
        '/v1/catalog/recipes/${widget.item['recipe_slug']}',
      );
    } on ApiException catch (exception) {
      // The plan item still has name, weight and nutrients to show.
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Рецепт не загрузился: ${exception.message}')),
        );
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _favorite() async {
    if (recipe == null) return;
    final favorite = recipe!['is_favorite'] == true;
    try {
      final result = favorite
          ? await widget.api.delete(
              '/v1/catalog/recipes/${recipe!['slug']}/favorite',
            )
          : await widget.api.post(
              '/v1/catalog/recipes/${recipe!['slug']}/favorite',
            );
      if (mounted) {
        setState(
          () => recipe!['is_favorite'] = result['is_favorite'] ?? !favorite,
        );
      }
    } on ApiException catch (exception) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(exception.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final ingredients = List<dynamic>.from(
      recipe?['ingredients'] as List? ?? const [],
    );
    final instructions = List<dynamic>.from(
      recipe?['instructions'] as List? ?? const [],
    );
    return Scaffold(
      appBar: AppBar(
        title: const Text('Блюдо'),
        actions: [
          IconButton(
            onPressed: loading ? null : _favorite,
            icon: Icon(
              recipe?['is_favorite'] == true
                  ? Icons.favorite
                  : Icons.favorite_border,
              color: olive,
            ),
          ),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator(color: olive))
          : ListView(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 30),
              children: [
                RecipePhoto(
                  mealType: widget.item['meal_type']?.toString() ?? 'lunch',
                  recipeName:
                      recipe?['name']?.toString() ??
                      widget.item['recipe_name']?.toString(),
                  imageUrl: recipe?['image_url']?.toString(),
                  width: double.infinity,
                  height: 220,
                  borderRadius: BorderRadius.circular(24),
                ),
                const SizedBox(height: 22),
                Text(
                  recipe?['name']?.toString() ??
                      widget.item['recipe_name'].toString(),
                  style: Theme.of(context).textTheme.headlineLarge,
                ),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    color: sageLight,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: line),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceAround,
                    children: [
                      _RecipeMetric(
                        '${(widget.item['kcal'] as num?)?.round()}',
                        'ккал',
                      ),
                      const _MetricDivider(),
                      _RecipeMetric(
                        '≈ ${(widget.item['cost'] as num?)?.round()} ₽',
                        'стоимость',
                      ),
                      const _MetricDivider(),
                      _RecipeMetric('${recipe?['prep_minutes']} мин', 'время'),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  recipe?['price_notice']?.toString() ??
                      'Цены примерные и могут отличаться от фактических.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: mutedInk),
                ),
                const SizedBox(height: 24),
                Text(
                  'Ингредиенты',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                for (final raw in ingredients)
                  Card(
                    child: ListTile(
                      title: Text(raw['name'].toString()),
                      subtitle: Text(
                        '${raw['grams']} г · ориентировочная цена',
                      ),
                      trailing: Text(
                        raw['estimated_cost'] == null
                            ? '—'
                            : '≈ ${(raw['estimated_cost'] as num).round()} ₽',
                      ),
                    ),
                  ),
                const SizedBox(height: 18),
                Text(
                  'Как приготовить',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                for (var index = 0; index < instructions.length; index++)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 14),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          width: 30,
                          height: 30,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: sage,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Text(
                            '${index + 1}',
                            style: const TextStyle(
                              color: olive,
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            instructions[index].toString(),
                            style: const TextStyle(height: 1.4),
                          ),
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ShoppingListScreen(
                        api: widget.api,
                        plan: widget.plan,
                        selectedDay: widget.selectedDay,
                      ),
                    ),
                  ),
                  icon: const Icon(Icons.shopping_bag_outlined),
                  label: const Text('Где купить ингредиенты'),
                ),
              ],
            ),
    );
  }
}

class _RecipeMetric extends StatelessWidget {
  const _RecipeMetric(this.value, this.label);
  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text(value, style: Theme.of(context).textTheme.labelLarge),
      const SizedBox(height: 2),
      Text(label, style: Theme.of(context).textTheme.bodySmall),
    ],
  );
}

class _MetricDivider extends StatelessWidget {
  const _MetricDivider();

  @override
  Widget build(BuildContext context) =>
      Container(width: 1, height: 28, color: line);
}

class ShoppingListScreen extends StatefulWidget {
  const ShoppingListScreen({
    required this.api,
    required this.plan,
    required this.selectedDay,
    super.key,
  });
  final ApiClient api;
  final Map<String, dynamic> plan;
  final DateTime selectedDay;

  @override
  State<ShoppingListScreen> createState() => _ShoppingListScreenState();
}

class _ShoppingListScreenState extends State<ShoppingListScreen> {
  bool week = true;
  bool loading = true;
  Map<String, dynamic>? list;
  Map<String, dynamic>? offers;
  final checked = <String>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  String _iso(DateTime value) =>
      '${value.year}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';
  Future<void> _load() async {
    setState(() => loading = true);
    final query = week ? null : {'day': _iso(widget.selectedDay)};
    try {
      list = await widget.api.get(
        '/v1/meal-plans/${widget.plan['id']}/shopping-list',
        query: query,
      );
      try {
        offers = await widget.api.get(
          '/v1/meal-plans/${widget.plan['id']}/shopping-list/offers',
          query: query,
        );
      } on ApiException {
        // The shopping list remains usable while an external retail provider is
        // unavailable. This is expected before a partner API is connected.
        offers = null;
      }
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

  @override
  Widget build(BuildContext context) {
    final entries = List<dynamic>.from(list?['entries'] as List? ?? const []);
    final retailerTotals = <String, double>{};
    final retailerItems = <String, int>{};
    final retailerLiveAvailability = <String, int>{};
    for (final raw in List<dynamic>.from(
      offers?['offers'] as List? ?? const [],
    )) {
      final item = Map<String, dynamic>.from(raw as Map);
      final retailer = item['retailer']?.toString();
      final price = (item['price'] as num?)?.toDouble();
      if (retailer == null || price == null) continue;
      retailerTotals.update(
        retailer,
        (value) => value + price,
        ifAbsent: () => price,
      );
      retailerItems.update(retailer, (value) => value + 1, ifAbsent: () => 1);
      if (item['price_type'] == 'retailer' && item['available'] == true) {
        retailerLiveAvailability.update(
          retailer,
          (value) => value + 1,
          ifAbsent: () => 1,
        );
      }
    }
    final retailers = retailerTotals.entries.toList()
      ..sort((a, b) => a.value.compareTo(b.value));
    final hasLiveAvailability =
        retailerLiveAvailability.values.fold<int>(
          0,
          (sum, value) => sum + value,
        ) >
        0;
    final total = (list?['total_estimated_cost'] as num?)?.toDouble() ?? 0;
    final budget = (widget.plan['budget_total'] as num?)?.toDouble();
    return Scaffold(
      appBar: AppBar(title: const Text('Где купить')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 30),
        children: [
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('День')),
              ButtonSegment(value: true, label: Text('Неделя')),
            ],
            selected: {week},
            onSelectionChanged: (value) {
              setState(() => week = value.first);
              _load();
            },
          ),
          const SizedBox(height: 16),
          Container(
            decoration: BoxDecoration(
              color: forest,
              borderRadius: BorderRadius.circular(20),
            ),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'СТОИМОСТЬ',
                        style: Theme.of(context).textTheme.labelMedium
                            ?.copyWith(
                              color: Colors.white.withValues(alpha: .6),
                              letterSpacing: 1,
                            ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        '≈ ${total.round()} ₽',
                        style: Theme.of(context).textTheme.headlineMedium
                            ?.copyWith(color: const Color(0xFFE7D4AB)),
                      ),
                    ],
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        'БЮДЖЕТ',
                        style: Theme.of(context).textTheme.labelMedium
                            ?.copyWith(
                              color: Colors.white.withValues(alpha: .6),
                              letterSpacing: 1,
                            ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        budget == null
                            ? 'Не ограничен'
                            : '${week ? budget.round() : (budget / 7).round()} ₽',
                        style: Theme.of(
                          context,
                        ).textTheme.titleLarge?.copyWith(color: Colors.white),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: Text(
              hasLiveAvailability
                  ? 'Товары с отметкой «в наличии» проверены по витрине сети. Остальные цены — ориентир для планирования.'
                  : 'Это ориентир для планирования. Наличие и финальную цену подтвердите в приложении магазина.',
              style: TextStyle(color: ink.withValues(alpha: .58)),
            ),
          ),
          Text(
            'Где собрать корзину',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 4),
          Text(
            retailers.isEmpty
                ? 'Подключаем магазины — пока показываем среднюю цену по Москве.'
                : 'Сравнили примерную стоимость вашей корзины в сетях.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 10),
          if (retailers.isEmpty)
            Card(
              child: ListTile(
                leading: const AccentIconTile(Icons.storefront_outlined),
                title: const Text('Средняя цена по Москве'),
                subtitle: const Text('Ориентир по каталогу продуктов'),
                trailing: Text('≈ ${total.round()} ₽'),
              ),
            )
          else
            for (var index = 0; index < retailers.length; index++)
              _retailerCard(
                retailer: retailers[index].key,
                total: retailers[index].value,
                items: retailerItems[retailers[index].key] ?? 0,
                liveAvailable:
                    retailerLiveAvailability[retailers[index].key] ?? 0,
                best: index == 0,
              ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: Text(
                  'Продукты из рациона',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ),
              TextButton(
                onPressed: entries.isEmpty
                    ? null
                    : () => setState(() {
                        checked.clear();
                        checked.addAll(
                          entries.map((raw) => (raw as Map)['slug'].toString()),
                        );
                      }),
                child: const Text('Отметить всё'),
              ),
            ],
          ),
          if (loading)
            const Center(
              child: Padding(
                padding: EdgeInsets.all(30),
                child: CircularProgressIndicator(color: olive),
              ),
            )
          else
            Card(
              child: Column(
                children: [
                  for (final raw in entries)
                    CheckboxListTile(
                      value: checked.contains((raw as Map)['slug']),
                      activeColor: olive,
                      onChanged: (value) => setState(
                        () => value == true
                            ? checked.add(raw['slug'].toString())
                            : checked.remove(raw['slug'].toString()),
                      ),
                      title: Text(raw['name'].toString()),
                      subtitle: Text('${raw['grams']} г'),
                      secondary: Text(
                        raw['estimated_cost'] == null
                            ? '—'
                            : '≈ ${(raw['estimated_cost'] as num).round()} ₽',
                      ),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _retailerCard({
    required String retailer,
    required double total,
    required int items,
    required int liveAvailable,
    required bool best,
  }) => Container(
    margin: const EdgeInsets.only(bottom: 9),
    decoration: BoxDecoration(
      color: best ? sageLight : warmWhite,
      borderRadius: BorderRadius.circular(18),
      border: Border.all(color: best ? olive.withValues(alpha: .42) : line),
    ),
    child: ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 15, vertical: 5),
      leading: AccentIconTile(
        best ? Icons.verified_outlined : Icons.storefront_outlined,
        size: 44,
      ),
      title: Row(
        children: [
          Flexible(child: Text(retailer)),
          if (best) ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
              decoration: BoxDecoration(
                color: olive,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                'выгоднее',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ],
        ],
      ),
      subtitle: Text(
        liveAvailable > 0
            ? 'В наличии: $liveAvailable из $items · остальное — оценка'
            : '$items продуктов · ориентировочная цена',
      ),
      trailing: Text(
        '≈ ${total.round()} ₽',
        style: const TextStyle(color: olive, fontWeight: FontWeight.w700),
      ),
    ),
  );
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message, required this.retry});
  final String message;
  final VoidCallback retry;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
          Text(message),
          const SizedBox(height: 12),
          TextButton(onPressed: retry, child: const Text('Повторить')),
        ],
      ),
    ),
  );
}
