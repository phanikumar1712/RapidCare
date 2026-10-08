// Smoke test for the RapidCare home screen.
//
// The original template test referenced `MyApp` (never existed in this
// project) and a counter UI this app doesn't have, so `flutter analyze` and
// `flutter test` always failed. This version verifies the screen that actually
// ships.

import 'package:flutter_test/flutter_test.dart';

import 'package:rapidcare_app/main.dart';

void main() {
  testWidgets('Home screen renders with branding and the SOS button',
      (WidgetTester tester) async {
    await tester.pumpWidget(const RapidCareApp());
    await tester.pump();

    expect(find.text('RapidCare'), findsOneWidget);
    expect(find.text('Emergency Assistance'), findsOneWidget);
    expect(find.text('SOS'), findsOneWidget);
    expect(find.text('Services Online'), findsOneWidget);
  });
}
