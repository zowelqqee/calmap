import 'package:flutter_appauth/flutter_appauth.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';

class OAuthCredential {
  const OAuthCredential({required this.token, this.email});

  final String token;
  final String? email;
}

class OAuthService {
  static const googleServerClientId = String.fromEnvironment(
    'GOOGLE_SERVER_CLIENT_ID',
  );
  static const vkClientId = String.fromEnvironment('VK_CLIENT_ID');
  static const vkRedirectUrl = String.fromEnvironment(
    'VK_REDIRECT_URL',
    defaultValue: 'ru.calmap.app:/oauth',
  );

  final FlutterAppAuth _appAuth = const FlutterAppAuth();
  final GoogleSignIn _google = GoogleSignIn.instance;
  bool _googleInitialized = false;

  Future<OAuthCredential> google() async {
    if (googleServerClientId.isEmpty) {
      throw StateError('Передайте GOOGLE_SERVER_CLIENT_ID через --dart-define');
    }
    if (!_googleInitialized) {
      await _google.initialize(serverClientId: googleServerClientId);
      _googleInitialized = true;
    }
    if (!_google.supportsAuthenticate()) {
      throw StateError(
        'Интерактивный вход Google не поддерживается на этом устройстве',
      );
    }
    final account = await _google.authenticate(scopeHint: const ['email']);
    final authentication = account.authentication;
    if (authentication.idToken == null) {
      throw StateError('Google не вернул id_token');
    }
    return OAuthCredential(
      token: authentication.idToken!,
      email: account.email,
    );
  }

  Future<OAuthCredential> apple() async {
    final credential = await SignInWithApple.getAppleIDCredential(
      scopes: [AppleIDAuthorizationScopes.email],
    );
    if (credential.identityToken == null) {
      throw StateError('Apple не вернул identity token');
    }
    return OAuthCredential(
      token: credential.identityToken!,
      email: credential.email,
    );
  }

  Future<OAuthCredential> vk() async {
    if (vkClientId.isEmpty || vkRedirectUrl.isEmpty) {
      throw StateError(
        'Передайте VK_CLIENT_ID и VK_REDIRECT_URL через --dart-define',
      );
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
