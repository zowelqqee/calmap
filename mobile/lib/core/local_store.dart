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

  File? _installMarker;

  Future<void> open() async {
    if (_file != null) return;
    // The cache holds health data. It lives in the platform cache directory,
    // which is excluded from iCloud/iTunes and Android Auto Backup and from
    // device-to-device transfer; the OS may purge it under storage pressure,
    // which only costs an offline copy.
    final cache = await getApplicationCacheDirectory();
    final support = await getApplicationSupportDirectory();
    _installMarker = File('${support.path}/.calmap_installed');
    _file = File('${cache.path}/calmap_local_store.json');
    // Earlier versions kept the cache in Application Support (backed up).
    final legacy = File('${support.path}/calmap_local_store.json');
    if (await legacy.exists()) await legacy.delete();
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

  /// True until [markLaunched]: app files are removed on uninstall, unlike the
  /// keychain, so a missing marker means a fresh install.
  Future<bool> isFirstLaunch() async {
    await open();
    return !(await _installMarker!.exists());
  }

  Future<void> markLaunched() async {
    await open();
    await _installMarker!.create(recursive: true);
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

  Future<void> _writing = Future<void>.value();

  /// Writes are chained: parallel requests would otherwise share the temporary
  /// file and fail each other's rename.
  Future<void> _persist() {
    final next = _writing.catchError((_) {}).then((_) => _writeNow());
    _writing = next;
    return next;
  }

  Future<void> _writeNow() async {
    final file = _file;
    if (file == null) return;
    await file.parent.create(recursive: true);
    final temporary = File('${file.path}.tmp');
    await temporary.writeAsString(jsonEncode(_state), flush: true);
    await temporary.rename(file.path);
  }
}
