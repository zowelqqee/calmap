import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:calmap_mobile/core/api_client.dart';
import 'package:calmap_mobile/core/subscription.dart';
import 'package:calmap_mobile/core/theme.dart';
import 'package:calmap_mobile/screens/assistant_screen.dart';
import 'package:calmap_mobile/screens/auth_screen.dart';
import 'package:calmap_mobile/screens/diary_screen.dart';
import 'package:calmap_mobile/screens/home_screen.dart';
import 'package:calmap_mobile/screens/intro_screen.dart';
import 'package:calmap_mobile/screens/onboarding_screen.dart';
import 'package:calmap_mobile/screens/paywall_screen.dart';
import 'package:calmap_mobile/screens/profile_screen.dart';

void main() {
  final binding = IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  final api = DemoApiClient();

  Future<void> show(WidgetTester tester, Widget child) async {
    await tester.pumpWidget(
      MaterialApp(
        key: UniqueKey(),
        title: 'Calmap',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: Scaffold(body: child),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> capture(WidgetTester tester, String name) async {
    await tester.pumpAndSettle();
    await binding.takeScreenshot(name);
  }

  testWidgets('partner screenshot gallery', (tester) async {
    await show(tester, const _DemoSplash());
    await capture(tester, '01_splash');

    await show(
      tester,
      IntroScreen(onCompleted: ({required bool register}) async {}),
    );
    await capture(tester, '02_intro_personal_plan');
    await tester.drag(find.byType(PageView), const Offset(-360, 0));
    await capture(tester, '03_intro_products');
    await tester.drag(find.byType(PageView), const Offset(-360, 0));
    await capture(tester, '04_intro_workouts');

    await show(tester, AuthScreen(api: api, onAuthenticated: () async {}));
    await capture(tester, '05_auth_login');
    await tester.tap(find.text('Зарегистрироваться'));
    await capture(tester, '06_auth_registration');

    await show(tester, OnboardingScreen(api: api, onCompleted: () {}));
    await capture(tester, '07_onboarding_personal');
    for (final name in [
      '08_onboarding_goal',
      '09_onboarding_restrictions',
      '10_onboarding_budget',
      '11_onboarding_activity',
    ]) {
      await tester.tap(find.text('Продолжить'));
      await capture(tester, name);
    }

    await show(tester, HomeScreen(api: api, onLogout: () async {}));
    await capture(tester, '12_dashboard');

    await tester.tap(find.byType(NavigationDestination).at(1));
    await capture(tester, '13_nutrition_today');
    await tester.tap(find.byTooltip('Календарь'));
    await capture(tester, '13a_nutrition_calendar');
    await tester.tap(find.text('Открыть рацион'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Овсянка с бананом и творогом'));
    await capture(tester, '14_recipe_detail');
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Где купить'));
    await tester.pumpAndSettle();
    await capture(tester, '15_shopping_list');
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();

    await tester.tap(find.byType(NavigationDestination).at(2));
    await capture(tester, '16_workouts_today');
    await capture(tester, '16a_workout_muscle_map');
    await tester.tap(find.byTooltip('Настроить тренировки'));
    await capture(tester, '16b_workout_preferences');
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    // Scroll rather than drag a fixed distance: how far the button sits below
    // the fold depends on how tall the muscle map card is for this body.
    await tester.scrollUntilVisible(
      find.text('Начать тренировку'),
      320,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Начать тренировку'));
    await capture(tester, '17_workout_execution');
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();

    await tester.tap(find.byType(NavigationDestination).at(3));
    await capture(tester, '18_progress');
    await tester.ensureVisible(find.text('Добавить результат'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Добавить результат'));
    await capture(tester, '19_add_progress');
    await tester.tap(find.text('Отмена'));

    await show(tester, DiaryScreen(api: api));
    await capture(tester, '20_food_diary');
    unawaited(
      showDialog<void>(
        context: tester.element(find.byType(DiaryScreen)),
        builder: (_) => const _DemoVisionConfirmation(),
      ),
    );
    await capture(tester, '21_vision_confirmation');

    await show(tester, AssistantScreen(api: api));
    await capture(tester, '22_ai_intro');
    await tester.enterText(
      find.byType(TextField),
      'Как добрать белок и не выйти за бюджет?',
    );
    await tester.tap(find.byIcon(Icons.arrow_upward));
    await capture(tester, '23_ai_chat');

    await show(tester, ProfileScreen(api: api, onLogout: () async {}));
    await capture(tester, '24_profile');

    await show(
      tester,
      PaywallScreen(
        api: api,
        status: SubscriptionStatus.fromJson(const {
          'state': 'expired',
          'has_access': false,
          'tier': 'base',
          'payment_available': true,
        }),
        onRecheck: () async => false,
        onLogout: () async {},
      ),
    );
    await capture(tester, '25_paywall');
  });
}

class DemoApiClient extends ApiClient {
  DemoApiClient() : super(baseUrl: 'http://demo.invalid');

  @override
  Future<dynamic> getAny(String path, {Map<String, String>? query}) async {
    if (path == '/v1/workouts/today') return _workout;
    return get(path, query: query);
  }

  @override
  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, String>? query,
  }) async {
    if (path == '/v1/onboarding/session') {
      return {
        'current_step': 1,
        'completed_steps': <int>[],
        'payload': <String, dynamic>{},
      };
    }
    if (path == '/v1/auth/me') {
      return {
        'id': 'demo-user',
        'email': 'alexey@calmap.ru',
        'name': 'Алексей',
        'avatar_url': null,
        'region_code': 'RU-MOW',
        'onboarding_completed': true,
        'tier': 'pro',
      };
    }
    if (path == '/v1/me/targets') {
      return {
        'target_kcal': 2450,
        'protein_g': 184,
        'fat_g': 68,
        'carbs_g': 276,
      };
    }
    if (path == '/v1/me/subscription') {
      return {
        'state': 'active',
        'has_access': true,
        'tier': 'pro',
        'access_until': DateTime.now()
            .add(const Duration(days: 20))
            .toUtc()
            .toIso8601String(),
        'telegram_linked': true,
        'payment_available': true,
      };
    }
    if (path == '/v1/progress/overview') return _progress;
    if (path == '/v1/exercises/meta') {
      return {
        'total': 226,
        'muscle_groups': [
          'грудь',
          'квадрицепсы',
          'ягодицы',
          'кор',
          'широчайшие',
        ],
        'equipment': ['вес тела', 'гантели', 'резинка', 'турник'],
      };
    }
    if (path == '/v1/workouts/preferences') {
      return {
        'equipment': ['гантели', 'резинка'],
        'focus_muscles': ['грудь', 'ягодицы'],
      };
    }
    if (path == '/v1/progress/report') {
      return {
        'weight_change_kg': -2.5,
        'waist_change_cm': -3,
        'summary': _progress,
        'notice': 'Отчёт носит информационный характер.',
      };
    }
    if (path.startsWith('/v1/catalog/recipes/')) return _recipe;
    if (path.endsWith('/shopping-list/offers')) return _offers;
    if (path.endsWith('/shopping-list')) return _shopping;
    if (path.startsWith('/v1/meal-plans/')) return _plan;
    if (path.startsWith('/v1/diary/')) return _diary;
    return <String, dynamic>{};
  }

  @override
  Future<List<dynamic>> getList(
    String path, {
    Map<String, String>? query,
  }) async {
    if (path == '/v1/meal-plans/calendar') {
      return [
        {
          'day': '2026-08-03',
          'plan_id': 'demo-plan',
          'kcal': 2438,
          'cost': 496,
          'has_weight_record': true,
        },
        {
          'day': '2026-08-04',
          'plan_id': 'demo-plan',
          'kcal': 2461,
          'cost': 501,
          'has_weight_record': false,
        },
      ];
    }
    return <dynamic>[];
  }

  @override
  Future<Map<String, dynamic>> patch(
    String path,
    Map<String, dynamic> body,
  ) async {
    if (path == '/v1/auth/me') return {...(await get('/v1/auth/me')), ...body};
    if (path.contains('/workouts/')) return _workout;
    return <String, dynamic>{};
  }

  @override
  Future<Map<String, dynamic>> post(
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    if (path == '/v1/assistant/chat') {
      return {
        'conversation_id': 'demo-conversation',
        'message': {
          'content':
              'Добавьте 200 г творога и порцию чечевицы. Это около 45 г белка и примерно 170 ₽.',
        },
      };
    }
    if (path == '/v1/onboarding/complete') return {'plan_id': 'demo-plan'};
    if (path == '/v1/me/subscription/telegram-link') {
      return {'url': 'https://t.me/calmap_bot?start=demo'};
    }
    if (path.contains('/workouts/')) return _workout;
    if (path.endsWith('/favorite')) return {'is_favorite': true};
    return <String, dynamic>{};
  }

  @override
  Future<Map<String, dynamic>> delete(String path) async =>
      path.endsWith('/favorite') ? {'is_favorite': false} : {'deleted': true};

  static final _plan = <String, dynamic>{
    'id': 'demo-plan',
    'target_kcal': 2450,
    'cost_total': 3478.0,
    'budget_total': 3500.0,
    'currency': 'RUB',
    'days': [
      {
        'day': '2026-08-03',
        'kcal': 2438.0,
        'protein_g': 183,
        'fat_g': 68,
        'carbs_g': 274,
        'cost': 496.0,
        'items': [
          {
            'id': 'meal-1',
            'meal_type': 'breakfast',
            'recipe_slug': 'oats_banana_cottage',
            'recipe_name': 'Овсянка с бананом и творогом',
            'grams': 360,
            'kcal': 580.0,
            'cost': 92.0,
          },
          {
            'id': 'meal-2',
            'meal_type': 'snack',
            'recipe_slug': 'skyr_berries',
            'recipe_name': 'Скир с ягодами',
            'grams': 260,
            'kcal': 330.0,
            'cost': 84.0,
          },
          {
            'id': 'meal-3',
            'meal_type': 'lunch',
            'recipe_slug': 'chicken_buckwheat',
            'recipe_name': 'Гречка с курицей и овощами',
            'grams': 520,
            'kcal': 760.0,
            'cost': 145.0,
          },
          {
            'id': 'meal-4',
            'meal_type': 'dinner',
            'recipe_slug': 'salmon_potato',
            'recipe_name': 'Горбуша с картофелем',
            'grams': 430,
            'kcal': 710.0,
            'cost': 175.0,
          },
        ],
      },
      {
        'day': '2026-08-04',
        'kcal': 2461.0,
        'protein_g': 184,
        'fat_g': 69,
        'carbs_g': 277,
        'cost': 501.0,
        'items': <dynamic>[],
      },
    ],
  };

  static final _recipe = <String, dynamic>{
    'slug': 'oats_banana_cottage',
    'name': 'Овсянка с бананом и творогом',
    'is_favorite': false,
    'prep_minutes': 12,
    'difficulty': 'easy',
    'price_notice': 'Цены примерные и могут отличаться от фактических.',
    'ingredients': [
      {
        'name': 'Овсяные хлопья',
        'grams': 70,
        'estimated_cost': 12,
        'store': 'Средняя цена по Москве',
      },
      {
        'name': 'Банан',
        'grams': 120,
        'estimated_cost': 18,
        'store': 'Средняя цена по Москве',
      },
      {
        'name': 'Творог 5%',
        'grams': 170,
        'estimated_cost': 62,
        'store': 'Средняя цена по Москве',
      },
    ],
    'instructions': [
      'Подготовьте и взвесьте ингредиенты.',
      'Сварите овсяные хлопья до готовности.',
      'Добавьте творог и нарезанный банан.',
    ],
  };

  static final _shopping = <String, dynamic>{
    'total_estimated_cost': 3478.0,
    'price_notice': 'Цены примерные и могут отличаться от фактических.',
    'entries': [
      {
        'slug': 'chicken_breast',
        'name': 'Куриная грудка, филе',
        'grams': 1260,
        'estimated_cost': 490.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'buckwheat',
        'name': 'Гречневая крупа',
        'grams': 630,
        'estimated_cost': 75.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'cottage_cheese_5',
        'name': 'Творог 5%',
        'grams': 900,
        'estimated_cost': 740.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'pink_salmon',
        'name': 'Горбуша',
        'grams': 1100,
        'estimated_cost': 700.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'vegetables',
        'name': 'Овощи и зелень',
        'grams': 3500,
        'estimated_cost': 500.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'eggs',
        'name': 'Яйца',
        'grams': 700,
        'estimated_cost': 180.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'dairy',
        'name': 'Кисломолочные продукты',
        'grams': 1600,
        'estimated_cost': 400.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'oats',
        'name': 'Овсяные хлопья',
        'grams': 600,
        'estimated_cost': 120.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'rice',
        'name': 'Рис',
        'grams': 700,
        'estimated_cost': 133.0,
        'store': 'Средняя цена по Москве',
      },
      {
        'slug': 'oil',
        'name': 'Растительное масло',
        'grams': 400,
        'estimated_cost': 140.0,
        'store': 'Средняя цена по Москве',
      },
    ],
  };

  static final _offers = <String, dynamic>{
    'offers': [
      for (final retailer in {
        'Пятёрочка': .94,
        'Лента': .98,
        'Перекрёсток': 1.04,
      }.entries)
        for (final raw in List<dynamic>.from(_shopping['entries'] as List))
          {
            'slug': raw['slug'],
            'name': raw['name'],
            'retailer': retailer.key,
            'available': null,
            'price': (raw['estimated_cost'] as num).toDouble() * retailer.value,
            'currency': 'RUB',
            'price_type': 'estimate',
          },
    ],
  };

  static final _workout = <String, dynamic>{
    'id': 'workout-1',
    'day': '2026-08-03',
    'title': 'Силовая — всё тело',
    'duration_minutes': 40,
    'estimated_kcal': 260,
    'body_sex': 'male',
    'status': 'planned',
    'completed_count': 1,
    'total_count': 4,
    'exercises': [
      {
        'id': 'exercise-1',
        'catalog_id': 'bodyweight-squat',
        'name': 'Приседания',
        'primary_muscle': 'квадрицепсы',
        'secondary_muscles': ['ягодицы', 'кор'],
        'equipment': 'вес тела',
        'sets': 3,
        'reps': 12,
        'duration_seconds': null,
        'position': 1,
        'is_completed': true,
        'is_skipped': false,
      },
      {
        'id': 'exercise-2',
        'catalog_id': 'push-up',
        'name': 'Отжимания',
        'primary_muscle': 'грудь',
        'secondary_muscles': ['трицепс', 'передняя дельта'],
        'equipment': 'вес тела',
        'sets': 3,
        'reps': 10,
        'duration_seconds': null,
        'position': 2,
        'is_completed': false,
        'is_skipped': false,
      },
      {
        'id': 'exercise-3',
        'catalog_id': 'glute-bridge',
        'name': 'Ягодичный мост',
        'primary_muscle': 'ягодицы',
        'secondary_muscles': ['задняя поверхность бедра'],
        'equipment': 'вес тела',
        'sets': 3,
        'reps': 15,
        'duration_seconds': null,
        'position': 3,
        'is_completed': false,
        'is_skipped': false,
      },
      {
        'id': 'exercise-4',
        'catalog_id': 'plank',
        'name': 'Планка',
        'primary_muscle': 'кор',
        'secondary_muscles': ['прямая мышца живота', 'ягодицы'],
        'equipment': 'вес тела',
        'sets': 3,
        'reps': null,
        'duration_seconds': 40,
        'position': 4,
        'is_completed': false,
        'is_skipped': false,
      },
    ],
  };

  static final _progress = <String, dynamic>{
    'goal': 'lose',
    'start_date': '2026-07-01',
    'end_date': '2026-09-23',
    'start_weight_kg': 84.0,
    'current_weight_kg': 81.5,
    'target_weight_kg': 76.0,
    'progress_pct': 31.3,
    'workouts_completed': 12,
    'average_kcal': 2380,
    'entries': [
      {
        'id': 'p1',
        'day': '2026-07-01',
        'weight_kg': 84.0,
        'waist_cm': 92.0,
        'note': 'Старт',
      },
      {
        'id': 'p2',
        'day': '2026-07-15',
        'weight_kg': 82.8,
        'waist_cm': 90.5,
        'note': null,
      },
      {
        'id': 'p3',
        'day': '2026-08-03',
        'weight_kg': 81.5,
        'waist_cm': 89.0,
        'note': 'Хорошее самочувствие',
      },
    ],
  };

  static final _diary = <String, dynamic>{
    'kcal': 1640.0,
    'protein_g': 128.0,
    'fat_g': 52.0,
    'carbs_g': 166.0,
    'target_kcal': 2450,
    'entries': [
      {
        'id': 'entry-1',
        'name': 'Овсянка с бананом',
        'grams': 320,
        'source': 'vision',
        'kcal': 510.0,
      },
      {
        'id': 'entry-2',
        'name': 'Гречка с куриной грудкой',
        'grams': 480,
        'source': 'plan',
        'kcal': 720.0,
      },
      {
        'id': 'entry-3',
        'name': 'Творог 5%',
        'grams': 200,
        'source': 'search',
        'kcal': 242.0,
      },
    ],
  };
}

class _DemoSplash extends StatelessWidget {
  const _DemoSplash();
  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 78,
            height: 78,
            decoration: BoxDecoration(
              color: forest,
              borderRadius: BorderRadius.circular(25),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x2B173D31),
                  blurRadius: 28,
                  offset: Offset(0, 12),
                ),
              ],
            ),
            child: const Icon(
              Icons.spa_outlined,
              color: Color(0xFFE7D4AB),
              size: 37,
            ),
          ),
          const SizedBox(height: 20),
          Text('calmap', style: Theme.of(context).textTheme.displayMedium),
          const SizedBox(height: 4),
          const Text(
            'ПИТАНИЕ · ДВИЖЕНИЕ · БАЛАНС',
            style: TextStyle(
              color: mutedInk,
              fontSize: 9,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.7,
            ),
          ),
        ],
      ),
    ),
  );
}

class _DemoVisionConfirmation extends StatelessWidget {
  const _DemoVisionConfirmation();
  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Проверьте распознавание'),
    content: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          DropdownButtonFormField<String>(
            initialValue: 'lunch',
            decoration: InputDecoration(labelText: 'Приём пищи'),
            items: [DropdownMenuItem(value: 'lunch', child: Text('Обед'))],
            onChanged: null,
          ),
          SizedBox(height: 12),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: true,
            onChanged: null,
            activeColor: olive,
            title: Text('Куриная грудка'),
            subtitle: Text('Уверенность 94%'),
          ),
          TextField(
            decoration: InputDecoration(
              labelText: 'Количество',
              hintText: '180 г',
            ),
          ),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            value: true,
            onChanged: null,
            activeColor: olive,
            title: Text('Гречка отварная'),
            subtitle: Text('Уверенность 91%'),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(onPressed: null, child: Text('Отмена')),
      FilledButton(onPressed: null, child: Text('Записать')),
    ],
  );
}
