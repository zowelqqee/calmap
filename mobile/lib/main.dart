import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/api_client.dart';
import 'core/theme.dart';
import 'screens/auth_screen.dart';
import 'screens/home_screen.dart';
import 'screens/intro_screen.dart';
import 'screens/onboarding_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const CalmapApp());
}

enum AppStage { loading, intro, auth, onboarding, home }

class CalmapApp extends StatefulWidget {
  const CalmapApp({super.key});

  @override
  State<CalmapApp> createState() => _CalmapAppState();
}

class _CalmapAppState extends State<CalmapApp> {
  final ApiClient api = ApiClient();
  AppStage stage = AppStage.loading;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    await Future.wait([
      api.restore(),
      Future<void>.delayed(const Duration(milliseconds: 1200)),
    ]);
    if (!api.hasSession) {
      final seenIntro = await api.hasSeenIntro();
      if (mounted) {
        setState(() => stage = seenIntro ? AppStage.auth : AppStage.intro);
      }
      return;
    }
    await _afterAuthentication();
  }

  Future<void> _afterAuthentication() async {
    try {
      final me = await api.get('/v1/auth/me');
      if (!mounted) return;
      setState(() {
        stage = me['onboarding_completed'] == true
            ? AppStage.home
            : AppStage.onboarding;
      });
    } catch (_) {
      await api.clearSession();
      if (mounted) setState(() => stage = AppStage.auth);
    }
  }

  Future<void> _logout() async {
    await api.clearSession();
    if (mounted) setState(() => stage = AppStage.auth);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Calmap',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: switch (stage) {
        AppStage.loading => const _SplashScreen(),
        AppStage.intro => IntroScreen(
          onCompleted: () async {
            await api.markIntroSeen();
            if (mounted) setState(() => stage = AppStage.auth);
          },
        ),
        AppStage.auth => AuthScreen(
          api: api,
          onAuthenticated: _afterAuthentication,
        ),
        AppStage.onboarding => OnboardingScreen(
          api: api,
          onCompleted: () => setState(() => stage = AppStage.home),
        ),
        AppStage.home => HomeScreen(api: api, onLogout: _logout),
      },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
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
}
