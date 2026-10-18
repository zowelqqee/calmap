import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../core/api_client.dart';
import '../core/legal.dart';
import '../core/theme.dart';

class DiaryScreen extends StatefulWidget {
  const DiaryScreen({required this.api, super.key});

  final ApiClient api;

  @override
  State<DiaryScreen> createState() => _DiaryScreenState();
}

class _DiaryScreenState extends State<DiaryScreen> {
  final picker = ImagePicker();
  DateTime day = DateTime.now();
  Map<String, dynamic>? summary;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  String get isoDay =>
      '${day.year.toString().padLeft(4, '0')}-${day.month.toString().padLeft(2, '0')}-${day.day.toString().padLeft(2, '0')}';

  Future<void> _load() async {
    setState(() => loading = true);
    try {
      summary = await widget.api.get('/v1/diary/$isoDay');
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _pick(ImageSource source) async {
    final XFile? file;
    try {
      file = await picker.pickImage(
        source: source,
        imageQuality: 82,
        maxWidth: 1600,
        // Strip EXIF (GPS, device) before the photo leaves the phone.
        requestFullMetadata: false,
      );
    } on PlatformException {
      _snack(
        source == ImageSource.camera
            ? 'Нет доступа к камере. Разрешите его в настройках телефона.'
            : 'Нет доступа к фото. Разрешите его в настройках телефона.',
      );
      return;
    }
    if (file == null) return;
    if (mounted) setState(() => loading = true);
    try {
      final bytes = await file.readAsBytes();
      final filename = file.name;
      if (!mounted) return;
      // The first photo asks for the consent to send it to the recognition service.
      final recognition = await withConsent(
        context,
        widget.api,
        () => widget.api.uploadImage(bytes: bytes, filename: filename),
      );
      await _confirmRecognition(recognition);
      await _load();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _confirmRecognition(Map<String, dynamic> recognition) async {
    final candidates = List<Map<String, dynamic>>.from(
      (recognition['candidates'] as List? ?? const []).map(
        (item) => Map<String, dynamic>.from(item as Map),
      ),
    );
    if (candidates.isEmpty) {
      _snack('На фото не удалось уверенно определить продукты');
      return;
    }
    final grams = [
      for (final item in candidates)
        TextEditingController(
          text: (item['grams_estimate'] as num).round().toString(),
        ),
    ];
    final included = [for (final _ in candidates) true];
    var mealType = 'dinner';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Проверьте распознавание'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: mealType,
                  decoration: const InputDecoration(labelText: 'Приём пищи'),
                  items: const [
                    DropdownMenuItem(
                      value: 'breakfast',
                      child: Text('Завтрак'),
                    ),
                    DropdownMenuItem(value: 'lunch', child: Text('Обед')),
                    DropdownMenuItem(value: 'dinner', child: Text('Ужин')),
                    DropdownMenuItem(value: 'snack', child: Text('Перекус')),
                  ],
                  onChanged: (value) => setDialogState(() => mealType = value!),
                ),
                const SizedBox(height: 12),
                for (var index = 0; index < candidates.length; index++) ...[
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: included[index],
                    activeColor: olive,
                    title: Text(candidates[index]['name'].toString()),
                    subtitle: Text(
                      'Уверенность ${(((candidates[index]['confidence'] as num?) ?? 0) * 100).round()}%'
                      '${List<dynamic>.from(candidates[index]['alternatives'] as List? ?? const []).isEmpty ? '' : ' · варианты: ${List<dynamic>.from(candidates[index]['alternatives'] as List).join(', ')}'}',
                    ),
                    onChanged: (value) =>
                        setDialogState(() => included[index] = value ?? false),
                  ),
                  TextField(
                    controller: grams[index],
                    enabled: included[index],
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Количество',
                      suffixText: 'г',
                    ),
                  ),
                  const SizedBox(height: 10),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: included.any((value) => value)
                  ? () => Navigator.pop(dialogContext, true)
                  : null,
              child: const Text('Записать'),
            ),
          ],
        ),
      ),
    );
    if (confirmed == true) {
      await widget.api.post(
        '/v1/vision/${recognition['recognition_id']}/confirm',
        {
          'day': isoDay,
          'meal_type': mealType,
          'items': [
            for (var index = 0; index < candidates.length; index++)
              if (included[index] && candidates[index]['product_id'] != null)
                {
                  'product_id': candidates[index]['product_id'],
                  'grams': double.tryParse(grams[index].text) ?? 100,
                },
          ],
        },
      );
    }
    for (final controller in grams) {
      controller.dispose();
    }
  }

  Future<void> _manualEntry() async {
    final query = TextEditingController();
    final search = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Найти продукт'),
        content: TextField(
          controller: query,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'Например, гречка'),
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(context, query.text.trim()),
            child: const Text('Найти'),
          ),
        ],
      ),
    );
    query.dispose();
    if (search == null || search.isEmpty) return;
    try {
      final products = await widget.api.getList(
        '/v1/catalog/products',
        query: {'q': search, 'limit': '20'},
      );
      if (!mounted) return;
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        builder: (_) => ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text('Выберите продукт', style: TextStyle(fontSize: 24)),
            for (final raw in products)
              ListTile(
                title: Text((raw as Map)['name'].toString()),
                subtitle: Text('${raw['kcal_per_100g']} ккал / 100 г'),
                onTap: () =>
                    Navigator.pop(context, Map<String, dynamic>.from(raw)),
              ),
          ],
        ),
      );
      if (selected == null || !mounted) return;
      await _enterManualGrams(selected);
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
  }

  Future<void> _enterManualGrams(Map<String, dynamic> product) async {
    final grams = TextEditingController(text: '100');
    var mealType = 'snack';
    final accepted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (_, setDialogState) => AlertDialog(
          title: Text(product['name'].toString()),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: grams,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Количество',
                  suffixText: 'г',
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: mealType,
                decoration: const InputDecoration(labelText: 'Приём пищи'),
                items: const [
                  DropdownMenuItem(value: 'breakfast', child: Text('Завтрак')),
                  DropdownMenuItem(value: 'lunch', child: Text('Обед')),
                  DropdownMenuItem(value: 'dinner', child: Text('Ужин')),
                  DropdownMenuItem(value: 'snack', child: Text('Перекус')),
                ],
                onChanged: (value) => setDialogState(() => mealType = value!),
              ),
            ],
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Добавить'),
            ),
          ],
        ),
      ),
    );
    if (accepted == true) {
      await widget.api.post('/v1/diary/entries', {
        'day': isoDay,
        'meal_type': mealType,
        'grams': double.tryParse(grams.text) ?? 100,
        'product_id': product['id'],
        'source': 'search',
      });
      await _load();
    }
    grams.dispose();
  }

  Future<void> _deleteEntry(String entryId) async {
    try {
      await widget.api.delete('/v1/diary/entries/$entryId');
      await _load();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
      await _load();
    }
  }

  Future<void> _repeatYesterday() async {
    var mealType = 'breakfast';
    final accepted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (_, setDialogState) => AlertDialog(
          title: const Text('Повторить вчерашнее'),
          content: DropdownButtonFormField<String>(
            initialValue: mealType,
            decoration: const InputDecoration(labelText: 'Приём пищи'),
            items: const [
              DropdownMenuItem(value: 'breakfast', child: Text('Завтрак')),
              DropdownMenuItem(value: 'lunch', child: Text('Обед')),
              DropdownMenuItem(value: 'dinner', child: Text('Ужин')),
              DropdownMenuItem(value: 'snack', child: Text('Перекус')),
            ],
            onChanged: (value) => setDialogState(() => mealType = value!),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Повторить'),
            ),
          ],
        ),
      ),
    );
    if (accepted != true) return;
    try {
      final source = day.subtract(const Duration(days: 1));
      await widget.api.postList('/v1/diary/repeat', {
        'source_day': _formatDay(source),
        'target_day': isoDay,
        'meal_type': mealType,
      });
      await _load();
    } on ApiException catch (exception) {
      if (mounted) _snack(exception.message);
    }
  }

  String _formatDay(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  void _snack(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  @override
  Widget build(BuildContext context) {
    final entries = List<dynamic>.from(
      summary?['entries'] as List? ?? const [],
    );
    final calories = (summary?['kcal'] as num?)?.round() ?? 0;
    final target = (summary?['target_kcal'] as num?)?.round() ?? 0;
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
              title: 'Дневник',
              subtitle: 'Фактическое питание за день',
            ),
            const SizedBox(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                IconButton(
                  onPressed: () {
                    setState(() => day = day.subtract(const Duration(days: 1)));
                    _load();
                  },
                  icon: const Icon(Icons.chevron_left),
                ),
                Text(isoDay, style: const TextStyle(fontSize: 18)),
                IconButton(
                  onPressed: () {
                    setState(() => day = day.add(const Duration(days: 1)));
                    _load();
                  },
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Container(
              decoration: BoxDecoration(
                color: forest,
                borderRadius: BorderRadius.circular(22),
              ),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$calories / $target ккал',
                      style: Theme.of(
                        context,
                      ).textTheme.headlineMedium?.copyWith(color: Colors.white),
                    ),
                    const SizedBox(height: 12),
                    LinearProgressIndicator(
                      value: progress,
                      color: champagne,
                      backgroundColor: Colors.white.withValues(alpha: .14),
                      minHeight: 6,
                    ),
                    const SizedBox(height: 14),
                    Text(
                      'Б ${summary?['protein_g'] ?? 0} г  ·  Ж ${summary?['fat_g'] ?? 0} г  ·  У ${summary?['carbs_g'] ?? 0} г',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: .7),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: loading ? null : () => _pick(ImageSource.camera),
                    icon: const Icon(Icons.camera_alt_outlined),
                    label: const Text('Сфотографировать'),
                  ),
                ),
                const SizedBox(width: 10),
                IconButton.filledTonal(
                  onPressed: loading ? null : () => _pick(ImageSource.gallery),
                  icon: const Icon(Icons.photo_library_outlined),
                ),
              ],
            ),
            TextButton.icon(
              onPressed: loading ? null : _manualEntry,
              icon: const Icon(Icons.search),
              label: const Text('Добавить продукт вручную'),
            ),
            TextButton.icon(
              onPressed: loading ? null : _repeatYesterday,
              icon: const Icon(Icons.history),
              label: const Text('Повторить приём пищи со вчера'),
            ),
            const SizedBox(height: 12),
            if (loading)
              const Center(child: CircularProgressIndicator(color: olive))
            else if (entries.isEmpty)
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text('Пока ничего не записано'),
                ),
              )
            else
              for (final raw in entries)
                Dismissible(
                  key: ValueKey((raw as Map)['id']),
                  direction: DismissDirection.endToStart,
                  background: Container(
                    alignment: Alignment.centerRight,
                    padding: const EdgeInsets.only(right: 24),
                    decoration: BoxDecoration(
                      color: Colors.redAccent,
                      borderRadius: BorderRadius.circular(24),
                    ),
                    child: const Icon(
                      Icons.delete_outline,
                      color: Colors.white,
                    ),
                  ),
                  onDismissed: (_) => _deleteEntry(raw['id'].toString()),
                  child: Card(
                    child: ListTile(
                      title: Text(raw['name'].toString()),
                      subtitle: Text(
                        '${raw['grams']} г · ${_sourceLabel(raw['source'])}',
                      ),
                      trailing: Text('${(raw['kcal'] as num).round()} ккал'),
                    ),
                  ),
                ),
          ],
        ),
      ),
    );
  }

  String _sourceLabel(dynamic source) => switch (source?.toString()) {
    'vision' => 'по фото',
    'plan' => 'из плана',
    'search' => 'добавлено вручную',
    _ => 'запись',
  };
}
