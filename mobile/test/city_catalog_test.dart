import 'package:flutter_test/flutter_test.dart';

import 'package:calmap_mobile/core/city_catalog.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('loads the offline catalogue of Russian cities', () async {
    final cities = await CityCatalog.load();

    expect(cities, hasLength(1102));
    expect(cities.any((city) => city.name == 'Москва'), isTrue);
    expect(cities.any((city) => city.name == 'Санкт-Петербург'), isTrue);
    expect(
      cities.where((city) => city.matches('елабуга')),
      isNotEmpty,
    );
  });
}
