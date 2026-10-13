import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../core/theme.dart';
import 'anatomy.dart';

/// Front and back anatomical map of a workout.  The figure follows the user's
/// profile sex, muscles are shaded by how much of the session's volume they
/// carried, and tapping either the figure or a chip explains a single muscle.
class WorkoutMuscleSummary extends StatefulWidget {
  const WorkoutMuscleSummary({
    required this.loads,
    required this.bodySex,
    super.key,
  });

  final Map<String, int> loads;
  final String bodySex;

  @override
  State<WorkoutMuscleSummary> createState() => _WorkoutMuscleSummaryState();
}

class _WorkoutMuscleSummaryState extends State<WorkoutMuscleSummary> {
  String? _selected;

  void _select(String? muscle) {
    if (muscle == _selected) {
      setState(() => _selected = null);
      return;
    }
    setState(() => _selected = muscle);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final female = widget.bodySex == 'female';
    final ranked = widget.loads.entries.where((entry) => entry.value > 0).toList()
      ..sort((left, right) {
        final byValue = right.value.compareTo(left.value);
        return byValue != 0 ? byValue : left.key.compareTo(right.key);
      });
    final maximum = ranked.isEmpty ? 1 : ranked.first.value;
    final onMap = ranked.where((entry) => anatomyMuscles.contains(entry.key));

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.accessibility_new_rounded, color: olive),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Карта мышц тренировки',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: sageLight,
                    borderRadius: BorderRadius.circular(9),
                    border: Border.all(color: line),
                  ),
                  child: Text(
                    female ? 'женское тело' : 'мужское тело',
                    style: const TextStyle(fontSize: 11, color: mutedInk),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              'Основная мышца упражнения ×2, вспомогательная ×1. '
              'Чем насыщеннее цвет, тем больше нагрузка за день.',
              style: theme.textTheme.bodySmall?.copyWith(color: mutedInk),
            ),
            const SizedBox(height: 12),
            LayoutBuilder(
              builder: (context, constraints) => SizedBox(
                // Two figures side by side, each as tall as its own model is
                // relative to its width, so no dead space is left over.
                height: (constraints.maxWidth / 2 * anatomyAspect(female))
                    .clamp(280.0, 430.0),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final view in AnatomyView.values)
                      Expanded(
                        child: _AnatomyFigure(
                          loads: widget.loads,
                          maximum: maximum,
                          female: female,
                          view: view,
                          selected: _selected,
                          onSelect: _select,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            _Readout(
              selected: _selected,
              loads: widget.loads,
              maximum: maximum,
              empty: ranked.isEmpty,
            ),
            const SizedBox(height: 12),
            _LoadScale(maximum: maximum),
            if (onMap.isNotEmpty) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 7,
                runSpacing: 7,
                children: [
                  for (final entry in onMap.take(8))
                    _LoadChip(
                      name: entry.key,
                      value: entry.value,
                      maximum: maximum,
                      selected: entry.key == _selected,
                      onTap: () => _select(entry.key),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// One figure — front or back — with its caption.
class _AnatomyFigure extends StatelessWidget {
  const _AnatomyFigure({
    required this.loads,
    required this.maximum,
    required this.female,
    required this.view,
    required this.selected,
    required this.onSelect,
  });

  final Map<String, int> loads;
  final int maximum;
  final bool female;
  final AnatomyView view;
  final String? selected;
  final ValueChanged<String?> onSelect;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Expanded(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final size = Size(constraints.maxWidth, constraints.maxHeight);
            final layout = AnatomyLayout.resolve(
              size: size,
              female: female,
              view: view,
            );
            return GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTapUp: (details) {
                final region = layout.regionAt(details.localPosition);
                final muscle = region?.labelFrom(loads);
                onSelect(muscle != null && loads.containsKey(muscle)
                    ? muscle
                    : null);
              },
              child: CustomPaint(
                size: size,
                painter: _AnatomyPainter(
                  layout: layout,
                  loads: loads,
                  maximum: maximum,
                  selected: selected,
                ),
              ),
            );
          },
        ),
      ),
      const SizedBox(height: 6),
      Text(
        view == AnatomyView.front ? 'спереди' : 'сзади',
        style: Theme.of(
          context,
        ).textTheme.labelMedium?.copyWith(color: mutedInk),
      ),
    ],
  );
}

class _AnatomyPainter extends CustomPainter {
  const _AnatomyPainter({
    required this.layout,
    required this.loads,
    required this.maximum,
    required this.selected,
  });

  final AnatomyLayout layout;
  final Map<String, int> loads;
  final int maximum;
  final String? selected;

  @override
  void paint(Canvas canvas, Size size) {
    for (final region in layout.regions) {
      _paintRegion(canvas, region);
    }
    if (selected == null) return;
    for (final region in layout.regions) {
      if (!region.muscles.contains(selected)) continue;
      canvas.drawPath(
        region.path,
        Paint()
          ..color = ink.withValues(alpha: .85)
          ..style = PaintingStyle.stroke
          ..strokeWidth = math.max(1.2, layout.unit * 4)
          ..strokeJoin = StrokeJoin.round,
      );
    }
  }

  void _paintRegion(Canvas canvas, AnatomyRegion region) {
    final bounds = region.path.getBounds();
    if (bounds.isEmpty) return;
    final value = region.loadFrom(loads);
    if (value <= 0) {
      canvas.drawPath(
        region.path,
        Paint()..color = _restingColor(region.slug),
      );
      return;
    }
    final color = _loadColor(value, maximum);
    canvas.drawPath(region.path, Paint()..shader = muscleShader(bounds, color));
    canvas.drawPath(
      region.path,
      Paint()
        ..color = shade(color, -.14)
        ..style = PaintingStyle.stroke
        ..strokeWidth = math.max(.5, layout.unit * 1.6),
    );
  }

  /// Hair reads as hair, the skin parts sit a shade lighter than muscle so the
  /// figure still looks like a body when nothing is worked.
  Color _restingColor(String slug) => switch (slug) {
    'hair' => _hair,
    'head' || 'hands' || 'feet' || 'knees' || 'ankles' => _skin,
    _ => _restingFill,
  };

  @override
  bool shouldRepaint(covariant _AnatomyPainter old) =>
      old.layout != layout ||
      old.selected != selected ||
      old.maximum != maximum ||
      !mapEquals(old.loads, loads);
}

/// A muscle at rest keeps the body's own tone; worked muscles run from
/// champagne through terracotta to the palette's deep red.
const _skin = Color(0xFFE2DDD0);
const _restingFill = Color(0xFFD3CDBD);
const _hair = Color(0xFF8D8676);

const _ramp = <Color>[
  Color(0xFFEBD5A6),
  Color(0xFFE2A96A),
  Color(0xFFCE6B45),
  Color(0xFFA2413B),
];

/// Colour for a load on the day's 0..[maximum] scale.
Color _loadColor(int value, int maximum) {
  final ratio = maximum <= 0 ? 0.0 : (value / maximum).clamp(0.0, 1.0);
  return _rampColor(.14 + .86 * ratio);
}

Color _rampColor(double t) {
  final position = t.clamp(0.0, 1.0) * (_ramp.length - 1);
  final index = position.floor().clamp(0, _ramp.length - 2);
  return Color.lerp(_ramp[index], _ramp[index + 1], position - index)!;
}

/// Explains the currently selected muscle, or nudges the user to tap one.
class _Readout extends StatelessWidget {
  const _Readout({
    required this.selected,
    required this.loads,
    required this.maximum,
    required this.empty,
  });

  final String? selected;
  final Map<String, int> loads;
  final int maximum;
  final bool empty;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (empty) {
      return Text(
        'Сегодня нагрузка не размечена по мышцам.',
        style: theme.textTheme.bodySmall?.copyWith(color: mutedInk),
      );
    }
    if (selected == null) {
      return Row(
        children: [
          const Icon(Icons.touch_app_outlined, size: 15, color: mutedInk),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              'Коснитесь мышцы, чтобы увидеть её долю в тренировке.',
              style: theme.textTheme.bodySmall?.copyWith(color: mutedInk),
            ),
          ),
        ],
      );
    }
    final value = loads[selected] ?? 0;
    final views = anatomyViewsOf(selected!);
    final side = views.length == 2
        ? 'спереди и сзади'
        : views.contains(AnatomyView.front)
        ? 'спереди'
        : 'сзади';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: sageLight,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: line),
      ),
      child: Row(
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(
              color: _loadColor(value, maximum),
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Text(
              selected!,
              style: theme.textTheme.labelLarge?.copyWith(color: ink),
            ),
          ),
          Text(
            '$value из $maximum · $side',
            style: theme.textTheme.bodySmall?.copyWith(color: mutedInk),
          ),
        ],
      ),
    );
  }
}

/// Gradient legend tying colour back to the load numbers.
class _LoadScale extends StatelessWidget {
  const _LoadScale({required this.maximum});

  final int maximum;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(
      context,
    ).textTheme.bodySmall?.copyWith(color: mutedInk, fontSize: 11);
    return Row(
      children: [
        Text('не задействована', style: style),
        const SizedBox(width: 8),
        Container(
          width: 14,
          height: 8,
          decoration: BoxDecoration(
            color: _restingFill,
            borderRadius: BorderRadius.circular(4),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Container(
            height: 8,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(4),
              gradient: LinearGradient(
                colors: [for (final color in _ramp) color],
              ),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text('$maximum', style: style),
      ],
    );
  }
}

class _LoadChip extends StatelessWidget {
  const _LoadChip({
    required this.name,
    required this.value,
    required this.maximum,
    required this.selected,
    required this.onTap,
  });

  final String name;
  final int value;
  final int maximum;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = _loadColor(value, maximum);
    return Material(
      color: selected ? color.withValues(alpha: .22) : warmWhite,
      borderRadius: BorderRadius.circular(11),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(11),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(11),
            border: Border.all(color: selected ? shade(color, -.12) : line),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 7),
              Text(
                '$name · $value',
                style: const TextStyle(fontSize: 12, color: ink),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
