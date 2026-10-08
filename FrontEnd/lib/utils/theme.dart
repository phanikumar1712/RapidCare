import 'package:flutter/material.dart';

/// Palette: white/light base, navy for trust/secondary elements,
/// red for emergency/SOS accents. Deliberately restrained — this is a
/// panel-demo app, not a design showcase, so clarity beats flourish.
class AppColors {
  static const Color emergencyRed = Color(0xFFD32F2F);
  static const Color emergencyRedDark = Color(0xFFB71C1C);
  static const Color navy = Color(0xFF0B2545);
  static const Color navyLight = Color(0xFF13315C);
  static const Color background = Color(0xFFF7F9FB);
  static const Color cardWhite = Color(0xFFFFFFFF);
  static const Color textPrimary = Color(0xFF1A1A1A);
  static const Color textMuted = Color(0xFF6B7280);

  // Severity colors — used consistently across severity_card and history
  static const Color sevLow = Color(0xFF2E7D32);
  static const Color sevMedium = Color(0xFFF9A825);
  static const Color sevHigh = Color(0xFFEF6C00);
  static const Color sevCritical = Color(0xFFC62828);
  static const Color sevUnclassified = Color(0xFF9E9E9E);

  static Color severityColor(String? severity) {
    switch (severity) {
      case 'Low':
        return sevLow;
      case 'Low-Medium':
        // The backend's 5-level scale also emits Low-Medium / Medium-High;
        // without these the severity card rendered grey (unclassified).
        return sevMedium;
      case 'Medium':
        return sevMedium;
      case 'Medium-High':
        return sevHigh;
      case 'High':
        return sevHigh;
      case 'Critical':
        return sevCritical;
      default:
        return sevUnclassified;
    }
  }
}

ThemeData buildAppTheme() {
  return ThemeData(
    useMaterial3: true,
    scaffoldBackgroundColor: AppColors.background,
    colorScheme: ColorScheme.fromSeed(
      seedColor: AppColors.navy,
      primary: AppColors.navy,
      secondary: AppColors.emergencyRed,
      surface: AppColors.cardWhite,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.navy,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: true,
    ),
    cardTheme: CardThemeData(
      color: AppColors.cardWhite,
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      margin: const EdgeInsets.symmetric(vertical: 8),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.cardWhite,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: Colors.grey.shade300),
      ),
      contentPadding: const EdgeInsets.all(16),
    ),
    textTheme: const TextTheme(
      headlineMedium: TextStyle(fontWeight: FontWeight.bold, color: AppColors.textPrimary),
      titleLarge: TextStyle(fontWeight: FontWeight.w700, color: AppColors.textPrimary),
      bodyMedium: TextStyle(color: AppColors.textPrimary),
    ),
  );
}
