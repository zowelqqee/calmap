import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/api_client.dart';
import 'core/subscription.dart';
import 'core/theme.dart';
import 'screens/auth_screen.dart';
import 'screens/home_screen.dart';
import 'screens/intro_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/paywall_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
  runApp(const CalmapApp());
}

enum AppStage { loading, intro, auth, onboarding, home, paywall }

class CalmapApp extends StatefulWidget {
  const CalmapApp({super.key});

  @override
  State<CalmapApp> createState() => _CalmapAppState();
}

class _CalmapAppState extends State<CalmapApp> with WidgetsBindingObserver {
  final ApiClient api = ApiClient();
  final navigatorKey = GlobalKey<NavigatorState>();
  AppStage stage = AppStage.loading;
  String? startupError;
  bool startInRegisterMode = false;
  SubscriptionStatus? subscription;
  bool onboardingCompleted = false;
  Timer? _accessTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    api.onSessionExpired = () => _goTo(AppStage.auth);
    api.onSubscriptionRequired = () {
      if (stage == AppStage.home || stage == AppStage.onboarding) {
        _refreshSubscription();
      }
    };
    _bootstrap();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _accessTimer?.cancel();
    super.dispose();
  }

  /// Back from Telegram (or from the background): the bot may have changed the
  /// payment status in the meantime.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed &&
        (stage == AppStage.home || stage == AppStage.paywall)) {
      _refreshSubscription();
    }
  }

  /// Reads the payment status and shows the app or the paywall accordingly.
  /// Returns true when the user has access.
  Future<bool> _refreshSubscription() async {
    try {
      final status = await fetchSubscription(api);
      if (!mounted) return status.hasAccess;
      setState(() => subscription = status);
      _scheduleAccessCheck(status);
      if (status.hasAccess) {
        if (stage != AppStage.home && stage != AppStage.onboarding) {
          _goTo(onboardingCompleted ? AppStage.home : AppStage.onboarding);
        }
      } else if (stage != AppStage.paywall) {
        _goTo(AppStage.paywall);
      }
      return status.hasAccess;
    } on ApiException catch (exception) {
      if (exception.statusCode == 401) return false;
      if (stage == AppStage.loading && mounted) {
        setState(() => startupError = exception.message);
      }
      return subscription?.hasAccess ?? false;
    }
  }

  /// Re-check exactly when the paid period or trial ends, so the paywall appears
  /// even if the app stays open.
  void _scheduleAccessCheck(SubscriptionStatus status) {
    _accessTimer?.cancel();
    final until = status.accessUntil;
    if (!status.hasAccess || until == null) return;
    var delay = until.difference(DateTime.now()) + const Duration(seconds: 1);
    if (delay > const Duration(hours: 12)) delay = const Duration(hours: 12);
    _accessTimer = Timer(delay, _refreshSubscription);
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
      onboardingCompleted = me['onboarding_completed'] == true;
      if (!onboardingCompleted) {
        _goTo(AppStage.onboarding);
        return;
      }
      await _refreshSubscription();
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
    _accessTimer?.cancel();
    subscription = null;
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
          onCompleted: () async {
            onboardingCompleted = true;
            _goTo(AppStage.home);
            await _refreshSubscription();
          },
        ),
        AppStage.home => HomeScreen(
          api: api,
          onLogout: _logout,
          subscription: subscription,
        ),
        AppStage.paywall => PaywallScreen(
          api: api,
          status: subscription,
          onRecheck: _refreshSubscription,
          onLogout: _logout,
        ),
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
