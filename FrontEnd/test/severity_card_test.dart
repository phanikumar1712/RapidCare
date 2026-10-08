import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:rapidcare_app/utils/theme.dart';
import 'package:rapidcare_app/widgets/severity_card.dart';

void main() {
  Widget wrap(Widget child) =>
      MaterialApp(home: Scaffold(body: child));

  group('SeverityCard', () {
    testWidgets('hides the confidence line when confidence is 0 '
        '(old backend default — must not show "0% model confidence")',
        (tester) async {
      await tester.pumpWidget(
          wrap(const SeverityCard(severity: 'High', confidence: 0.0)));
      expect(find.text('HIGH'), findsOneWidget);
      expect(find.textContaining('% model confidence'), findsNothing);
    });

    testWidgets('shows the real model confidence when provided',
        (tester) async {
      await tester.pumpWidget(
          wrap(const SeverityCard(severity: 'Medium-High', confidence: 0.6)));
      expect(find.text('MEDIUM-HIGH'), findsOneWidget);
      expect(find.text('60% model confidence'), findsOneWidget);
    });

    testWidgets('never shows confidence for Unclassified', (tester) async {
      await tester.pumpWidget(
          wrap(const SeverityCard(severity: 'Unclassified', confidence: 0.0)));
      expect(find.text('UNCLASSIFIED'), findsOneWidget);
      expect(find.textContaining('% model confidence'), findsNothing);
    });
  });

  group('severityColor covers every label the backend emits', () {
    const unclassified = null; // resolve via default branch
    test('all five backend labels are colored, not grey', () {
      for (final label in ['High', 'Medium-High', 'Medium', 'Low-Medium', 'Low']) {
        expect(
          AppColors.severityColor(label),
          isNot(AppColors.severityColor(unclassified)),
          reason: '$label must not fall back to the unclassified grey',
        );
      }
    });

    test('ordering: higher severity is not greener than lower', () {
      expect(AppColors.severityColor('Low'), AppColors.sevLow);
      expect(AppColors.severityColor('Medium-High'), AppColors.sevHigh);
      expect(AppColors.severityColor('Low-Medium'), AppColors.sevMedium);
    });
  });
}
