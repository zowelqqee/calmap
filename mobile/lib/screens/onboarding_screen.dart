import 'dart:async';

import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/city_catalog.dart';
import '../core/legal.dart';
import '../core/theme.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({
    required this.api,
    required this.onCompleted,
    super.key,
  });

  final ApiClient api;
  final VoidCallback onCompleted;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  int step = 0;
  bool saving = false;
  bool calculating = false;
  String? error;

  String city = 'Москва';
  bool hasChosenCity = false;
  String sex = 'male';
  final age = TextEditingController(text: '30');
  final height = TextEditingController(text: '175');
  final weight = TextEditingController(text: '75');
  String goal = 'maintain';
  final targetWeight = TextEditingController();
  final selectedAllergens = <String>{};
  String budgetType = 'fixed_week';
  final budget = TextEditingController(text: '3500');
  String activity = 'medium';
  String workoutLocation = 'home';
  String diet = 'omnivore';
  bool healthConsent = false;

  static const diets = <String, String>{
    'omnivore': 'Без ограничений',
    'no_pork': 'Без свинины',
    'pescatarian': 'Рыба без мяса',
    'vegetarian': 'Вегетарианское',
    'vegan': 'Веганское',
  };

  static const allergens = <String, String>{
    'gluten': 'Глютен',
    'lactose': 'Лактоза',
    'nuts': 'Орехи',
    'seafood': 'Морепродукты',
    'egg': 'Яйца',
    'soy': 'Соя',
    'peanut': 'Арахис',
    'sesame': 'Кунжут',
    'fish': 'Рыба',
    'molluscs': 'Моллюски',
  };

  @override
  void initState() {
    super.initState();
    _restoreCity();
  }

  Future<void> _restoreCity() async {
    final saved = await widget.api.readPreferredCity();
    if (saved != null && saved.isNotEmpty) {
      city = saved;
      hasChosenCity = true;
    }
    await _restoreDraft();
  }

  Future<void> _chooseCity() async {
    final selected = await showCityPicker(context, selectedCity: city);
    if (selected == null || selected.name == city) return;
    await widget.api.savePreferredCity(selected.name);
    if (mounted) setState(() => city = selected.name);
  }

  @override
  void dispose() {
    for (final controller in [age, height, weight, targetWeight, budget]) {
      controller.dispose();
    }
    super.dispose();
  }

  double _number(TextEditingController controller) =>
      double.tryParse(controller.text.replaceAll(',', '.')) ?? 0;

  Future<void> _restoreDraft() async {
    setState(() => saving = true);
    try {
      final session = await widget.api.get('/v1/onboarding/session');
      final payload = Map<String, dynamic>.from(
        session['payload'] as Map? ?? const {},
      );
      final personal = Map<String, dynamic>.from(
        payload['personal'] as Map? ?? const {},
      );
      final goalData = Map<String, dynamic>.from(
        payload['goal'] as Map? ?? const {},
      );
      final restrictions = Map<String, dynamic>.from(
        payload['restrictions'] as Map? ?? const {},
      );
      final budgetData = Map<String, dynamic>.from(
        payload['budget'] as Map? ?? const {},
      );
      final activityData = Map<String, dynamic>.from(
        payload['activity'] as Map? ?? const {},
      );
      final locationData = Map<String, dynamic>.from(
        payload['workout_location'] as Map? ?? const {},
      );
      if (personal.isNotEmpty) {
        healthConsent = true;
        sex = personal['sex']?.toString() ?? sex;
        if (personal['age'] != null) age.text = personal['age'].toString();
        if (personal['birth_date'] != null && personal['age'] == null) {
          final birth = DateTime.tryParse(personal['birth_date'].toString());
          if (birth != null) {
            age.text = (DateTime.now().year - birth.year).toString();
          }
        }
        height.text = personal['height_cm']?.toString() ?? height.text;
        weight.text = personal['weight_kg']?.toString() ?? weight.text;
      }
      if (goalData.isNotEmpty) {
        goal = goalData['goal']?.toString() ?? goal;
        targetWeight.text = goalData['target_weight_kg']?.toString() ?? '';
      }
      if (restrictions.isNotEmpty) {
        diet = restrictions['diet']?.toString() ?? diet;
        selectedAllergens
          ..clear()
          ..addAll(
            List<String>.from(restrictions['allergens'] as List? ?? const []),
          );
      }
      if (budgetData.isNotEmpty) {
        budgetType = budgetData['budget_type']?.toString() ?? budgetType;
        budget.text = budgetData['amount']?.toString() ?? budget.text;
      }
      if (activityData.isNotEmpty) {
        activity = activityData['activity_level']?.toString() ?? activity;
      }
      if (locationData.isNotEmpty) {
        workoutLocation =
            locationData['location']?.toString() ?? workoutLocation;
      }
      final serverStep = (session['current_step'] as num?)?.toInt() ?? 1;
      if (mounted) {
        setState(() {
          step = hasChosenCity ? serverStep.clamp(1, 6).toInt() : 0;
        });
      }
    } on ApiException catch (exception) {
      if (mounted) setState(() => error = exception.message);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  String? _validationError() {
    if (step == 1) {
      if (!healthConsent) {
        return 'Подтвердите согласие на обработку данных о здоровье';
      }
      final ageValue = _number(age);
      final heightValue = _number(height);
      final weightValue = _number(weight);
      if (ageValue < 10 || ageValue > 99) {
        return 'Укажите возраст от 10 до 99 лет';
      }
      if (heightValue < 100 || heightValue > 250) {
        return 'Укажите рост от 100 до 250 см';
      }
      if (weightValue < 30 || weightValue > 300) {
        return 'Укажите вес от 30 до 300 кг';
      }
    }
    if (step == 2 && targetWeight.text.trim().isNotEmpty) {
      final target = _number(targetWeight);
      if (target < 35 || target > 300) {
        return 'Целевой вес — от 35 до 300 кг';
      }
    }
    if (step == 4 && budgetType != 'unlimited' && _number(budget) <= 0) {
      return 'Бюджет должен быть больше нуля';
    }
    return null;
  }

  Future<void> _continue({bool skipRestrictions = false}) async {
    final validation = _validationError();
    if (validation != null) {
      setState(() => error = validation);
      return;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      switch (step) {
        case 0:
          await widget.api.savePreferredCity(city);
          hasChosenCity = true;
          break;
        case 1:
          await widget.api.patch('/v1/onboarding/personal', {
            'sex': sex,
            'age': _number(age).round(),
            'height_cm': _number(height),
            'weight_kg': _number(weight),
          });
          break;
        case 2:
          await widget.api.patch('/v1/onboarding/goal', {
            'goal': goal,
            'rate_pct': goal == 'maintain' ? 0 : 0.15,
            'target_weight_kg': targetWeight.text.trim().isEmpty
                ? null
                : _number(targetWeight),
          });
          break;
        case 3:
          if (skipRestrictions) {
            selectedAllergens.clear();
            diet = 'omnivore';
          }
          final values = <String>{...selectedAllergens};
          await widget.api.patch('/v1/onboarding/restrictions', {
            'diet': diet,
            'allergens': values.toList(),
            'excluded_product_ids': <String>[],
          });
          break;
        case 4:
          await widget.api.patch('/v1/onboarding/budget', {
            'budget_type': budgetType,
            'amount': budgetType == 'unlimited' ? null : _number(budget),
            'currency': 'RUB',
          });
          break;
        case 5:
          await widget.api.patch('/v1/onboarding/activity', {
            'activity_level': activity,
          });
          break;
        case 6:
          await widget.api.patch('/v1/onboarding/workout-location', {
            'location': workoutLocation,
          });
          break;
      }
      if (step < 6) {
        if (mounted) setState(() => step += 1);
      } else {
        if (mounted) setState(() => calculating = true);
        await Future.wait<dynamic>([
          widget.api.post('/v1/onboarding/complete'),
          // A short minimum keeps the result screen from flashing by.
          Future<void>.delayed(const Duration(milliseconds: 1500)),
        ]);
        widget.onCompleted();
      }
    } on ApiException catch (exception) {
      if (mounted) {
        setState(() {
          error = exception.message;
          calculating = false;
        });
      }
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (calculating) return const _CalculationScreen();
    const titles = [
      'Выберите город',
      'Расскажите о себе',
      'Выберите цель',
      'Есть ограничения?',
      'Бюджет на питание',
      'Уровень активности',
      'Где будете заниматься?',
    ];
    const subtitles = [
      'Цены в рационе сейчас рассчитываются по средним ценам Москвы.',
      'Эти данные нужны для точного расчёта калорий.',
      'Мы применим безопасный коэффициент к вашей норме.',
      'Исключим блюда с отмеченными продуктами.',
      'Рацион останется в пределах указанной суммы.',
      'Активность влияет на ежедневную норму энергии.',
      'Подберём упражнения и оборудование под ваше пространство.',
    ];
    return Scaffold(
      appBar: AppBar(
        leading: step > 0
            ? IconButton(
                onPressed: saving ? null : () => setState(() => step -= 1),
                icon: const Icon(Icons.arrow_back),
              )
            : null,
        title: const Text(
          'Ваш персональный план',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w600,
            letterSpacing: -.2,
          ),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 18),
            child: Center(child: Text('${step + 1}/7')),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            LinearProgressIndicator(
              value: (step + 1) / 7,
              minHeight: 3,
              color: champagne,
              backgroundColor: sage,
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(22, 28, 22, 20),
                children: [
                  Text(
                    titles[step],
                    style: Theme.of(context).textTheme.headlineLarge,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    subtitles[step],
                    style: Theme.of(
                      context,
                    ).textTheme.bodyLarge?.copyWith(color: mutedInk),
                  ),
                  const SizedBox(height: 24),
                  switch (step) {
                    0 => _city(),
                    1 => _personal(),
                    2 => _goal(),
                    3 => _restrictions(),
                    4 => _budget(),
                    5 => _activity(),
                    _ => _workoutLocation(),
                  },
                ],
              ),
            ),
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 22,
                  vertical: 6,
                ),
                child: Text(
                  error!,
                  style: const TextStyle(color: Colors.redAccent),
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(22, 8, 22, 18),
              child: Column(
                children: [
                  FilledButton(
                    onPressed: saving ? null : _continue,
                    child: saving
                        ? const SizedBox.square(
                            dimension: 22,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(step == 6 ? 'Рассчитать план' : 'Продолжить'),
                  ),
                  if (step == 3)
                    TextButton(
                      onPressed: saving
                          ? null
                          : () => _continue(skipRestrictions: true),
                      child: const Text('Пропустить'),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _city() => Card(
    child: ListTile(
      contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      leading: const AccentIconTile(Icons.location_on_outlined, size: 52),
      title: Text(city, style: const TextStyle(fontSize: 20)),
      subtitle: const Text('Можно изменить позже в профиле'),
      trailing: const Icon(Icons.chevron_right_rounded),
      onTap: _chooseCity,
    ),
  );

  Widget _personal() => Column(
    children: [
      Row(
        children: [
          Expanded(child: _sexCard('male', 'Мужской', Icons.male)),
          const SizedBox(width: 12),
          Expanded(child: _sexCard('female', 'Женский', Icons.female)),
        ],
      ),
      const SizedBox(height: 14),
      _numberField(age, 'Возраст', 'лет'),
      const SizedBox(height: 14),
      Row(
        children: [
          Expanded(child: _numberField(height, 'Рост', 'см')),
          const SizedBox(width: 12),
          Expanded(child: _numberField(weight, 'Вес', 'кг')),
        ],
      ),
      const SizedBox(height: 18),
      CheckboxListTile(
        value: healthConsent,
        onChanged: (value) => setState(() => healthConsent = value ?? false),
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        activeColor: olive,
        title: const Text(
          'Даю согласие на обработку данных о здоровье (пол, возраст, рост, '
          'вес, ограничения в питании) для расчёта рациона',
          style: TextStyle(fontSize: 14),
        ),
      ),
      LegalLinksText(
        api: widget.api,
        prefix: 'Подробнее —',
        textAlign: TextAlign.start,
      ),
    ],
  );

  Widget _goal() => Column(
    children: [
      _choiceCard(
        'lose',
        goal,
        'Похудеть',
        Icons.trending_down,
        () => setState(() => goal = 'lose'),
        subtitle: 'Дефицит 15%',
      ),
      _choiceCard(
        'gain',
        goal,
        'Набрать',
        Icons.trending_up,
        () => setState(() => goal = 'gain'),
        subtitle: 'Профицит 15%',
      ),
      _choiceCard(
        'maintain',
        goal,
        'Поддерживать',
        Icons.balance,
        () => setState(() => goal = 'maintain'),
        subtitle: 'Без изменения калорий',
      ),
      const SizedBox(height: 12),
      _numberField(targetWeight, 'Целевой вес (необязательно)', 'кг'),
    ],
  );

  Widget _restrictions() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: allergens.entries
            .map(
              (entry) => FilterChip(
                label: Text(entry.value),
                selected: selectedAllergens.contains(entry.key),
                selectedColor: olive.withValues(alpha: .18),
                checkmarkColor: olive,
                onSelected: (selected) => setState(
                  () => selected
                      ? selectedAllergens.add(entry.key)
                      : selectedAllergens.remove(entry.key),
                ),
              ),
            )
            .toList(),
      ),
      const SizedBox(height: 12),
      const Text(
        'Если вашего аллергена нет в списке, проверяйте состав блюд в рецепте.',
        style: TextStyle(color: mutedInk, fontSize: 13),
      ),
      const SizedBox(height: 22),
      Text('Тип питания', style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 10),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: diets.entries
            .map(
              (entry) => ChoiceChip(
                label: Text(entry.value),
                selected: diet == entry.key,
                selectedColor: olive.withValues(alpha: .18),
                onSelected: (_) => setState(() => diet = entry.key),
              ),
            )
            .toList(),
      ),
    ],
  );

  Widget _budget() => Column(
    children: [
      _choiceCard(
        'budget',
        budgetType == 'fixed_day' || budgetType == 'fixed_week' ? 'budget' : '',
        'Фиксированный бюджет',
        Icons.account_balance_wallet_outlined,
        () => setState(() => budgetType = 'fixed_week'),
        subtitle: 'На день или неделю',
      ),
      if (budgetType == 'fixed_day' || budgetType == 'fixed_week') ...[
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'fixed_day', label: Text('День')),
            ButtonSegment(value: 'fixed_week', label: Text('Неделя')),
          ],
          selected: {budgetType},
          onSelectionChanged: (value) =>
              setState(() => budgetType = value.first),
        ),
        const SizedBox(height: 12),
        _numberField(budget, 'Сумма', '₽'),
      ],
      _choiceCard(
        'unlimited',
        budgetType,
        'Не ограничен',
        Icons.all_inclusive,
        () => setState(() => budgetType = 'unlimited'),
        subtitle: 'Оптимизируем только КБЖУ',
      ),
      _choiceCard(
        'custom_week',
        budgetType,
        'Свой бюджет на неделю',
        Icons.edit_outlined,
        () => setState(() => budgetType = 'custom_week'),
        subtitle: 'Укажите удобную сумму',
      ),
      if (budgetType == 'custom_week')
        _numberField(budget, 'Сумма на неделю', '₽'),
    ],
  );

  Widget _activity() => Column(
    children: [
      _choiceCard(
        'low',
        activity,
        'Низкая',
        Icons.weekend_outlined,
        () => setState(() => activity = 'low'),
        subtitle: 'Мало движения · коэффициент 1.2',
      ),
      _choiceCard(
        'medium',
        activity,
        'Умеренная',
        Icons.directions_walk,
        () => setState(() => activity = 'medium'),
        subtitle: 'Регулярная активность · 1.55',
      ),
      _choiceCard(
        'high',
        activity,
        'Высокая',
        Icons.fitness_center,
        () => setState(() => activity = 'high'),
        subtitle: 'Интенсивные нагрузки · 1.9',
      ),
    ],
  );

  Widget _workoutLocation() => Column(
    children: [
      _choiceCard(
        'home',
        workoutLocation,
        'Дома',
        Icons.home_outlined,
        () => setState(() => workoutLocation = 'home'),
        subtitle: 'Без тренажёров и специального оборудования',
      ),
      _choiceCard(
        'gym',
        workoutLocation,
        'В зале',
        Icons.fitness_center_outlined,
        () => setState(() => workoutLocation = 'gym'),
        subtitle: 'Используем оборудование и тренажёры зала',
      ),
    ],
  );

  Widget _choiceCard(
    String value,
    String selected,
    String title,
    IconData icon,
    VoidCallback onTap, {
    String? subtitle,
  }) => Card(
    margin: const EdgeInsets.only(bottom: 10),
    color: value == selected ? sage : warmWhite,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(18),
      side: BorderSide(
        color: value == selected ? olive.withValues(alpha: .48) : line,
        width: value == selected ? 1.2 : .8,
      ),
    ),
    child: ListTile(
      onTap: onTap,
      leading: Icon(icon, color: olive),
      title: Text(title),
      subtitle: subtitle == null ? null : Text(subtitle),
      trailing: Icon(
        value == selected ? Icons.check_circle : Icons.circle_outlined,
        color: value == selected ? olive : Colors.black26,
      ),
    ),
  );

  Widget _sexCard(String value, String title, IconData icon) {
    final selected = sex == value;
    return Card(
      margin: EdgeInsets.zero,
      color: selected ? sage : warmWhite,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(
          color: selected ? olive.withValues(alpha: .48) : line,
          width: selected ? 1.2 : .8,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: () => setState(() => sex = value),
        child: SizedBox(
          height: 108,
          child: Stack(
            children: [
              Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(icon, color: olive, size: 30),
                    const SizedBox(height: 8),
                    Text(
                      title,
                      maxLines: 1,
                      style: const TextStyle(fontSize: 17),
                    ),
                  ],
                ),
              ),
              Positioned(
                right: 12,
                top: 12,
                child: Icon(
                  selected ? Icons.check_circle : Icons.circle_outlined,
                  color: selected ? olive : Colors.black26,
                  size: 22,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _numberField(
    TextEditingController controller,
    String label,
    String suffix,
  ) => TextField(
    controller: controller,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    decoration: InputDecoration(labelText: label, suffixText: suffix),
  );
}

class _CalculationScreen extends StatefulWidget {
  const _CalculationScreen();

  @override
  State<_CalculationScreen> createState() => _CalculationScreenState();
}

class _CalculationScreenState extends State<_CalculationScreen> {
  int message = 0;
  Timer? timer;
  Timer? slowTimer;
  bool slow = false;
  static const messages = [
    'Рассчитываем вашу норму калорий',
    'Подбираем блюда по бюджету',
    'Балансируем БЖУ',
    'Составляем список покупок',
  ];

  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(const Duration(milliseconds: 1600), (_) {
      if (mounted) {
        setState(
          () => message = message < messages.length - 1 ? message + 1 : message,
        );
      }
    });
    slowTimer = Timer(const Duration(seconds: 10), () {
      if (mounted) setState(() => slow = true);
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    slowTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(34),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.spa_outlined, size: 72, color: olive),
              const SizedBox(height: 30),
              const Text(
                'Создаём ваш план',
                style: TextStyle(fontSize: 30, color: ink),
              ),
              const SizedBox(height: 14),
              AnimatedSwitcher(
                duration: const Duration(milliseconds: 300),
                child: Text(
                  messages[message],
                  key: ValueKey(message),
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 17),
                ),
              ),
              const SizedBox(height: 26),
              if (slow) ...[
                const Text(
                  'Расчёт занимает немного больше времени. Не закрывайте приложение — мы продолжаем подбирать план.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: olive),
                ),
                const SizedBox(height: 18),
              ],
              TweenAnimationBuilder<double>(
                tween: Tween(begin: 0, end: .96),
                duration: const Duration(seconds: 8),
                builder: (_, value, _) => Column(
                  children: [
                    LinearProgressIndicator(
                      value: value,
                      minHeight: 8,
                      borderRadius: BorderRadius.circular(8),
                      color: olive,
                    ),
                    const SizedBox(height: 8),
                    Text('${(value * 100).round()}%'),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
