import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'theme.dart';

/// Public legal pages served by the backend (`/legal/privacy`, `/legal/terms`).
Future<void> openLegalPage(
  BuildContext context,
  ApiClient api,
  String page,
) async {
  final uri = Uri.parse('${api.baseUrl}/legal/$page');
  final opened = await launchUrl(uri, mode: LaunchMode.inAppBrowserView);
  if (!opened && context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Не удалось открыть документ')),
    );
  }
}

/// Consent sentence: the prefix followed by links to the terms and the privacy policy.
class LegalLinksText extends StatefulWidget {
  const LegalLinksText({
    required this.api,
    required this.prefix,
    this.textAlign = TextAlign.center,
    super.key,
  });

  final ApiClient api;
  final String prefix;
  final TextAlign textAlign;

  @override
  State<LegalLinksText> createState() => _LegalLinksTextState();
}

class _LegalLinksTextState extends State<LegalLinksText> {
  late final TapGestureRecognizer _terms = TapGestureRecognizer()
    ..onTap = () => openLegalPage(context, widget.api, 'terms');
  late final TapGestureRecognizer _privacy = TapGestureRecognizer()
    ..onTap = () => openLegalPage(context, widget.api, 'privacy');

  @override
  void dispose() {
    _terms.dispose();
    _privacy.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const link = TextStyle(
      color: olive,
      decoration: TextDecoration.underline,
      fontWeight: FontWeight.w600,
    );
    return Text.rich(
      TextSpan(
        style: const TextStyle(color: mutedInk, fontSize: 13, height: 1.4),
        children: [
          TextSpan(text: '${widget.prefix} '),
          TextSpan(
            text: 'Пользовательское соглашение',
            style: link,
            recognizer: _terms,
          ),
          const TextSpan(text: ' и '),
          TextSpan(
            text: 'Политику обработки персональных данных',
            style: link,
            recognizer: _privacy,
          ),
        ],
      ),
      textAlign: widget.textAlign,
    );
  }
}

/// Consents asked in the app when a feature first needs them (152-FZ art. 9, 12).
class ConsentRequest {
  const ConsentRequest({
    required this.document,
    required this.title,
    required this.summary,
    required this.page,
  });

  final String document;
  final String title;
  final String summary;

  /// Full text at `/legal/<page>`.
  final String page;

  static const aiAssistant = ConsentRequest(
    document: 'ai_assistant',
    title: 'Передача данных AI-консультанту',
    summary:
        'Для ответа AI-консультанту передаются ваш вопрос, данные анкеты '
        '(пол, вес, цель, тип питания, аллергии, бюджет), нормы и последние '
        'записи дневника. Имя и номер телефона не передаются. Сервис может '
        'находиться за пределами России.',
    page: 'ai-consent',
  );

  static const photoRecognition = ConsentRequest(
    document: 'photo_recognition',
    title: 'Распознавание фото',
    summary:
        'Фото блюда передаётся сервису распознавания. Геопозиция, модель '
        'телефона и время съёмки из файла удаляются, имя и номер телефона не '
        'передаются. Фото не хранится на сервере. Сервис может находиться за '
        'пределами России.',
    page: 'photo-consent',
  );

  static const all = [aiAssistant, photoRecognition];

  static ConsentRequest? byDocument(String? document) {
    for (final request in all) {
      if (request.document == document) return request;
    }
    return null;
  }
}

/// Shows the consent and records it on the server when accepted.
Future<bool> askConsent(
  BuildContext context,
  ApiClient api,
  ConsentRequest request,
) async {
  final accepted = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: Text(request.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(request.summary),
          const SizedBox(height: 10),
          GestureDetector(
            onTap: () => openLegalPage(context, api, request.page),
            child: const Text(
              'Текст согласия',
              style: TextStyle(
                color: olive,
                decoration: TextDecoration.underline,
              ),
            ),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext, false),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(dialogContext, true),
          child: const Text('Согласен'),
        ),
      ],
    ),
  );
  if (accepted != true) return false;
  await api.post('/v1/me/consents', {'document': request.document});
  return true;
}

/// Runs [action]; when the server asks for one of the in-app consents, asks
/// the user and repeats [action] once after consent.
Future<T> withConsent<T>(
  BuildContext context,
  ApiClient api,
  Future<T> Function() action,
) async {
  try {
    return await action();
  } on ApiException catch (exception) {
    final request = ConsentRequest.byDocument(exception.consentDocument);
    if (request == null || !context.mounted) rethrow;
    if (!await askConsent(context, api, request)) rethrow;
    return action();
  }
}
