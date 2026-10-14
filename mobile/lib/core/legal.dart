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
