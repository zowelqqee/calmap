import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/legal.dart';
import '../core/oauth_service.dart';
import '../core/theme.dart';

/// Sign-in by a Russian mobile number and an SMS code (the first sign-in creates
/// the account), or through VK ID when the build is configured for it.
class AuthScreen extends StatefulWidget {
  const AuthScreen({
    required this.api,
    required this.onAuthenticated,
    super.key,
  });

  final ApiClient api;
  final Future<void> Function() onAuthenticated;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final phone = TextEditingController();
  final code = TextEditingController();
  final oauth = OAuthService();

  /// The number the code was sent to (normalised digits, 7XXXXXXXXXX).
  String? sentTo;
  bool loading = false;

  /// Shown once the server says this sign-in creates a new account.
  bool consentNeeded = false;
  bool personalDataConsent = false;
  int resendIn = 0;
  Timer? _resendTimer;
  String? error;

  @override
  void dispose() {
    _resendTimer?.cancel();
    phone.dispose();
    code.dispose();
    super.dispose();
  }

  /// 10 digits after +7 for a Russian mobile number, or null.
  String? get _phoneDigits {
    var digits = phone.text.replaceAll(RegExp(r'\D'), '');
    if (digits.length == 11 && (digits[0] == '7' || digits[0] == '8')) {
      digits = digits.substring(1);
    }
    return digits.length == 10 && digits.startsWith('9') ? digits : null;
  }

  void _startResendTimer(int seconds) {
    _resendTimer?.cancel();
    setState(() => resendIn = seconds);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted || resendIn <= 1) {
        timer.cancel();
        if (mounted) setState(() => resendIn = 0);
        return;
      }
      setState(() => resendIn -= 1);
    });
  }

  Future<void> _requestCode() async {
    final digits = _phoneDigits;
    if (digits == null) {
      setState(() => error = 'Введите российский мобильный номер');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final sent = await widget.api.post('/v1/auth/phone/code', {
        'phone': '+7$digits',
      });
      if (!mounted) return;
      setState(() {
        sentTo = '7$digits';
        code.clear();
      });
      _startResendTimer((sent['resend_in'] as num?)?.toInt() ?? 60);
    } on ApiException catch (exception) {
      if (mounted) setState(() => error = exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _verify() async {
    final number = sentTo;
    if (number == null || code.text.length != 6 || loading) return;
    if (consentNeeded && !personalDataConsent) {
      setState(() => error = 'Отметьте согласие на обработку данных');
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final tokens = await widget.api.post('/v1/auth/phone/verify', {
        'phone': '+$number',
        'code': code.text,
        'personal_data_consent': personalDataConsent,
      });
      await widget.api.saveTokens(tokens);
      await widget.onAuthenticated();
    } on ApiException catch (exception) {
      if (!mounted) return;
      setState(() {
        if (exception.statusCode == 422) {
          // New account: the code is still valid, the consent is missing.
          consentNeeded = true;
          error = 'Это новый аккаунт. Отметьте согласие и нажмите «Войти».';
        } else {
          error = exception.message;
        }
      });
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _vk() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final credential = await oauth.vk();
      final tokens = await widget.api.post('/v1/auth/oauth/vk', {
        'id_token': credential.token,
        'personal_data_consent': personalDataConsent,
      });
      await widget.api.saveTokens(tokens);
      await widget.onAuthenticated();
    } on ApiException catch (exception) {
      if (mounted) {
        setState(() {
          if (exception.statusCode == 422) {
            consentNeeded = true;
            error = 'Отметьте согласие на обработку данных и повторите вход.';
          } else {
            error = exception.message;
          }
        });
      }
    } on OAuthNotConfigured {
      if (mounted) setState(() => error = 'Этот способ входа пока недоступен');
    } on PlatformException catch (exception) {
      // flutter_appauth reports a closed browser as a platform error.
      final cancelled =
          exception.code.contains('cancel') ||
          (exception.message ?? '').toLowerCase().contains('cancel');
      if (mounted && !cancelled) {
        setState(() => error = 'Не удалось войти через VK ID');
      }
    } catch (_) {
      if (mounted) setState(() => error = 'Не удалось войти через VK ID');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  String get _sentToLabel {
    final n = sentTo ?? '';
    if (n.length != 11) return '+$n';
    return '+7 ${n.substring(1, 4)} ${n.substring(4, 7)}-'
        '${n.substring(7, 9)}-${n.substring(9)}';
  }

  @override
  Widget build(BuildContext context) {
    final codeStep = sentTo != null;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(24, 46, 24, 28),
          children: [
            Center(
              child: Container(
                width: 62,
                height: 62,
                decoration: BoxDecoration(
                  color: forest,
                  borderRadius: BorderRadius.circular(20),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x24173D31),
                      blurRadius: 22,
                      offset: Offset(0, 9),
                    ),
                  ],
                ),
                child: const Icon(
                  Icons.spa_outlined,
                  color: Color(0xFFE7D4AB),
                  size: 29,
                ),
              ),
            ),
            const SizedBox(height: 24),
            Text(
              codeStep ? 'Введите код' : 'Вход в Calmap',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.displayMedium,
            ),
            const SizedBox(height: 10),
            Text(
              codeStep
                  ? 'Отправили SMS на $_sentToLabel'
                  : 'Укажите номер телефона — пришлём код в SMS. '
                        'Аккаунт создастся автоматически.',
              textAlign: TextAlign.center,
              style: Theme.of(
                context,
              ).textTheme.bodyLarge?.copyWith(color: mutedInk),
            ),
            const SizedBox(height: 30),
            if (!codeStep)
              TextField(
                controller: phone,
                keyboardType: TextInputType.phone,
                autofillHints: const [AutofillHints.telephoneNumber],
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[\d\s()+-]')),
                  LengthLimitingTextInputFormatter(18),
                ],
                onSubmitted: (_) => _requestCode(),
                decoration: const InputDecoration(
                  labelText: 'Номер телефона',
                  prefixText: '+7 ',
                  hintText: '999 123-45-67',
                ),
              )
            else ...[
              TextField(
                controller: code,
                autofocus: true,
                keyboardType: TextInputType.number,
                autofillHints: const [AutofillHints.oneTimeCode],
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  LengthLimitingTextInputFormatter(6),
                ],
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 26, letterSpacing: 8),
                onChanged: (value) {
                  if (value.length == 6 && !consentNeeded) _verify();
                },
                decoration: const InputDecoration(hintText: '••••••'),
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  TextButton(
                    onPressed: loading
                        ? null
                        : () => setState(() {
                            sentTo = null;
                            error = null;
                          }),
                    child: const Text('Изменить номер'),
                  ),
                  TextButton(
                    onPressed: loading || resendIn > 0 ? null : _requestCode,
                    child: Text(
                      resendIn > 0
                          ? 'Новый код через $resendIn с'
                          : 'Отправить снова',
                    ),
                  ),
                ],
              ),
            ],
            if (consentNeeded) ...[
              const SizedBox(height: 6),
              // 152-FZ art. 9: consent is a separate act, not part of the terms.
              CheckboxListTile(
                value: personalDataConsent,
                onChanged: loading
                    ? null
                    : (value) =>
                          setState(() => personalDataConsent = value ?? false),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                activeColor: olive,
                title: const Text(
                  'Даю согласие на обработку моих персональных данных',
                  style: TextStyle(fontSize: 14),
                ),
                subtitle: GestureDetector(
                  onTap: () => openLegalPage(context, widget.api, 'consent'),
                  child: const Text(
                    'Текст согласия',
                    style: TextStyle(
                      color: olive,
                      decoration: TextDecoration.underline,
                    ),
                  ),
                ),
              ),
            ],
            if (error != null) ...[
              const SizedBox(height: 12),
              Text(error!, style: const TextStyle(color: Colors.redAccent)),
            ],
            const SizedBox(height: 20),
            FilledButton(
              onPressed: loading ? null : (codeStep ? _verify : _requestCode),
              child: loading
                  ? const SizedBox.square(
                      dimension: 22,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(codeStep ? 'Войти' : 'Получить код'),
            ),
            if (OAuthService.vkClientId.isNotEmpty && !codeStep) ...[
              const SizedBox(height: 14),
              const Row(
                children: [
                  Expanded(child: Divider()),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12),
                    child: Text('или'),
                  ),
                  Expanded(child: Divider()),
                ],
              ),
              const SizedBox(height: 14),
              OutlinedButton(
                onPressed: loading ? null : _vk,
                child: const Text('Войти через VK ID'),
              ),
            ],
            const SizedBox(height: 22),
            LegalLinksText(api: widget.api, prefix: 'Продолжая, вы принимаете'),
          ],
        ),
      ),
    );
  }
}
