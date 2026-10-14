import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/subscription.dart';
import '../core/theme.dart';
import 'calorie_tracker_screen.dart';
import 'dashboard_screen.dart';
import 'plan_screen.dart';
import 'progress_screen.dart';
import 'workout_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({
    required this.api,
    required this.onLogout,
    this.subscription,
    super.key,
  });

  final ApiClient api;
  final Future<void> Function() onLogout;
  final SubscriptionStatus? subscription;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int index = 0;

  @override
  Widget build(BuildContext context) {
    final pages = [
      DashboardScreen(
        api: widget.api,
        onSelectTab: (value) => setState(() => index = value),
        onLogout: widget.onLogout,
        subscription: widget.subscription,
      ),
      PlanScreen(api: widget.api),
      WorkoutScreen(api: widget.api),
      ProgressScreen(api: widget.api),
      CalorieTrackerScreen(api: widget.api),
    ];
    return Scaffold(
      body: IndexedStack(index: index, children: pages),
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          color: warmWhite,
          border: Border(top: BorderSide(color: line, width: .8)),
          boxShadow: [
            BoxShadow(
              color: Color(0x10173D31),
              blurRadius: 22,
              offset: Offset(0, -6),
            ),
          ],
        ),
        child: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: (value) => setState(() => index = value),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.home_outlined),
              selectedIcon: Icon(Icons.home_rounded),
              label: 'Главная',
            ),
            NavigationDestination(
              icon: Icon(Icons.restaurant_outlined),
              selectedIcon: Icon(Icons.restaurant_rounded),
              label: 'Питание',
            ),
            NavigationDestination(
              icon: Icon(Icons.fitness_center_outlined),
              selectedIcon: Icon(Icons.fitness_center_rounded),
              label: 'Тренировки',
            ),
            NavigationDestination(
              icon: Icon(Icons.monitor_heart_outlined),
              selectedIcon: Icon(Icons.monitor_heart_rounded),
              label: 'Прогресс',
            ),
            NavigationDestination(
              icon: Icon(Icons.local_fire_department_outlined),
              selectedIcon: Icon(Icons.local_fire_department_rounded),
              label: 'Калории',
            ),
          ],
        ),
      ),
    );
  }
}
