import 'package:flutter/material.dart';

import '../core/theme.dart';

class IntroScreen extends StatefulWidget {
  const IntroScreen({required this.onCompleted, super.key});

  final Future<void> Function() onCompleted;

  @override
  State<IntroScreen> createState() => _IntroScreenState();
}

class _IntroScreenState extends State<IntroScreen> {
  final controller = PageController();
  int page = 0;

  static const pages = [
    (
      icon: Icons.person_outline,
      title: 'Твой персональный план',
      text: 'Питание и тренировки под твои цели',
    ),
    (
      icon: Icons.shopping_basket_outlined,
      title: 'Реальные продукты из магазина',
      text: 'Точные калории и примерная стоимость корзины',
    ),
    (
      icon: Icons.fitness_center,
      title: 'Тренировки под твой уровень',
      text: 'Адаптивный план и понятный прогресс',
    ),
  ];

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> _next() async {
    if (page < pages.length - 1) {
      await controller.nextPage(
        duration: const Duration(milliseconds: 280),
        curve: Curves.easeOutCubic,
      );
    } else {
      await widget.onCompleted();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Column(
        children: [
          const SizedBox(height: 28),
          Expanded(
            child: PageView.builder(
              controller: controller,
              itemCount: pages.length,
              onPageChanged: (value) => setState(() => page = value),
              itemBuilder: (_, index) {
                final item = pages[index];
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 34),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Container(
                        width: 142,
                        height: 142,
                        decoration: BoxDecoration(
                          gradient: const LinearGradient(
                            begin: Alignment.topLeft,
                            end: Alignment.bottomRight,
                            colors: [sageLight, Color(0xFFD5E2D5)],
                          ),
                          borderRadius: BorderRadius.circular(42),
                          border: Border.all(color: Colors.white, width: 1.5),
                          boxShadow: const [
                            BoxShadow(
                              color: Color(0x16173D31),
                              blurRadius: 30,
                              offset: Offset(0, 12),
                            ),
                          ],
                        ),
                        child: Icon(item.icon, size: 54, color: olive),
                      ),
                      const SizedBox(height: 42),
                      Text(
                        item.title,
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.displayMedium,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        item.text,
                        textAlign: TextAlign.center,
                        style: Theme.of(
                          context,
                        ).textTheme.bodyLarge?.copyWith(color: mutedInk),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (var index = 0; index < pages.length; index++)
                AnimatedContainer(
                  duration: const Duration(milliseconds: 180),
                  width: index == page ? 24 : 8,
                  height: 8,
                  margin: const EdgeInsets.symmetric(horizontal: 4),
                  decoration: BoxDecoration(
                    color: index == page ? olive : const Color(0xFFC9CEC9),
                    borderRadius: BorderRadius.circular(8),
                  ),
                ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 24, 24, 24),
            child: Column(
              children: [
                FilledButton(
                  onPressed: _next,
                  child: Text(page == pages.length - 1 ? 'Начать' : 'Далее'),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}
