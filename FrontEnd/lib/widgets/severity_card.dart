import 'package:flutter/material.dart';
import '../utils/theme.dart';

/// Shows the AI severity result. Per the brief, this must NEVER read as a
/// medical diagnosis — the "AI-assisted" wording is deliberate and required.
class SeverityCard extends StatelessWidget {
  final String severity;
  final double confidence;
  final String? classifierNote;

  const SeverityCard({
    super.key,
    required this.severity,
    required this.confidence,
    this.classifierNote,
  });

  @override
  Widget build(BuildContext context) {
    final color = AppColors.severityColor(severity);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.psychology_alt_outlined, color: AppColors.navy, size: 20),
                const SizedBox(width: 8),
                Text(
                  'AI-ASSISTED EMERGENCY SEVERITY ASSESSMENT',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    color: AppColors.textMuted,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 16),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 18),
              decoration: BoxDecoration(
                color: color.withOpacity(0.12),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: color, width: 1.5),
              ),
              child: Column(
                children: [
                  Text(
                    severity.toUpperCase(),
                    style: TextStyle(
                      fontSize: 26,
                      fontWeight: FontWeight.bold,
                      color: color,
                      letterSpacing: 1,
                    ),
                  ),
                  if (severity != 'Unclassified' && confidence > 0) ...[
                    const SizedBox(height: 4),
                    Text(
                      '${(confidence * 100).toStringAsFixed(0)}% model confidence',
                      style: TextStyle(fontSize: 12, color: AppColors.textMuted),
                    ),
                  ],
                ],
              ),
            ),
            if (classifierNote != null) ...[
              const SizedBox(height: 10),
              Text(
                'Note: $classifierNote',
                style: TextStyle(fontSize: 11, color: AppColors.textMuted, fontStyle: FontStyle.italic),
              ),
            ],
            const SizedBox(height: 10),
            Text(
              'This is an AI-assisted estimate to help prioritize response — '
              'not a medical diagnosis. Responders and hospitals make final clinical decisions.',
              style: TextStyle(fontSize: 11.5, color: AppColors.textMuted, height: 1.4),
            ),
          ],
        ),
      ),
    );
  }
}
