import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';

// ---------- formatting ----------

final _compact = NumberFormat.compact(locale: 'en_IN');
String compact(num n) => _compact.format(n);
String fmtDateTime(DateTime? d) => d == null ? '—' : DateFormat('d MMM, h:mm a').format(d);
String fmtDate(DateTime? d) => d == null ? '—' : DateFormat('d MMM').format(d);
String humanize(String s) => s.replaceAll('_', ' ');

// ---------- status ----------

const _tones = {
  'active': Colors.green, 'onboarding': Colors.blue, 'paused': Colors.grey,
  'new': Colors.blue, 'drafted': Colors.purple, 'approved': Colors.orange, 'published': Colors.green, 'rejected': Colors.grey, 'failed': Colors.red,
  'draft': Colors.grey, 'in_review': Colors.orange, 'scheduled': Colors.blue,
  'positive': Colors.green, 'neutral': Colors.orange, 'negative': Colors.red,
  'todo': Colors.grey, 'in_progress': Colors.blue, 'review': Colors.orange, 'done': Colors.green,
  'low': Colors.grey, 'medium': Colors.orange, 'high': Colors.red,
  'connected': Colors.green, 'expired': Colors.red, 'disconnected': Colors.red,
};

class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key, this.label});
  final String status;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final MaterialColor c = _tones[status] ?? Colors.grey;
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: dark ? c.shade900.withValues(alpha: .5) : c.shade50, borderRadius: BorderRadius.circular(99)),
      child: Text(label ?? humanize(status), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: dark ? c.shade200 : c.shade800)),
    );
  }
}

class Stars extends StatelessWidget {
  const Stars(this.rating, {super.key, this.size = 14});
  final num rating;
  final double size;

  @override
  Widget build(BuildContext context) {
    final n = rating.round();
    return Semantics(
      label: '$n out of 5 stars',
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        for (var i = 0; i < 5; i++) Icon(Icons.star_rounded, size: size, color: i < n ? const Color(0xFFF5A524) : Theme.of(context).dividerColor),
      ]),
    );
  }
}

/// "Dr. Anjali Rao" → "Anjali": skips titles so greetings use the person's name.
String firstName(String full) {
  const titles = {'dr', 'mr', 'mrs', 'ms', 'miss', 'prof', 'shri', 'smt', 'sri'};
  final parts = full.split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
  final name = parts.firstWhere((p) => !titles.contains(p.toLowerCase().replaceAll('.', '')), orElse: () => parts.isEmpty ? '' : parts.first);
  return name;
}

class Delta extends StatelessWidget {
  const Delta(this.pct, {super.key});
  final num pct;

  @override
  Widget build(BuildContext context) {
    // Icons instead of ▲/▼ glyphs, which some fonts (e.g. Flutter web's default) don't have. 0% is not growth.
    final color = pct > 0 ? Colors.green.shade700 : (pct < 0 ? Colors.red.shade700 : Colors.blueGrey);
    final icon = pct > 0 ? Icons.arrow_upward : (pct < 0 ? Icons.arrow_downward : Icons.remove);
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 13, color: color),
      const SizedBox(width: 2),
      Text('${pct.abs()}%', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color)),
    ]);
  }
}

// ---------- layout ----------

class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.label, required this.value, this.hint, this.delta});
  final String label, value;
  final String? hint;
  final num? delta;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(label, style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 2),
          Text(value, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
          if (delta != null) Delta(delta!),
          if (hint != null) Text(hint!, style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
    );
  }
}

class StatGrid extends StatelessWidget {
  const StatGrid({super.key, required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, c) {
      final cols = c.maxWidth > 900 ? 4 : c.maxWidth > 560 ? 3 : 2;
      final w = (c.maxWidth - (cols - 1) * 8) / cols;
      return Wrap(spacing: 8, runSpacing: 8, children: [for (final ch in children) SizedBox(width: w, child: ch)]);
    });
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, required this.child, this.action});
  final String title;
  final Widget child;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600))),
            ?action,
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState(this.message, {super.key});
  final String message;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 32),
        child: Center(child: Text(message, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: Theme.of(context).hintColor))),
      );
}

// ---------- async ----------

/// Loads data with a pull-to-refresh list; shows errors with a retry button.
class AsyncList<T> extends StatefulWidget {
  const AsyncList({super.key, required this.load, required this.builder});
  final Future<T> Function(ApiClient api) load;
  final List<Widget> Function(BuildContext context, T data, VoidCallback reload) builder;

  @override
  State<AsyncList<T>> createState() => AsyncListState<T>();
}

class AsyncListState<T> extends State<AsyncList<T>> {
  late Future<T> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.load(context.read<Session>().api);
  }

  @override
  void didUpdateWidget(covariant AsyncList<T> oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.load != widget.load) reload();
  }

  void reload() => setState(() => _future = widget.load(context.read<Session>().api));

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
        if (snap.hasError) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.cloud_off, size: 40),
                const SizedBox(height: 8),
                Text('${snap.error}', textAlign: TextAlign.center),
                const SizedBox(height: 12),
                FilledButton.tonal(onPressed: reload, child: const Text('Retry')),
              ]),
            ),
          );
        }
        return RefreshIndicator(
          onRefresh: () async => reload(),
          child: ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), children: widget.builder(context, snap.data as T, reload)),
        );
      },
    );
  }
}

/// Runs an API action, showing the server's message on failure. Returns true on success.
Future<bool> runAction(BuildContext context, Future<void> Function(ApiClient api) action, {String? success}) async {
  final messenger = ScaffoldMessenger.of(context);
  try {
    await action(context.read<Session>().api);
    if (success != null) messenger.showSnackBar(SnackBar(content: Text(success)));
    return true;
  } on ApiException catch (e) {
    messenger.showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    return false;
  }
}

// ---------- client picker ----------

class ClientPicker extends StatelessWidget {
  const ClientPicker({super.key, required this.clients, required this.value, required this.onChanged, this.allowAll = true});
  final List<ClientBrief> clients;
  final int? value;
  final ValueChanged<int?> onChanged;
  final bool allowAll;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<int?>(
      initialValue: value,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'Client', isDense: true),
      items: [
        if (allowAll) DropdownMenuItem<int?>(value: null, child: Text('All clients (${clients.length})')),
        for (final c in clients) DropdownMenuItem<int?>(value: c.id, child: Text(c.companyName, overflow: TextOverflow.ellipsis)),
      ],
      onChanged: onChanged,
    );
  }
}

Future<List<ClientBrief>> loadClients(ApiClient api) async =>
    [for (final c in await api.get('/api/clients') as List) ClientBrief.fromJson(c as Map<String, dynamic>)];

// ---------- charts ----------

class ChartSeries {
  const ChartSeries(this.label, this.values, this.color);
  final String label;
  final List<num> values;
  final Color color;
}

class LineChart extends StatelessWidget {
  const LineChart({super.key, required this.series, this.height = 150});
  final List<ChartSeries> series;
  final double height;

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(height: height, width: double.infinity, child: CustomPaint(painter: _LinePainter(series, Theme.of(context).dividerColor))),
      const SizedBox(height: 8),
      Wrap(spacing: 14, children: [
        for (final s in series)
          Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 10, height: 3, color: s.color),
            const SizedBox(width: 4),
            Text(s.label, style: Theme.of(context).textTheme.bodySmall),
          ]),
      ]),
    ]);
  }
}

class _LinePainter extends CustomPainter {
  _LinePainter(this.series, this.grid);
  final List<ChartSeries> series;
  final Color grid;

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (final f in [.25, .5, .75]) {
      canvas.drawLine(Offset(0, size.height * f), Offset(size.width, size.height * f), gridPaint);
    }
    final all = series.expand((s) => s.values);
    if (all.isEmpty) return;
    final mx = math.max(1, all.reduce(math.max)).toDouble();
    for (final s in series) {
      if (s.values.length < 2) continue;
      final p = Path();
      for (var i = 0; i < s.values.length; i++) {
        final x = i / (s.values.length - 1) * size.width;
        final y = size.height - 4 - s.values[i] / mx * (size.height - 8);
        i == 0 ? p.moveTo(x, y) : p.lineTo(x, y);
      }
      canvas.drawPath(
          p,
          Paint()
            ..color = s.color
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2
            ..strokeJoin = StrokeJoin.round);
    }
  }

  @override
  bool shouldRepaint(covariant _LinePainter old) => old.series != series;
}

class BarList extends StatelessWidget {
  const BarList(this.rows, {super.key});
  final List<(String, num)> rows;

  @override
  Widget build(BuildContext context) {
    final mx = rows.isEmpty ? 1 : math.max(1, rows.map((r) => r.$2).reduce(math.max));
    return Column(children: [
      for (final (label, v) in rows)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            SizedBox(width: 130, child: Text(label, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13))),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(value: v / mx, minHeight: 8, backgroundColor: Theme.of(context).dividerColor.withValues(alpha: .4)),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(width: 56, child: Text(NumberFormat.decimalPattern('en_IN').format(v), textAlign: TextAlign.right, style: const TextStyle(fontSize: 12))),
          ]),
        ),
    ]);
  }
}
