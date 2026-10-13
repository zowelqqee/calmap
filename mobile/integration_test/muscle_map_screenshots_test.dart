import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/workout_screen.dart';

import 'screenshots_test.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  final api = DemoApiClient();

  Future<void> capture(WidgetTester tester, String name) async {
    await tester.pumpAndSettle();
    await binding.takeScreenshot(name);
  }

  testWidgets('muscle map screens', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        debugShowCheckedModeBanner: false,
        home: WorkoutScreen(api: api),
      ),
    );
    await capture(tester, 'workout_muscle_map');
    await tester.tap(find.byTooltip('Настроить тренировки'));
    await capture(tester, 'workout_preferences');
  });
}
