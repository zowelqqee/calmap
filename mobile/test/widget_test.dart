import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/intro_screen.dart';

void main() {
  testWidgets('intro walks through all three product promises', (tester) async {
    var completed = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTheme(),
        home: IntroScreen(onCompleted: () async => completed = true),
      ),
    );

    expect(find.text('Твой персональный план'), findsOneWidget);
    await tester.tap(find.text('Далее'));
    await tester.pumpAndSettle();
    expect(find.text('Реальные продукты из магазина'), findsOneWidget);
    await tester.tap(find.text('Далее'));
    await tester.pumpAndSettle();
    expect(find.text('Тренировки под твой уровень'), findsOneWidget);
    await tester.tap(find.text('Начать'));
    await tester.pump();
    expect(completed, isTrue);
  });
}
