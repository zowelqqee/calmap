import 'package:flutter/material.dart';

import '../core/api_client.dart';
import '../core/legal.dart';
import '../core/theme.dart';

class AssistantScreen extends StatefulWidget {
  const AssistantScreen({required this.api, super.key});

  final ApiClient api;

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final input = TextEditingController();
  final scroll = ScrollController();
  final messages = <Map<String, String>>[];
  String? conversationId;
  bool sending = false;

  @override
  void dispose() {
    input.dispose();
    scroll.dispose();
    super.dispose();
  }

  /// Sends the question; on the first use asks for the separate consent to pass
  /// data to the AI provider (152-FZ art. 10, 12) and retries once.
  Future<Map<String, dynamic>> _ask(String text) => withConsent(
    context,
    widget.api,
    () => widget.api.post('/v1/assistant/chat', {
      'conversation_id': conversationId,
      'message': text,
    }),
  );

  Future<void> _send() async {
    final text = input.text.trim();
    if (text.isEmpty || sending) return;
    input.clear();
    setState(() {
      sending = true;
      messages.add({'role': 'user', 'content': text});
    });
    try {
      final response = await _ask(text);
      conversationId = response['conversation_id'].toString();
      final answer = Map<String, dynamic>.from(response['message'] as Map);
      messages.add({
        'role': 'assistant',
        'content': answer['content'].toString(),
      });
    } on ApiException catch (exception) {
      messages.add({
        'role': 'system',
        'content': exception.statusCode == 402
            ? 'AI-консультант доступен на тарифе PRO. Оформить его можно в профиле.'
            : exception.message,
      });
    } finally {
      if (mounted) {
        setState(() => sending = false);
        await Future<void>.delayed(const Duration(milliseconds: 100));
        if (scroll.hasClients) {
          scroll.animateTo(
            scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOut,
          );
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 22, 20, 12),
            child: Row(
              children: [
                const AccentIconTile(Icons.auto_awesome_rounded),
                const SizedBox(width: 12),
                Text(
                  'AI-консультант',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
              ],
            ),
          ),
          Expanded(
            child: messages.isEmpty
                ? const _AssistantIntro()
                : ListView.builder(
                    controller: scroll,
                    padding: const EdgeInsets.all(18),
                    itemCount: messages.length,
                    itemBuilder: (_, index) {
                      final item = messages[index];
                      final mine = item['role'] == 'user';
                      return Align(
                        alignment: mine
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: Container(
                          constraints: const BoxConstraints(maxWidth: 330),
                          margin: const EdgeInsets.only(bottom: 10),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 16,
                            vertical: 13,
                          ),
                          decoration: BoxDecoration(
                            color: mine ? olive : warmWhite,
                            borderRadius: BorderRadius.only(
                              topLeft: const Radius.circular(18),
                              topRight: const Radius.circular(18),
                              bottomLeft: Radius.circular(mine ? 18 : 5),
                              bottomRight: Radius.circular(mine ? 5 : 18),
                            ),
                            border: mine ? null : Border.all(color: line),
                          ),
                          child: Text(
                            item['content']!,
                            style: TextStyle(
                              color: mine ? Colors.white : ink,
                              height: 1.35,
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: TextField(
                    controller: input,
                    minLines: 1,
                    maxLines: 4,
                    textInputAction: TextInputAction.newline,
                    decoration: const InputDecoration(
                      hintText: 'Задайте вопрос о питании…',
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  onPressed: sending ? null : _send,
                  icon: sending
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.arrow_upward),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AssistantIntro extends StatelessWidget {
  const _AssistantIntro();

  @override
  Widget build(BuildContext context) => const Center(
    child: Padding(
      padding: EdgeInsets.all(36),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.chat_bubble_outline, size: 54, color: olive),
          SizedBox(height: 16),
          Text('Спросите о рационе', style: TextStyle(fontSize: 24)),
          SizedBox(height: 8),
          Text(
            'Консультант учитывает ваши цели, ограничения и записи дневника.',
            textAlign: TextAlign.center,
          ),
        ],
      ),
    ),
  );
}
