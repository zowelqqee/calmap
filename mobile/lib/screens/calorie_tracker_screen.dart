import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/theme.dart';

class CalorieTrackerScreen extends StatefulWidget {
  const CalorieTrackerScreen({required this.api, super.key});

  final ApiClient api;

  @override
  State<CalorieTrackerScreen> createState() => _CalorieTrackerScreenState();
}

class _CalorieTrackerScreenState extends State<CalorieTrackerScreen> {
  DateTime day = DateTime.now();
  Map<String, dynamic>? summary;
  bool loading = true;
  bool saving = false;

  String get isoDay => _formatDay(day);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (mounted) setState(() => loading = true);
    try {
      summary = await widget.api.get('/v1/diary/$isoDay');
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _addEntry() async {
    final method = await showModalBottomSheet<String>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Как добавить?',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 16),
              _addMethodTile(
                context: context,
                icon: Icons.menu_book_outlined,
                title: 'Из базового списка',
                subtitle: 'Продукты и блюда с примерным весом и КБЖУ',
                onTap: () => Navigator.pop(sheetContext, 'catalog'),
              ),
              const SizedBox(height: 10),
              _addMethodTile(
                context: context,
                icon: Icons.edit_outlined,
                title: 'Вручную',
                subtitle: 'Указать название и калории самостоятельно',
                onTap: () => Navigator.pop(sheetContext, 'manual'),
              ),
            ],
          ),
        ),
      ),
    );
    if (!mounted) return;
    if (method == 'catalog') {
      await _addFromCatalog();
    } else if (method == 'manual') {
      await _addManualEntry();
    }
  }

  Widget _addMethodTile({
    required BuildContext context,
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) => Card(
    margin: EdgeInsets.zero,
    child: ListTile(
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 15, vertical: 5),
      leading: AccentIconTile(icon, size: 44),
      title: Text(title, style: Theme.of(context).textTheme.titleMedium),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 3),
        child: Text(subtitle),
      ),
      trailing: const Icon(Icons.chevron_right, color: mutedInk),
    ),
  );

  Future<void> _addFromCatalog() async {
    try {
      final results = await Future.wait([
        widget.api.getList('/v1/catalog/products', query: {'limit': '100'}),
        widget.api.getList('/v1/catalog/recipes', query: {'limit': '100'}),
      ]);
      final products = _maps(results[0]);
      final recipes = _maps(results[1]);
      if (!mounted) return;
      final search = TextEditingController();
      final selected = await showModalBottomSheet<_CatalogSelection>(
        context: context,
        isScrollControlled: true,
        builder: (sheetContext) {
          var tab = 0;
          // Products are searched on the server (the catalogue is larger than the
          // first page); dishes are few enough to filter locally.
          List<Map<String, dynamic>>? searched;
          Timer? debounce;
          var requestSeq = 0;
          return StatefulBuilder(
            builder: (context, setSheetState) {
              void onQueryChanged(String value) {
                setSheetState(() {});
                debounce?.cancel();
                final text = value.trim();
                if (text.length < 2) {
                  searched = null;
                  return;
                }
                debounce = Timer(const Duration(milliseconds: 300), () async {
                  final seq = ++requestSeq;
                  try {
                    final found = _maps(
                      await widget.api.getList(
                        '/v1/catalog/products',
                        query: {'q': text, 'limit': '50'},
                      ),
                    );
                    if (seq == requestSeq && context.mounted) {
                      setSheetState(() => searched = found);
                    }
                  } on ApiException {
                    // Keep the local results while offline.
                  }
                });
              }

              final source = tab == 0 ? products : recipes;
              final query = search.text.trim().toLowerCase();
              final filtered = tab == 0 && searched != null && query.length >= 2
                  ? searched!
                  : query.isEmpty
                  ? source
                  : source
                        .where(
                          (item) => item['name']
                              .toString()
                              .toLowerCase()
                              .contains(query),
                        )
                        .toList();
              return SafeArea(
                child: SizedBox(
                  height: MediaQuery.sizeOf(context).height * .82,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Добавить из списка',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: 5),
                        const Text(
                          'Выберите продукт или готовое блюдо — вес можно изменить дальше.',
                          style: TextStyle(color: mutedInk),
                        ),
                        const SizedBox(height: 16),
                        SegmentedButton<int>(
                          segments: const [
                            ButtonSegment(value: 0, label: Text('Продукты')),
                            ButtonSegment(value: 1, label: Text('Блюда')),
                          ],
                          selected: {tab},
                          onSelectionChanged: (value) =>
                              setSheetState(() => tab = value.first),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: search,
                          onChanged: onQueryChanged,
                          decoration: const InputDecoration(
                            hintText: 'Поиск продукта или блюда',
                            prefixIcon: Icon(Icons.search),
                          ),
                        ),
                        const SizedBox(height: 10),
                        Expanded(
                          child: filtered.isEmpty
                              ? const Center(child: Text('Ничего не найдено'))
                              : ListView.separated(
                                  itemCount: filtered.length,
                                  separatorBuilder: (_, _) =>
                                      const Divider(height: 1),
                                  itemBuilder: (_, index) {
                                    final item = filtered[index];
                                    final isProduct = tab == 0;
                                    return ListTile(
                                      contentPadding:
                                          const EdgeInsets.symmetric(
                                            vertical: 4,
                                          ),
                                      leading: AccentIconTile(
                                        isProduct
                                            ? Icons.apple_outlined
                                            : Icons.restaurant_outlined,
                                        size: 42,
                                      ),
                                      title: Text(item['name'].toString()),
                                      subtitle: Text(
                                        isProduct
                                            ? '${_compactNumber(item['kcal_per_100g'])} ккал / 100 г · ${_categoryLabel(item['category'])}'
                                            : '${_compactNumber(item['kcal_per_100g'])} ккал / 100 г · порция ${_compactNumber(item['base_grams'])} г',
                                      ),
                                      trailing: const Icon(
                                        Icons.add_circle_outline,
                                        color: olive,
                                      ),
                                      onTap: () => Navigator.pop(
                                        sheetContext,
                                        _CatalogSelection(
                                          kind: isProduct
                                              ? 'product'
                                              : 'recipe',
                                          item: item,
                                        ),
                                      ),
                                    );
                                  },
                                ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          );
        },
      );
      search.dispose();
      if (selected != null && mounted) await _enterCatalogEntry(selected);
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
  }

  Future<void> _enterCatalogEntry(_CatalogSelection selection) async {
    final item = selection.item;
    final suggested = selection.kind == 'recipe'
        ? _number(item['base_grams']).round().clamp(1, 5000)
        : _suggestedWeight(item['category']);
    final grams = TextEditingController(text: suggested.toString());
    var mealType = _suggestedMealType(item);
    final accepted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          final amount = _parse(grams.text);
          final factor = amount / 100;
          return AlertDialog(
            title: Text(item['name'].toString()),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'На 100 г: ${_compactNumber(item['kcal_per_100g'])} ккал · Б ${_compactNumber(item['protein_per_100g'])} г · Ж ${_compactNumber(item['fat_per_100g'])} г · У ${_compactNumber(item['carbs_per_100g'])} г',
                    style: const TextStyle(color: mutedInk),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: grams,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    onChanged: (_) => setDialogState(() {}),
                    decoration: const InputDecoration(
                      labelText: 'Количество',
                      suffixText: 'г',
                      prefixIcon: Icon(Icons.scale_outlined),
                    ),
                  ),
                  const SizedBox(height: 12),
                  _nutritionPreview(item, factor),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: mealType,
                    decoration: const InputDecoration(
                      labelText: 'Приём пищи',
                      prefixIcon: Icon(Icons.schedule_outlined),
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: 'breakfast',
                        child: Text('Завтрак'),
                      ),
                      DropdownMenuItem(value: 'lunch', child: Text('Обед')),
                      DropdownMenuItem(value: 'dinner', child: Text('Ужин')),
                      DropdownMenuItem(value: 'snack', child: Text('Перекус')),
                    ],
                    onChanged: (value) =>
                        setDialogState(() => mealType = value ?? 'snack'),
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
                onPressed: amount > 0 && amount <= 5000
                    ? () => Navigator.pop(dialogContext, true)
                    : null,
                child: const Text('Добавить'),
              ),
            ],
          );
        },
      ),
    );
    if (accepted == true) {
      final amount = _parse(grams.text);
      if (mounted) setState(() => saving = true);
      try {
        await widget.api.post('/v1/diary/entries', {
          'day': isoDay,
          'meal_type': mealType,
          'grams': amount,
          if (selection.kind == 'product') 'product_id': item['id'],
          if (selection.kind == 'recipe') 'recipe_id': item['id'],
          'source': 'search',
        });
        await _load();
      } on ApiException catch (exception) {
        if (mounted) _snack(exception.message);
      } finally {
        if (mounted) setState(() => saving = false);
      }
    }
    grams.dispose();
  }

  Future<void> _addManualEntry() async {
    final name = TextEditingController();
    final kcal = TextEditingController();
    final protein = TextEditingController();
    final fat = TextEditingController();
    final carbs = TextEditingController();
    var mealType = 'snack';
    final formKey = GlobalKey<FormState>();

    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, setSheetState) => Padding(
          padding: EdgeInsets.fromLTRB(
            20,
            8,
            20,
            MediaQuery.viewInsetsOf(context).bottom + 24,
          ),
          child: SingleChildScrollView(
            child: Form(
              key: formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Добавить калории',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Запишите блюдо или продукт вручную',
                    style: Theme.of(
                      context,
                    ).textTheme.bodyMedium?.copyWith(color: mutedInk),
                  ),
                  const SizedBox(height: 20),
                  TextFormField(
                    controller: name,
                    autofocus: true,
                    textCapitalization: TextCapitalization.sentences,
                    decoration: const InputDecoration(
                      labelText: 'Что съели?',
                      hintText: 'Например, домашний обед',
                      prefixIcon: Icon(Icons.restaurant_outlined),
                    ),
                    validator: (value) => value == null || value.trim().isEmpty
                        ? 'Введите название'
                        : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: kcal,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(
                      labelText: 'Калории',
                      hintText: 'Например, 450',
                      suffixText: 'ккал',
                      prefixIcon: Icon(Icons.local_fire_department_outlined),
                    ),
                    validator: (value) {
                      final amount = double.tryParse(
                        (value ?? '').replaceAll(',', '.'),
                      );
                      return amount == null || amount <= 0
                          ? 'Укажите калории больше нуля'
                          : null;
                    },
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: mealType,
                    decoration: const InputDecoration(
                      labelText: 'Приём пищи',
                      prefixIcon: Icon(Icons.schedule_outlined),
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: 'breakfast',
                        child: Text('Завтрак'),
                      ),
                      DropdownMenuItem(value: 'lunch', child: Text('Обед')),
                      DropdownMenuItem(value: 'dinner', child: Text('Ужин')),
                      DropdownMenuItem(value: 'snack', child: Text('Перекус')),
                    ],
                    onChanged: (value) =>
                        setSheetState(() => mealType = value ?? 'snack'),
                  ),
                  const SizedBox(height: 18),
                  Text(
                    'БЖУ — необязательно',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(child: _macroField(protein, 'Белки', 'г')),
                      const SizedBox(width: 8),
                      Expanded(child: _macroField(fat, 'Жиры', 'г')),
                      const SizedBox(width: 8),
                      Expanded(child: _macroField(carbs, 'Углеводы', 'г')),
                    ],
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: () {
                      if (formKey.currentState?.validate() ?? false) {
                        Navigator.pop(sheetContext, true);
                      }
                    },
                    icon: const Icon(Icons.add),
                    label: const Text('Добавить запись'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );

    if (result == true) {
      double parse(String value) =>
          double.tryParse(value.replaceAll(',', '.')) ?? 0;
      if (mounted) setState(() => saving = true);
      try {
        await widget.api.post('/v1/diary/entries', {
          'day': isoDay,
          'meal_type': mealType,
          'name': name.text.trim(),
          'kcal': parse(kcal.text),
          'protein_g': parse(protein.text),
          'fat_g': parse(fat.text),
          'carbs_g': parse(carbs.text),
          'source': 'manual',
        });
        await _load();
      } on ApiException catch (exception) {
        if (mounted) _snack(exception.message);
      } finally {
        if (mounted) setState(() => saving = false);
      }
    }
    name.dispose();
    kcal.dispose();
    protein.dispose();
    fat.dispose();
    carbs.dispose();
  }

  Widget _macroField(
    TextEditingController controller,
    String label,
    String suffix,
  ) => TextFormField(
    controller: controller,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    decoration: InputDecoration(labelText: label, suffixText: suffix),
  );

  Future<void> _deleteEntry(String id) async {
    try {
      await widget.api.delete('/v1/diary/entries/$id');
      await _load();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
      await _load();
    }
  }

  Future<void> _confirmDeleteEntry(String id, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Удалить запись?'),
        content: Text(name),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed == true) await _deleteEntry(id);
  }

  String _formatDay(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  String _humanDay() {
    final today = DateTime.now();
    final isToday =
        day.year == today.year &&
        day.month == today.month &&
        day.day == today.day;
    if (isToday) return 'Сегодня';
    return '${day.day} ${_months[day.month - 1]}';
  }

  void _changeDay(int offset) {
    setState(() => day = day.add(Duration(days: offset)));
    _load();
  }

  void _snack(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  @override
  Widget build(BuildContext context) {
    final entries = List<Map<String, dynamic>>.from(
      (summary?['entries'] as List? ?? const []).map(
        (entry) => Map<String, dynamic>.from(entry as Map),
      ),
    );
    final calories = _number(summary?['kcal']).round();
    final target = _number(summary?['target_kcal']).round();
    final remaining = target > 0 ? target - calories : 0;
    final progress = target <= 0
        ? 0.0
        : (calories / target).clamp(0.0, 1.0).toDouble();

    return SafeArea(
      child: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 22, 20, 120),
          children: [
            const ScreenHeading(
              title: 'Калории',
              subtitle: 'Ручной трекер питания',
            ),
            const SizedBox(height: 18),
            _datePicker(),
            const SizedBox(height: 14),
            _summaryCard(calories, target, remaining, progress),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: loading || saving ? null : _addEntry,
              icon: const Icon(Icons.add),
              label: const Text('Добавить калории'),
            ),
            const SizedBox(height: 24),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'Записи за день',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                if (entries.isNotEmpty)
                  Text(
                    '${entries.length}',
                    style: Theme.of(
                      context,
                    ).textTheme.bodyMedium?.copyWith(color: mutedInk),
                  ),
              ],
            ),
            const SizedBox(height: 10),
            if (loading)
              const Padding(
                padding: EdgeInsets.all(32),
                child: Center(child: CircularProgressIndicator(color: olive)),
              )
            else if (entries.isEmpty)
              _emptyState()
            else
              for (final entry in entries) _entryCard(entry),
          ],
        ),
      ),
    );
  }

  Widget _datePicker() => Row(
    children: [
      IconButton(
        onPressed: loading ? null : () => _changeDay(-1),
        icon: const Icon(Icons.chevron_left),
      ),
      Expanded(
        child: Column(
          children: [
            Text(_humanDay(), style: Theme.of(context).textTheme.titleMedium),
            Text(isoDay, style: Theme.of(context).textTheme.bodySmall),
          ],
        ),
      ),
      IconButton(
        onPressed: loading ? null : () => _changeDay(1),
        icon: const Icon(Icons.chevron_right),
      ),
    ],
  );

  Widget _summaryCard(
    int calories,
    int target,
    int remaining,
    double progress,
  ) => Container(
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: forest,
      borderRadius: BorderRadius.circular(22),
      boxShadow: const [
        BoxShadow(
          color: Color(0x21173D31),
          blurRadius: 22,
          offset: Offset(0, 10),
        ),
      ],
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              '$calories',
              style: Theme.of(
                context,
              ).textTheme.displayMedium?.copyWith(color: Colors.white),
            ),
            const Padding(
              padding: EdgeInsets.only(bottom: 8, left: 6),
              child: Text(
                'ккал съедено',
                style: TextStyle(color: Color(0xB3FFFFFF), fontSize: 14),
              ),
            ),
          ],
        ),
        const SizedBox(height: 3),
        Text(
          target > 0 ? 'из $target ккал в день' : 'цель пока не задана',
          style: const TextStyle(color: Color(0xB3FFFFFF), fontSize: 14),
        ),
        const SizedBox(height: 18),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            value: progress,
            color: champagne,
            backgroundColor: Colors.white.withValues(alpha: .14),
            minHeight: 7,
          ),
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            Icon(
              remaining >= 0 ? Icons.check_circle_outline : Icons.info_outline,
              color: champagne,
              size: 18,
            ),
            const SizedBox(width: 8),
            Text(
              target <= 0
                  ? 'Добавляйте записи, чтобы видеть динамику'
                  : remaining >= 0
                  ? 'Осталось $remaining ккал'
                  : 'Превышение на ${remaining.abs()} ккал',
              style: const TextStyle(color: Color(0xE6FFFFFF)),
            ),
          ],
        ),
      ],
    ),
  );

  Widget _emptyState() => Card(
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 28),
      child: Column(
        children: [
          const AccentIconTile(Icons.local_fire_department_outlined, size: 58),
          const SizedBox(height: 14),
          Text('Пока пусто', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 5),
          const Text(
            'Добавьте первый приём пищи — это займёт несколько секунд.',
            textAlign: TextAlign.center,
            style: TextStyle(color: mutedInk),
          ),
        ],
      ),
    ),
  );

  Widget _entryCard(Map<String, dynamic> entry) {
    final kcal = _number(entry['kcal']).round();
    final protein = _number(entry['protein_g']);
    final fat = _number(entry['fat_g']);
    final carbs = _number(entry['carbs_g']);
    final macros = protein == 0 && fat == 0 && carbs == 0
        ? _mealLabel(entry['meal_type'])
        : '${_mealLabel(entry['meal_type'])} · Б ${_compact(protein)}  Ж ${_compact(fat)}  У ${_compact(carbs)}';
    return Dismissible(
      key: ValueKey(entry['id']),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 24),
        margin: const EdgeInsets.only(bottom: 10),
        decoration: BoxDecoration(
          color: Colors.redAccent,
          borderRadius: BorderRadius.circular(20),
        ),
        child: const Icon(Icons.delete_outline, color: Colors.white),
      ),
      onDismissed: (_) => _deleteEntry(entry['id'].toString()),
      child: Card(
        margin: const EdgeInsets.only(bottom: 10),
        child: ListTile(
          contentPadding: const EdgeInsets.fromLTRB(15, 7, 15, 7),
          leading: const AccentIconTile(Icons.restaurant_outlined, size: 43),
          title: Text(entry['name'].toString()),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(macros),
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '$kcal\nккал',
                textAlign: TextAlign.right,
                style: Theme.of(context).textTheme.labelLarge,
              ),
              IconButton(
                tooltip: 'Удалить',
                onPressed: () => _confirmDeleteEntry(
                  entry['id'].toString(),
                  entry['name'].toString(),
                ),
                icon: const Icon(Icons.delete_outline, color: mutedInk),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _nutritionPreview(Map<String, dynamic> item, double factor) {
    final kcal = _number(item['kcal_per_100g']) * factor;
    final protein = _number(item['protein_per_100g']) * factor;
    final fat = _number(item['fat_per_100g']) * factor;
    final carbs = _number(item['carbs_per_100g']) * factor;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: sageLight,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Примерно на выбранный вес',
            style: TextStyle(color: mutedInk, fontSize: 12),
          ),
          const SizedBox(height: 5),
          Text(
            '${_compactNumber(kcal)} ккал',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 3),
          Text(
            'Б ${_compactNumber(protein)} г · Ж ${_compactNumber(fat)} г · У ${_compactNumber(carbs)} г',
            style: const TextStyle(color: mutedInk),
          ),
        ],
      ),
    );
  }

  List<Map<String, dynamic>> _maps(List<dynamic> values) => [
    for (final value in values) Map<String, dynamic>.from(value as Map),
  ];

  double _parse(String value) =>
      double.tryParse(value.replaceAll(',', '.')) ?? 0;

  int _suggestedWeight(String? category) => switch (category) {
    'meat' || 'fish' || 'plant_protein' => 150,
    'dairy' => 200,
    'grains' => 70,
    'bakery' => 50,
    'legumes' => 150,
    'vegetables' || 'fruit' => 150,
    'fats' => 10,
    'nuts' => 30,
    'eggs' => 100,
    'supplements' => 30,
    _ => 100,
  };

  String _suggestedMealType(Map<String, dynamic> item) {
    final types = List<String>.from(item['meal_types'] as List? ?? const []);
    if (types.contains('breakfast')) return 'breakfast';
    if (types.contains('lunch')) return 'lunch';
    if (types.contains('dinner')) return 'dinner';
    return 'snack';
  }

  String _categoryLabel(dynamic value) => switch (value?.toString()) {
    'meat' => 'мясо',
    'fish' => 'рыба',
    'dairy' => 'молочные',
    'grains' => 'крупы',
    'bakery' => 'выпечка',
    'legumes' => 'бобовые',
    'vegetables' => 'овощи',
    'fruit' => 'фрукты',
    'fats' => 'жиры',
    'nuts' => 'орехи',
    'eggs' => 'яйца',
    _ => 'продукт',
  };

  String _compactNumber(dynamic value) {
    final number = _number(value);
    return number == number.roundToDouble()
        ? number.round().toString()
        : number.toStringAsFixed(1);
  }

  double _number(dynamic value) => (value as num?)?.toDouble() ?? 0;

  String _compact(double value) => value == value.roundToDouble()
      ? value.round().toString()
      : value.toStringAsFixed(1);

  String _mealLabel(dynamic value) => switch (value?.toString()) {
    'breakfast' => 'Завтрак',
    'lunch' => 'Обед',
    'dinner' => 'Ужин',
    'snack' => 'Перекус',
    _ => 'Приём пищи',
  };

  static const _months = [
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
}

class _CatalogSelection {
  const _CatalogSelection({required this.kind, required this.item});

  final String kind;
  final Map<String, dynamic> item;
}
