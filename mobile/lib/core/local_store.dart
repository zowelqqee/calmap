import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Small device-local store for the local-first mobile client.
///
/// The file contains cached API responses and an outbox of mutations that
/// should be retried when connectivity returns. It is deliberately kept
/// behind a tiny interface so the API client does not know anything about the
/// on-disk format.
class LocalStore {
  File? _file;
  Map<String, dynamic> _state = <String, dynamic>{
    'responses': <String, dynamic>{},
    'outbox': <dynamic>[],
  };

  Future<void> open() async {
    if (_file != null) return;
    final directory = await getApplicationSupportDirectory();
    _file = File('${directory.path}/calmap_local_store.json');
    if (!await _file!.exists()) return;

    try {
      final decoded = jsonDecode(await _file!.readAsString());
      if (decoded is Map) {
        _state = <String, dynamic>{
          'responses': Map<String, dynamic>.from(
            decoded['responses'] as Map? ?? const <String, dynamic>{},
          ),
          'outbox': List<dynamic>.from(decoded['outbox'] as List? ?? const []),
        };
      }
    } catch (_) {
      // A corrupt cache should never prevent the app from starting.
      _state = <String, dynamic>{
        'responses': <String, dynamic>{},
        'outbox': <dynamic>[],
      };
    }
  }

  Future<dynamic> readResponse(String key) async {
    await open();
    return _state['responses'][key];
  }

  Future<void> writeResponse(String key, dynamic value) async {
    await open();
    (_state['responses'] as Map<String, dynamic>)[key] = value;
    await _persist();
  }

  Future<void> removeResponse(String key) async {
    await open();
    (_state['responses'] as Map<String, dynamic>).remove(key);
    await _persist();
  }

  Future<void> enqueue({
    required String method,
    required String path,
    Map<String, dynamic>? body,
  }) async {
    await open();
    (_state['outbox'] as List<dynamic>).add(<String, dynamic>{
      'method': method,
      'path': path,
      'body': body,
      'created_at': DateTime.now().toUtc().toIso8601String(),
    });
    await _persist();
  }

  Future<List<Map<String, dynamic>>> get outbox async {
    await open();
    return [
      for (final item in _state['outbox'] as List<dynamic>)
        Map<String, dynamic>.from(item as Map),
    ];
  }

  Future<void> removeFirstOutboxItem() async {
    await open();
    final items = _state['outbox'] as List<dynamic>;
    if (items.isNotEmpty) items.removeAt(0);
    await _persist();
  }

  Future<void> clear() async {
    await open();
    _state = <String, dynamic>{
      'responses': <String, dynamic>{},
      'outbox': <dynamic>[],
    };
    await _persist();
  }

  Future<void> _persist() async {
    final file = _file;
    if (file == null) return;
    await file.parent.create(recursive: true);
    final temporary = File('${file.path}.tmp');
    await temporary.writeAsString(jsonEncode(_state), flush: true);
    await temporary.rename(file.path);
  }
}
