import 'package:flutter/material.dart';

// Calmap's visual language is intentionally warm and restrained.  The aliases
// below are kept because screens use them directly, while the actual palette is
// defined as a small semantic system rather than one beige + one green.
const cream = Color(0xFFF4F1EA);
const warmWhite = Color(0xFFFCFBF7);
const olive = Color(0xFF244B3C);
const ink = Color(0xFF17231E);

const forest = Color(0xFF173D31);
const forestSoft = Color(0xFF315E4D);
const sage = Color(0xFFDDE7DC);
const sageLight = Color(0xFFEDF2EB);
const champagne = Color(0xFFC8A977);
const sand = Color(0xFFE9E3D8);
const line = Color(0xFFE3DED4);
const mutedInk = Color(0xFF68716C);

ThemeData buildTheme() {
  const scheme = ColorScheme.light(
    primary: olive,
    onPrimary: Color(0xFFFFFEFA),
    primaryContainer: sage,
    onPrimaryContainer: ink,
    secondary: champagne,
    onSecondary: ink,
    secondaryContainer: Color(0xFFF1E7D5),
    onSecondaryContainer: ink,
    surface: warmWhite,
    onSurface: ink,
    error: Color(0xFFA2413B),
    outline: line,
    outlineVariant: Color(0xFFEEEAE2),
    shadow: Color(0x1A183A2F),
  );

  const textTheme = TextTheme(
    displayLarge: TextStyle(
      fontSize: 42,
      height: 1.04,
      fontWeight: FontWeight.w600,
      letterSpacing: -1.5,
      color: ink,
    ),
    displayMedium: TextStyle(
      fontSize: 36,
      height: 1.08,
      fontWeight: FontWeight.w600,
      letterSpacing: -1.1,
      color: ink,
    ),
    headlineLarge: TextStyle(
      fontSize: 30,
      height: 1.12,
      fontWeight: FontWeight.w600,
      letterSpacing: -.7,
      color: ink,
    ),
    headlineMedium: TextStyle(
      fontSize: 25,
      height: 1.16,
      fontWeight: FontWeight.w600,
      letterSpacing: -.4,
      color: ink,
    ),
    titleLarge: TextStyle(
      fontSize: 21,
      height: 1.22,
      fontWeight: FontWeight.w600,
      letterSpacing: -.25,
      color: ink,
    ),
    titleMedium: TextStyle(
      fontSize: 17,
      height: 1.3,
      fontWeight: FontWeight.w600,
      color: ink,
    ),
    bodyLarge: TextStyle(fontSize: 16, height: 1.45, color: ink),
    bodyMedium: TextStyle(fontSize: 14, height: 1.42, color: ink),
    bodySmall: TextStyle(fontSize: 12, height: 1.35, color: mutedInk),
    labelLarge: TextStyle(
      fontSize: 15,
      height: 1.2,
      fontWeight: FontWeight.w600,
      letterSpacing: .05,
    ),
    labelMedium: TextStyle(
      fontSize: 12,
      height: 1.2,
      fontWeight: FontWeight.w600,
      letterSpacing: .25,
    ),
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: cream,
    textTheme: textTheme,
    primaryTextTheme: textTheme,
    dividerColor: line,
    splashColor: sage.withValues(alpha: .55),
    highlightColor: sage.withValues(alpha: .25),
    appBarTheme: const AppBarTheme(
      backgroundColor: cream,
      foregroundColor: ink,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(
        color: ink,
        fontSize: 20,
        fontWeight: FontWeight.w600,
        letterSpacing: -.2,
      ),
    ),
    cardTheme: CardThemeData(
      color: warmWhite,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 5),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(20),
        side: const BorderSide(color: line, width: .8),
      ),
      shadowColor: const Color(0x14173D31),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: warmWhite,
      labelStyle: const TextStyle(color: mutedInk, fontSize: 14),
      floatingLabelStyle: const TextStyle(
        color: olive,
        fontSize: 13,
        fontWeight: FontWeight.w600,
      ),
      hintStyle: const TextStyle(color: Color(0xFF9A9F9B)),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: olive, width: 1.4),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: Color(0xFFA2413B)),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 17, vertical: 17),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: olive,
        foregroundColor: Colors.white,
        disabledBackgroundColor: const Color(0xFFADB8B2),
        minimumSize: const Size.fromHeight(56),
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 16),
        textStyle: const TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          letterSpacing: .1,
        ),
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: olive,
        minimumSize: const Size.fromHeight(52),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        side: const BorderSide(color: Color(0xFFB8C2BC)),
        textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: olive,
        textStyle: const TextStyle(fontWeight: FontWeight.w600),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        foregroundColor: ink,
        backgroundColor: warmWhite,
        minimumSize: const Size(44, 44),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: line),
        ),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: warmWhite,
      selectedColor: sage,
      side: const BorderSide(color: line),
      labelStyle: const TextStyle(color: ink, fontWeight: FontWeight.w500),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? olive : warmWhite,
      ),
      side: const BorderSide(color: Color(0xFF9EA7A1), width: 1.5),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: olive,
      linearTrackColor: sage,
      circularTrackColor: sage,
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: ButtonStyle(
        foregroundColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected) ? ink : mutedInk,
        ),
        backgroundColor: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected) ? sage : warmWhite,
        ),
        side: const WidgetStatePropertyAll(BorderSide(color: line)),
        textStyle: const WidgetStatePropertyAll(
          TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
        shape: WidgetStatePropertyAll(
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: warmWhite,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shadowColor: Colors.transparent,
      indicatorColor: sage,
      indicatorShape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
      ),
      height: 76,
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          color: states.contains(WidgetState.selected) ? olive : mutedInk,
          size: states.contains(WidgetState.selected) ? 24 : 23,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          color: states.contains(WidgetState.selected) ? ink : mutedInk,
          fontSize: 11,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w700
              : FontWeight.w500,
        ),
      ),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: warmWhite,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      dragHandleColor: Color(0xFFC7C2B9),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: warmWhite,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
      titleTextStyle: textTheme.headlineMedium,
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: ink,
      contentTextStyle: const TextStyle(color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    datePickerTheme: const DatePickerThemeData(
      backgroundColor: warmWhite,
      surfaceTintColor: Colors.transparent,
      headerBackgroundColor: forest,
      headerForegroundColor: Colors.white,
    ),
  );
}

class ScreenHeading extends StatelessWidget {
  const ScreenHeading({
    required this.title,
    this.subtitle,
    this.trailing,
    super.key,
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.headlineLarge),
            if (subtitle != null) ...[
              const SizedBox(height: 5),
              Text(
                subtitle!,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: mutedInk),
              ),
            ],
          ],
        ),
      ),
      ?trailing,
    ],
  );
}

class AccentIconTile extends StatelessWidget {
  const AccentIconTile(
    this.icon, {
    this.dark = false,
    this.size = 48,
    super.key,
  });

  final IconData icon;
  final bool dark;
  final double size;

  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      color: dark ? Colors.white.withValues(alpha: .1) : sageLight,
      borderRadius: BorderRadius.circular(size * .32),
      border: dark
          ? Border.all(color: Colors.white.withValues(alpha: .08))
          : Border.all(color: line),
    ),
    child: Icon(
      icon,
      color: dark ? const Color(0xFFE7D4AB) : olive,
      size: size * .46,
    ),
  );
}

/// Full-screen route for tab-style screens (profile, diary, assistant) that are
/// built without their own Scaffold: adds the Material surface and a back button.
class SubPage extends StatelessWidget {
  const SubPage({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      backgroundColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      toolbarHeight: 44,
    ),
    body: child,
  );
}
