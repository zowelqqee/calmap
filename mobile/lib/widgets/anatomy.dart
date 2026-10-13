import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'anatomy_paths.dart';

/// Geometry for the anatomical workout map.
///
/// The artwork comes from the MIT licensed `MuscleMap` project (see
/// [anatomy_paths.dart] and THIRD_PARTY_NOTICES.md): four models — male and
/// female, front and back — each a set of named muscle shapes.  This file
/// turns them into painted, hit-testable paths and maps their slugs onto
/// Calmap's Russian muscle vocabulary.

/// Which side of the body a view shows.
enum AnatomyView { front, back }

/// One region of the chart, ready to be painted or hit tested.  A region can
/// belong to several of Calmap's muscles — the abdominal wall counts both as
/// `прямая мышца живота` and as part of `кор` — so it carries the whole list.
class AnatomyRegion {
  const AnatomyRegion(this.slug, this.muscles, this.path);

  final String slug;
  final List<String> muscles;
  final Path path;

  /// The load this region should show: the heaviest of its muscles.
  int loadFrom(Map<String, int> loads) {
    var top = 0;
    for (final muscle in muscles) {
      final value = loads[muscle] ?? 0;
      if (value > top) top = value;
    }
    return top;
  }

  /// Which muscle a tap on this region is about.
  String? labelFrom(Map<String, int> loads) {
    String? best;
    var top = 0;
    for (final muscle in muscles) {
      final value = loads[muscle] ?? 0;
      if (value > top) {
        top = value;
        best = muscle;
      }
    }
    return best ?? (muscles.isEmpty ? null : muscles.first);
  }
}

/// The figure resolved into real pixels for a given widget [size].
class AnatomyLayout {
  AnatomyLayout._(this.regions, this.unit);

  /// Resolving parses a hundred paths, so identical figures are reused — the
  /// same two layouts are asked for on every repaint.
  factory AnatomyLayout.resolve({
    required Size size,
    required bool female,
    required AnatomyView view,
  }) {
    final model = '${female ? 'female' : 'male'}'
        '${view == AnatomyView.front ? 'Front' : 'Back'}';
    final key = '${size.width}x${size.height}|$model';
    final cached = _layouts[key];
    if (cached != null) return cached;
    if (_layouts.length > 8) _layouts.clear();
    return _layouts[key] = AnatomyLayout._build(size, model, view);
  }

  static final Map<String, AnatomyLayout> _layouts = {};

  factory AnatomyLayout._build(Size size, String model, AnatomyView view) {
    final box = anatomyViewBoxes[model]!;
    final (originX, originY, width, height) = (box[0], box[1], box[2], box[3]);
    final scale = math.min(size.width / width, size.height / height);
    final fit = Matrix4.identity()
      ..translateByDouble(
        (size.width - width * scale) / 2 - originX * scale,
        (size.height - height * scale) / 2 - originY * scale,
        0,
        1,
      )
      ..scaleByDouble(scale, scale, 1, 1);

    final source = anatomyModels[model]!;
    final regions = <AnatomyRegion>[];
    for (final slug in _drawOrder) {
      final parts = source[slug];
      if (parts == null) continue;
      final path = Path();
      for (final part in parts) {
        path.addPath(parseSvgPath(part), Offset.zero);
      }
      regions.add(
        AnatomyRegion(
          slug,
          musclesOfSlug(slug, view),
          path.transform(fit.storage),
        ),
      );
    }
    return AnatomyLayout._(regions, scale);
  }

  final List<AnatomyRegion> regions;

  /// Pixels per unit of the source artwork, so strokes can be sized in the
  /// drawing's own terms rather than in whatever the widget happens to be.
  final double unit;

  /// Region under [point], preferring whatever is painted last (on top).
  AnatomyRegion? regionAt(Offset point) {
    for (final region in regions.reversed) {
      if (region.path.contains(point)) return region;
    }
    return null;
  }
}

/// Painting order, bottom layer first.
///
/// Beside the muscle groups the anterior model carries label accents —
/// `upperChest` and `lowerChest` sitting as blobs on top of a whole pectoral,
/// `upperAbs` over the abs, `innerQuad` over the thigh.  They mark a group's
/// parts for a textbook rather than dividing it, so they are left out: one
/// muscle, one shape.
const _drawOrder = <String>[
  'hair',
  'head',
  'neck',
  'trapezius',
  'upperBack',
  'lowerBack',
  'deltoids',
  'chest',
  'serratus',
  'abs',
  'obliques',
  'biceps',
  'triceps',
  'forearm',
  'hands',
  'gluteal',
  'quadriceps',
  'hipFlexors',
  'hamstring',
  'adductors',
  'knees',
  'tibialis',
  'calves',
  'ankles',
  'feet',
];

/// Slug to Calmap's muscles, per view: the same shoulder cap is the front and
/// lateral deltoid seen from the front, and the rear deltoid seen from behind.
const _frontMuscles = <String, List<String>>{
  'neck': ['шея'],
  'trapezius': ['трапеции'],
  'deltoids': ['передняя дельта', 'средняя дельта'],
  'chest': ['грудь'],
  'serratus': ['передняя зубчатая'],
  'abs': ['прямая мышца живота', 'кор'],
  'obliques': ['косые мышцы живота', 'кор'],
  'biceps': ['бицепс'],
  'triceps': ['трицепс'],
  'forearm': ['предплечья'],
  'quadriceps': ['квадрицепсы'],
  'hipFlexors': ['сгибатели бедра'],
  'adductors': ['приводящие мышцы бедра'],
  'tibialis': ['икры'],
  'calves': ['икры', 'камбаловидная'],
};

const _backMuscles = <String, List<String>>{
  'neck': ['шея'],
  // The posterior model splits the back into the trapezius diamond and the
  // scapular wings, so the mid-back work lands on the first and the lats on
  // the second; the cuff has no shape of its own and rides with the wings.
  'trapezius': ['трапеции', 'верх спины'],
  'upperBack': ['широчайшие', 'вращательная манжета'],
  'lowerBack': ['разгибатели спины', 'кор'],
  'deltoids': ['задняя дельта'],
  'triceps': ['трицепс'],
  'forearm': ['предплечья'],
  'gluteal': ['ягодицы', 'средняя ягодичная'],
  'hamstring': ['задняя поверхность бедра'],
  'adductors': ['приводящие мышцы бедра'],
  'calves': ['икры', 'камбаловидная'],
};

/// Height-to-width ratio of a model, so a figure can be given exactly the room
/// it fills.  The female model is drawn taller and narrower than the male one.
double anatomyAspect(bool female) {
  final box = anatomyViewBoxes[female ? 'femaleFront' : 'maleFront']!;
  return box[3] / box[2];
}

/// Muscles drawn on [slug] in [view]; empty for hair, head, hands and feet.
List<String> musclesOfSlug(String slug, AnatomyView view) =>
    (view == AnatomyView.front ? _frontMuscles : _backMuscles)[slug] ??
    const <String>[];

/// Muscles the map is able to show at all.
final Set<String> anatomyMuscles = {
  for (final muscles in _frontMuscles.values) ...muscles,
  for (final muscles in _backMuscles.values) ...muscles,
};

/// Views a muscle appears in — used to tell the user where to look.
Set<AnatomyView> anatomyViewsOf(String muscle) => {
  for (final view in AnatomyView.values)
    if ((view == AnatomyView.front ? _frontMuscles : _backMuscles).entries.any(
      (entry) => entry.value.contains(muscle) && _drawOrder.contains(entry.key),
    ))
      view,
};

// ---------------------------------------------------------------------------
// SVG path parsing.
// ---------------------------------------------------------------------------

/// Parses one SVG path `d` string: relative commands, the smooth curve
/// shorthands and elliptical arcs included.
///
/// Scanned by hand rather than tokenised up front because arc flags are single
/// characters that may be packed against their neighbours — in `a1 1 0 01-.4-1`
/// the `01-.4-1` is two flags and two coordinates.
Path parseSvgPath(String data) {
  final scanner = _PathScanner(data);
  final path = Path();
  var current = Offset.zero;
  var start = Offset.zero;
  var cubicControl = Offset.zero;
  var quadraticControl = Offset.zero;
  var command = '';

  while (scanner.hasCommand || scanner.hasNumber) {
    command = scanner.command() ?? command;
    if (command.isEmpty) break;
    final relative = command.toLowerCase() == command;
    Offset point() {
      final x = scanner.number();
      final offset = Offset(x, scanner.number());
      return relative ? current + offset : offset;
    }

    switch (command.toUpperCase()) {
      case 'M':
        current = point();
        start = current;
        path.moveTo(current.dx, current.dy);
        cubicControl = current;
        quadraticControl = current;
        // Further coordinate pairs after a moveto are implicit linetos.
        command = relative ? 'l' : 'L';
      case 'L':
        current = point();
        path.lineTo(current.dx, current.dy);
        cubicControl = current;
        quadraticControl = current;
      case 'H':
        final x = scanner.number();
        current = Offset(relative ? current.dx + x : x, current.dy);
        path.lineTo(current.dx, current.dy);
        cubicControl = current;
      case 'V':
        final y = scanner.number();
        current = Offset(current.dx, relative ? current.dy + y : y);
        path.lineTo(current.dx, current.dy);
        cubicControl = current;
      case 'C':
        final first = point();
        final second = point();
        current = point();
        path.cubicTo(
          first.dx,
          first.dy,
          second.dx,
          second.dy,
          current.dx,
          current.dy,
        );
        cubicControl = second;
        quadraticControl = current;
      case 'S':
        final first = current * 2 - cubicControl;
        final second = point();
        current = point();
        path.cubicTo(
          first.dx,
          first.dy,
          second.dx,
          second.dy,
          current.dx,
          current.dy,
        );
        cubicControl = second;
        quadraticControl = current;
      case 'Q':
        final control = point();
        current = point();
        path.quadraticBezierTo(control.dx, control.dy, current.dx, current.dy);
        quadraticControl = control;
        cubicControl = current;
      case 'T':
        final control = current * 2 - quadraticControl;
        current = point();
        path.quadraticBezierTo(control.dx, control.dy, current.dx, current.dy);
        quadraticControl = control;
        cubicControl = current;
      case 'A':
        final radiusX = scanner.number().abs();
        final radiusY = scanner.number().abs();
        final rotation = scanner.number();
        final largeArc = scanner.flag();
        final clockwise = scanner.flag();
        current = point();
        if (radiusX == 0 || radiusY == 0) {
          path.lineTo(current.dx, current.dy);
        } else {
          path.arcToPoint(
            current,
            radius: Radius.elliptical(radiusX, radiusY),
            rotation: rotation,
            largeArc: largeArc,
            clockwise: clockwise,
          );
        }
        cubicControl = current;
        quadraticControl = current;
      case 'Z':
        path.close();
        current = start;
        cubicControl = current;
        quadraticControl = current;
      default:
        return path;
    }
  }
  return path;
}

class _PathScanner {
  _PathScanner(this._data);

  final String _data;
  int _index = 0;

  static const _separators = ' \t\n\r,';

  void _skip() {
    while (_index < _data.length && _separators.contains(_data[_index])) {
      _index++;
    }
  }

  bool get hasCommand {
    _skip();
    return _index < _data.length && _isLetter(_data.codeUnitAt(_index));
  }

  bool get hasNumber {
    _skip();
    if (_index >= _data.length) return false;
    final code = _data.codeUnitAt(_index);
    return _isDigit(code) || code == _minus || code == _plus || code == _dot;
  }

  /// The next command letter, or null when a coordinate pair repeats one.
  String? command() {
    _skip();
    if (_index >= _data.length) return null;
    if (!_isLetter(_data.codeUnitAt(_index))) return null;
    return _data[_index++];
  }

  double number() {
    _skip();
    final begin = _index;
    if (_index < _data.length &&
        (_data.codeUnitAt(_index) == _minus ||
            _data.codeUnitAt(_index) == _plus)) {
      _index++;
    }
    var seenDot = false;
    while (_index < _data.length) {
      final code = _data.codeUnitAt(_index);
      if (_isDigit(code)) {
        _index++;
      } else if (code == _dot && !seenDot) {
        seenDot = true;
        _index++;
      } else if ((code == 0x65 || code == 0x45) &&
          _index + 1 < _data.length &&
          (_isDigit(_data.codeUnitAt(_index + 1)) ||
              _data.codeUnitAt(_index + 1) == _minus ||
              _data.codeUnitAt(_index + 1) == _plus)) {
        // An exponent: its sign belongs to it, not to the next number.
        _index += 2;
      } else {
        break;
      }
    }
    return double.parse(_data.substring(begin, _index));
  }

  /// Arc flags are one character each and may be packed together.
  bool flag() {
    _skip();
    final value = _data[_index] == '1';
    _index++;
    return value;
  }

  static const _minus = 0x2D;
  static const _plus = 0x2B;
  static const _dot = 0x2E;

  static bool _isDigit(int code) => code >= 0x30 && code <= 0x39;

  static bool _isLetter(int code) =>
      (code >= 0x41 && code <= 0x5A) || (code >= 0x61 && code <= 0x7A);
}

/// Shader used to give a muscle a little volume instead of a flat fill.
ui.Shader muscleShader(Rect bounds, Color color) => ui.Gradient.linear(
  bounds.topCenter,
  bounds.bottomCenter,
  [shade(color, .10), color, shade(color, -.08)],
  const [0, .55, 1],
);

/// Lighten ([amount] > 0) or darken a colour by a share of its lightness.
Color shade(Color color, double amount) {
  final hsl = HSLColor.fromColor(color);
  return hsl.withLightness((hsl.lightness + amount).clamp(0.0, 1.0)).toColor();
}
