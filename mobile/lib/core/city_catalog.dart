import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class RussianCity {
  const RussianCity({
    required this.name,
    required this.region,
    required this.alternateName,
  });

  final String name;
  final String region;
  final String alternateName;

  String get subtitle =>
      region.isEmpty || region == name ? 'Город федерального значения' : region;

  bool matches(String query) {
    final normalized = _normalize(query);
    return _normalize(name).contains(normalized) ||
        _normalize(alternateName).contains(normalized) ||
        _normalize(region).contains(normalized);
  }

  static String _normalize(String value) =>
      value.toLowerCase().replaceAll('ё', 'е').trim();
}

class CityCatalog {
  CityCatalog._();

  static List<RussianCity>? _cached;

  static Future<List<RussianCity>> load() async {
    final cached = _cached;
    if (cached != null) return cached;

    final raw = await rootBundle.loadString('assets/data/russia_cities.json');
    final decoded = jsonDecode(raw) as List<dynamic>;
    final cities = [
      for (final value in decoded)
        if (value is Map)
          RussianCity(
            name: value['name']?.toString() ?? '',
            alternateName: value['alt']?.toString() ?? '',
            region: value['region']?.toString() ?? '',
          ),
    ]..removeWhere((city) => city.name.isEmpty);
    return _cached = cities;
  }
}

Future<RussianCity?> showCityPicker(
  BuildContext context, {
  String? selectedCity,
}) => showModalBottomSheet<RussianCity>(
  context: context,
  isScrollControlled: true,
  backgroundColor: Colors.transparent,
  builder: (_) => _CityPickerSheet(selectedCity: selectedCity),
);

class _CityPickerSheet extends StatefulWidget {
  const _CityPickerSheet({this.selectedCity});

  final String? selectedCity;

  @override
  State<_CityPickerSheet> createState() => _CityPickerSheetState();
}

class _CityPickerSheetState extends State<_CityPickerSheet> {
  final _search = TextEditingController();
  late final Future<List<RussianCity>> _cities = CityCatalog.load();
  String _query = '';

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final height = MediaQuery.sizeOf(context).height * .82;
    return SafeArea(
      top: false,
      child: Container(
        height: height,
        padding: const EdgeInsets.fromLTRB(20, 14, 20, 18),
        decoration: const BoxDecoration(
          color: Color(0xFFFCFBF7),
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
        child: Column(
          children: [
            Container(
              width: 42,
              height: 4,
              decoration: BoxDecoration(
                color: const Color(0xFFE3DED4),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
            const SizedBox(height: 18),
            const Align(
              alignment: Alignment.centerLeft,
              child: Text('Выберите город', style: TextStyle(fontSize: 25)),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _search,
              autofocus: true,
              onChanged: (value) => setState(() => _query = value),
              decoration: const InputDecoration(
                hintText: 'Начните вводить название',
                prefixIcon: Icon(Icons.search_rounded),
              ),
            ),
            const SizedBox(height: 10),
            Expanded(
              child: FutureBuilder<List<RussianCity>>(
                future: _cities,
                builder: (context, snapshot) {
                  if (!snapshot.hasData) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  final cities = _query.isEmpty
                      ? snapshot.data!
                      : snapshot.data!
                            .where((city) => city.matches(_query))
                            .toList();
                  if (cities.isEmpty) {
                    return const Center(child: Text('Город не найден'));
                  }
                  return ListView.separated(
                    itemCount: cities.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final city = cities[index];
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(city.name),
                        subtitle: Text(city.subtitle),
                        trailing: city.name == widget.selectedCity
                            ? const Icon(
                                Icons.check_rounded,
                                color: Color(0xFF244B3C),
                              )
                            : null,
                        onTap: () => Navigator.pop(context, city),
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
