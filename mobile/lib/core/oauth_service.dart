import 'package:flutter_appauth/flutter_appauth.dart';

class OAuthCredential {
  const OAuthCredential({required this.token});

  final String token;
}

/// The build was made without the provider's client ID.
class OAuthNotConfigured implements Exception {
  const OAuthNotConfigured(this.provider);

  final String provider;
}

/// External sign-in. Only VK ID is offered: since 1 December 2023 Russian
/// services may authorise users only by a Russian phone number, Gosuslugi, the
/// Unified Biometric System or a Russian-owned system (149-FZ), and sign-in via
/// Google or Apple ID is fined under article 13.55 of the Administrative Code.
class OAuthService {
  static const vkClientId = String.fromEnvironment('VK_CLIENT_ID');
  static const vkRedirectUrl = String.fromEnvironment(
    'VK_REDIRECT_URL',
    defaultValue: 'ru.calmap.app:/oauth',
  );

  final FlutterAppAuth _appAuth = const FlutterAppAuth();

  Future<OAuthCredential> vk() async {
    if (vkClientId.isEmpty || vkRedirectUrl.isEmpty) {
      throw const OAuthNotConfigured('vk');
    }
    final result = await _appAuth.authorizeAndExchangeCode(
      AuthorizationTokenRequest(
        vkClientId,
        vkRedirectUrl,
        serviceConfiguration: const AuthorizationServiceConfiguration(
          authorizationEndpoint: 'https://id.vk.com/authorize',
          tokenEndpoint: 'https://id.vk.com/oauth2/auth',
        ),
        scopes: const ['vkid.personal_info', 'email'],
      ),
    );
    final token = result.accessToken;
    if (token == null) throw StateError('VK не вернул access token');
    return OAuthCredential(token: token);
  }
}
