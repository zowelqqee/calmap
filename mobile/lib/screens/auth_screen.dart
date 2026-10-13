import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/oauth_service.dart';
import '../core/theme.dart';

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
  final email = TextEditingController();
  final password = TextEditingController();
  bool register = false;
  bool loading = false;
  bool obscurePassword = true;
  String? error;
  final oauth = OAuthService();

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final tokens = await widget.api.post(
        register ? '/v1/auth/register' : '/v1/auth/login',
        {'email': email.text.trim(), 'password': password.text},
      );
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
      final credential = switch (provider) {
        'apple' => await oauth.apple(),
        'google' => await oauth.google(),
        _ => await oauth.vk(),
      };
      final tokens = await widget.api.post('/v1/auth/oauth/$provider', {
        'id_token': credential.token,
        'email': credential.email,
      });
      await widget.api.saveTokens(tokens);
      await widget.onAuthenticated();
    } catch (exception) {
      if (mounted) {
        setState(
          () => error = exception.toString().replaceFirst('Bad state: ', ''),
        );
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
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _OAuthButton(
                  label: 'Apple',
                  onTap: loading ? null : () => _oauth('apple'),
                ),
                const SizedBox(width: 8),
                _OAuthButton(
                  label: 'Google',
                  onTap: loading ? null : () => _oauth('google'),
                ),
                const SizedBox(width: 8),
                _OAuthButton(
                  label: 'VK',
                  onTap: loading ? null : () => _oauth('vk'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

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
