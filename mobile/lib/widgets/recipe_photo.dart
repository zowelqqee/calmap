import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

/// Local editorial food photos keep the experience complete before the catalogue
/// is connected to a CMS. A real `image_url` from the API takes precedence.
class RecipePhoto extends StatefulWidget {
  const RecipePhoto({
    required this.mealType,
    this.recipeName,
    this.imageUrl,
    required this.width,
    required this.height,
    required this.borderRadius,
    super.key,
  });

  final String mealType;
  final String? recipeName;
  final String? imageUrl;
  final double width;
  final double height;
  final BorderRadius borderRadius;

  @override
  State<RecipePhoto> createState() => _RecipePhotoState();
}

class _RecipePhotoState extends State<RecipePhoto> {
  Uint8List? _cachedBytes;

  @override
  void initState() {
    super.initState();
    _loadRemoteImage();
  }

  @override
  void didUpdateWidget(covariant RecipePhoto oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.imageUrl != widget.imageUrl) {
      _cachedBytes = null;
      _loadRemoteImage();
    }
  }

  Future<void> _loadRemoteImage() async {
    final url = widget.imageUrl;
    if (url == null || !url.startsWith('http')) return;
    try {
      final directory = await getApplicationSupportDirectory();
      final file = File(
        '${directory.path}/recipe-images/${_stableKey(url)}.img',
      );
      if (await file.exists()) {
        final bytes = await file.readAsBytes();
        if (mounted) setState(() => _cachedBytes = bytes);
        return;
      }
      final response = await http
          .get(Uri.parse(url))
          .timeout(const Duration(seconds: 12));
      if (response.statusCode < 200 || response.statusCode >= 300) return;
      await file.parent.create(recursive: true);
      await file.writeAsBytes(response.bodyBytes, flush: true);
      if (mounted) setState(() => _cachedBytes = response.bodyBytes);
    } catch (_) {
      // The bundled editorial image remains the offline fallback.
    }
  }

  String _stableKey(String value) {
    var hash = 2166136261;
    for (final codeUnit in value.codeUnits) {
      hash = (hash ^ codeUnit) * 16777619 & 0x7fffffff;
    }
    return hash.toRadixString(16);
  }

  String get _asset {
    final name = (widget.recipeName ?? '').toLowerCase();
    if (name.contains('лосос') ||
        name.contains('рыб') ||
        name.contains('семг')) {
      return 'assets/food/salmon_vegetables.png';
    }
    if (name.contains('куриц') ||
        name.contains('греч') ||
        widget.mealType == 'lunch') {
      return 'assets/food/chicken_buckwheat.png';
    }
    if (name.contains('скир') ||
        name.contains('йогурт') ||
        widget.mealType == 'snack') {
      return 'assets/food/skyr_berries.png';
    }
    if (widget.mealType == 'dinner') {
      return 'assets/food/salmon_vegetables.png';
    }
    return 'assets/food/oatmeal_banana_cottage.png';
  }

  @override
  Widget build(BuildContext context) {
    final local = Image.asset(_asset, fit: BoxFit.cover);
    final remote = _cachedBytes == null
        ? local
        : Image.memory(_cachedBytes!, fit: BoxFit.cover);
    return ClipRRect(
      borderRadius: widget.borderRadius,
      child: SizedBox(
        width: widget.width,
        height: widget.height,
        child: remote,
      ),
    );
  }
}
