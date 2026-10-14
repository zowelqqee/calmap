import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/api_client.dart';
import 'core/theme.dart';
import 'screens/auth_screen.dart';
import 'screens/home_screen.dart';
import 'screens/intro_screen.dart';
import 'screens/onboarding_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
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
  final navigatorKey = GlobalKey<NavigatorState>();
  AppStage stage = AppStage.loading;
  String? startupError;
  bool startInRegisterMode = false;

  @override
  void initState() {
    super.initState();
    api.onSessionExpired = () => _goTo(AppStage.auth);
    _bootstrap();
  }

  /// Switch the root stage and drop any screens pushed on top of the old one.
  void _goTo(AppStage next) {
    if (!mounted) return;
    navigatorKey.currentState?.popUntil((route) => route.isFirst);
    setState(() {
      startupError = null;
      stage = next;
    });
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
      _goTo(
        me['onboarding_completed'] == true
            ? AppStage.home
            : AppStage.onboarding,
      );
    } on ApiException catch (exception) {
      if (exception.statusCode == 401) {
        await api.clearSession();
        _goTo(AppStage.auth);
        return;
      }
      // Offline or a server outage is not a reason to sign the user out.
      if (mounted) {
        setState(() {
          stage = AppStage.loading;
          startupError = exception.message;
        });
      }
    }
  }

  Future<void> _logout() async {
    await api.clearSession();
    _goTo(AppStage.auth);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
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
        AppStage.loading => _SplashScreen(
          error: startupError,
          onRetry: () {
            setState(() => startupError = null);
            _afterAuthentication();
          },
        ),
        AppStage.intro => IntroScreen(
          onCompleted: ({required bool register}) async {
            await api.markIntroSeen();
            startInRegisterMode = register;
            _goTo(AppStage.auth);
          },
        ),
        AppStage.auth => AuthScreen(
          api: api,
          initialRegister: startInRegisterMode,
          onAuthenticated: _afterAuthentication,
        ),
        AppStage.onboarding => OnboardingScreen(
          api: api,
          onCompleted: () => _goTo(AppStage.home),
        ),
        AppStage.home => HomeScreen(api: api, onLogout: _logout),
      },
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen({this.error, this.onRetry});

  final String? error;
  final VoidCallback? onRetry;

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
            if (error != null) ...[
              const SizedBox(height: 32),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Text(
                  error!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: mutedInk),
                ),
              ),
              const SizedBox(height: 14),
              FilledButton(onPressed: onRetry, child: const Text('Повторить')),
            ],
          ],
        ),
      ),
    );
  }
}
