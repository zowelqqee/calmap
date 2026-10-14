import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/api_client.dart';
import '../core/legal.dart';
import '../core/oauth_service.dart';
import '../core/theme.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({
    required this.api,
    required this.onAuthenticated,
    this.initialRegister = false,
    super.key,
  });

  final bool initialRegister;
  final ApiClient api;
  final Future<void> Function() onAuthenticated;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final email = TextEditingController();
  final password = TextEditingController();
  late bool register = widget.initialRegister;
  bool loading = false;
  bool obscurePassword = true;
  bool personalDataConsent = false;
  String? error;
  final oauth = OAuthService();

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final emailText = email.text.trim();
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(emailText)) {
      setState(() => error = 'Введите корректный email');
      return;
    }
    if (register && password.text.length < 8) {
      setState(() => error = 'Пароль — не короче 8 символов');
      return;
    }
    if (register && !personalDataConsent) {
      setState(
        () => error = 'Для регистрации нужно согласие на обработку данных',
      );
      return;
    }
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final tokens = await widget.api
          .post(register ? '/v1/auth/register' : '/v1/auth/login', {
            'email': emailText,
            'password': password.text,
            if (register) 'personal_data_consent': true,
          });
      await widget.api.saveTokens(tokens);
      await widget.onAuthenticated();
    } on ApiException catch (exception) {
      if (mounted) setState(() => error = exception.message);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _oauth(String provider) async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final credential = await oauth.vk();
      final tokens = await widget.api.post('/v1/auth/oauth/$provider', {
        'id_token': credential.token,
        // A first VK sign-in creates the account, which needs the consent.
        'personal_data_consent': personalDataConsent,
      });
      await widget.api.saveTokens(tokens);
      await widget.onAuthenticated();
    } on ApiException catch (exception) {
      if (mounted) {
        setState(() {
          error = exception.message;
          // New VK account without consent: show the consent checkbox.
          if (exception.statusCode == 422) register = true;
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
        setState(() => error = 'Не удалось войти через внешний сервис');
      }
    } catch (_) {
      if (mounted) {
        setState(() => error = 'Не удалось войти через внешний сервис');
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
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
              'Добро пожаловать',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.displayMedium,
            ),
            const SizedBox(height: 10),
            Text(
              'Войдите или создайте аккаунт, чтобы продолжить',
              textAlign: TextAlign.center,
              style: Theme.of(
                context,
              ).textTheme.bodyLarge?.copyWith(color: mutedInk),
            ),
            const SizedBox(height: 34),
            TextField(
              controller: email,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.next,
              decoration: const InputDecoration(labelText: 'Email'),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: password,
              obscureText: obscurePassword,
              onSubmitted: (_) => _submit(),
              decoration: InputDecoration(
                labelText: 'Пароль',
                suffixIcon: IconButton(
                  style: IconButton.styleFrom(
                    backgroundColor: Colors.transparent,
                    side: BorderSide.none,
                  ),
                  onPressed: () =>
                      setState(() => obscurePassword = !obscurePassword),
                  icon: Icon(
                    obscurePassword
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
            ),
            if (register) ...[
              const SizedBox(height: 10),
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
              onPressed: loading ? null : _submit,
              child: loading
                  ? const SizedBox.square(
                      dimension: 22,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(register ? 'Создать аккаунт' : 'Войти'),
            ),
            TextButton(
              onPressed: loading
                  ? null
                  : () => setState(() => register = !register),
              child: Text(
                register ? 'У меня уже есть аккаунт' : 'Зарегистрироваться',
              ),
            ),
            if (_oauthProviders.isNotEmpty) ...[
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
              Wrap(
                alignment: WrapAlignment.center,
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final entry in _oauthProviders.entries)
                    _OAuthButton(
                      label: entry.value,
                      onTap: loading ? null : () => _oauth(entry.key),
                    ),
                ],
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

/// External sign-in buttons this build is configured for (Russian services only).
Map<String, String> get _oauthProviders => {
  if (OAuthService.vkClientId.isNotEmpty) 'vk': 'VK ID',
};

class _OAuthButton extends StatelessWidget {
  const _OAuthButton({required this.label, required this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => OutlinedButton(
    onPressed: onTap,
    style: OutlinedButton.styleFrom(
      minimumSize: const Size(96, 48),
      padding: const EdgeInsets.symmetric(horizontal: 16),
    ),
    child: Text(label),
  );
}
