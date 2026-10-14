import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/workout_screen.dart';
import 'package:calmap_mobile/widgets/muscle_map.dart';

import '../integration_test/screenshots_test.dart';

// Golden images are rendered with macOS system fonts, so these comparisons run
// only where those fonts exist (the developer's Mac); elsewhere they are skipped.
const _arialPath = '/System/Library/Fonts/Supplemental/Arial.ttf';
const _iconsPath =
    '/opt/homebrew/share/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf';
final bool _goldenFontsAvailable =
    File(_arialPath).existsSync() && File(_iconsPath).existsSync();

void main() {
  final api = DemoApiClient();

  ThemeData previewTheme() {
    final base = buildTheme();
    return base.copyWith(
      textTheme: base.textTheme.apply(fontFamily: 'PreviewArial'),
      appBarTheme: base.appBarTheme.copyWith(
        titleTextStyle: base.appBarTheme.titleTextStyle?.copyWith(
          fontFamily: 'PreviewArial',
        ),
      ),
      chipTheme: base.chipTheme.copyWith(
        labelStyle:
            base.chipTheme.labelStyle?.copyWith(fontFamily: 'PreviewArial') ??
            const TextStyle(fontFamily: 'PreviewArial'),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: base.filledButtonTheme.style?.copyWith(
          textStyle: const WidgetStatePropertyAll(
            TextStyle(fontFamily: 'PreviewArial'),
          ),
        ),
      ),
    );
  }

  setUpAll(() async {
    if (!_goldenFontsAvailable) return;
    final previewFont = FontLoader('PreviewArial')
      ..addFont(File(_arialPath).readAsBytes().then(ByteData.sublistView));
    final materialIcons = FontLoader('MaterialIcons')
      ..addFont(File(_iconsPath).readAsBytes().then(ByteData.sublistView));
    await Future.wait([previewFont.load(), materialIcons.load()]);
  });

  Future<void> pumpScreen(WidgetTester tester, Widget screen) async {
    await tester.binding.setSurfaceSize(const Size(430, 932));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: previewTheme(),
        debugShowCheckedModeBanner: false,
        home: screen,
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('renders the workout muscle map', (tester) async {
    await pumpScreen(tester, WorkoutScreen(api: api));
    await expectLater(
      find.byType(WorkoutScreen),
      matchesGoldenFile('goldens/workout_muscle_map.png'),
    );
  }, skip: !_goldenFontsAvailable);

  testWidgets('renders workout preferences', (tester) async {
    await pumpScreen(tester, WorkoutPreferencesScreen(api: api));
    await expectLater(
      find.byType(WorkoutPreferencesScreen),
      matchesGoldenFile('goldens/workout_preferences.png'),
    );
  }, skip: !_goldenFontsAvailable);

  testWidgets('renders the male anatomy map', (tester) async {
    await pumpScreen(
      tester,
      const Scaffold(
        body: WorkoutMuscleSummary(
          bodySex: 'male',
          loads: {
            'грудь': 2,
            'передняя дельта': 1,
            'трицепс': 1,
            'квадрицепсы': 2,
            'ягодицы': 4,
            'кор': 3,
          },
        ),
      ),
    );
    await expectLater(
      find.byType(WorkoutMuscleSummary),
      matchesGoldenFile('goldens/male_muscle_map.png'),
    );
  }, skip: !_goldenFontsAvailable);

  testWidgets('renders the female anatomy map', (tester) async {
    await pumpScreen(
      tester,
      const Scaffold(
        body: WorkoutMuscleSummary(
          bodySex: 'female',
          loads: {
            'грудь': 2,
            'задняя дельта': 2,
            'ягодицы': 4,
            'задняя поверхность бедра': 3,
            'кор': 3,
          },
        ),
      ),
    );
    await tester.tap(find.text('ягодицы · 4'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(WorkoutMuscleSummary),
      matchesGoldenFile('goldens/female_muscle_map.png'),
    );
  }, skip: !_goldenFontsAvailable);
}
