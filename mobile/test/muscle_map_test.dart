import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/widgets/anatomy.dart';
import 'package:calmap_mobile/widgets/muscle_map.dart';

/// Every anatomical muscle the exercise catalogue can name.  `кардио`,
/// `мобильность` and `всё тело` are deliberately absent — they are modalities,
/// not places on the body.
const _catalogueMuscles = <String>{
  'бицепс',
  'верх спины',
  'вращательная манжета',
  'грудь',
  'задняя дельта',
  'задняя поверхность бедра',
  'икры',
  'камбаловидная',
  'квадрицепсы',
  'кор',
  'косые мышцы живота',
  'передняя дельта',
  'передняя зубчатая',
  'предплечья',
  'приводящие мышцы бедра',
  'прямая мышца живота',
  'разгибатели спины',
  'сгибатели бедра',
  'средняя дельта',
  'средняя ягодичная',
  'трапеции',
  'трицепс',
  'шея',
  'широчайшие',
  'ягодицы',
};

/// First point of [path] found by scanning its bounding box.
Offset _insidePoint(Path path) {
  final bounds = path.getBounds();
  for (var row = 1; row < 20; row++) {
    for (var column = 1; column < 20; column++) {
      final point = Offset(
        bounds.left + bounds.width * column / 20,
        bounds.top + bounds.height * row / 20,
      );
      if (path.contains(point)) return point;
    }
  }
  fail('no point found inside $bounds');
}

void main() {
  test('every muscle the catalogue can name is on the map', () {
    expect(anatomyMuscles, containsAll(_catalogueMuscles));
    expect(anatomyMuscles.difference(_catalogueMuscles), isEmpty);
  });

  test('muscles are announced on the views that actually show them', () {
    expect(anatomyViewsOf('ягодицы'), {AnatomyView.back});
    expect(anatomyViewsOf('грудь'), {AnatomyView.front});
    expect(anatomyViewsOf('предплечья'), {
      AnatomyView.front,
      AnatomyView.back,
    });
  });

  test('regions hit test back to their muscle', () {
    final layout = AnatomyLayout.resolve(
      size: const Size(200, 500),
      female: false,
      view: AnatomyView.front,
    );
    final chest = layout.regions.firstWhere(
      (region) => region.slug == 'chest',
    );
    final hit = layout.regionAt(_insidePoint(chest.path));
    expect(hit?.muscles, contains('грудь'));
  });

  test('a region shared by two muscles reports the heavier one', () {
    final layout = AnatomyLayout.resolve(
      size: const Size(200, 500),
      female: false,
      view: AnatomyView.front,
    );
    final abs = layout.regions.firstWhere(
      (region) => region.slug == 'abs',
    );
    expect(abs.muscles, containsAll(['прямая мышца живота', 'кор']));
    expect(abs.loadFrom({'прямая мышца живота': 1, 'кор': 4}), 4);
    expect(abs.labelFrom({'прямая мышца живота': 1, 'кор': 4}), 'кор');
  });

  testWidgets('tapping a chip explains that muscle', (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: const Scaffold(
          body: SingleChildScrollView(
            child: WorkoutMuscleSummary(
              bodySex: 'female',
              loads: {'ягодицы': 4, 'кор': 2},
            ),
          ),
        ),
      ),
    );
    expect(find.textContaining('Коснитесь мышцы'), findsOneWidget);

    await tester.tap(find.text('ягодицы · 4'));
    await tester.pumpAndSettle();
    expect(find.text('ягодицы'), findsOneWidget);
    expect(find.text('4 из 4 · сзади'), findsOneWidget);

    // Tapping the same chip again clears the selection.
    await tester.tap(find.text('ягодицы · 4'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Коснитесь мышцы'), findsOneWidget);
  });

  testWidgets('a day without muscle data still renders', (tester) async {
    await tester.binding.setSurfaceSize(const Size(430, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: const Scaffold(
          body: SingleChildScrollView(
            child: WorkoutMuscleSummary(bodySex: 'male', loads: {}),
          ),
        ),
      ),
    );
    expect(find.textContaining('не размечена'), findsOneWidget);
  });
}
