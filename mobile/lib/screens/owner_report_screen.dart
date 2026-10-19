import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import 'ai_post/shared.dart';

const _blue = Color(0xFF4169E1);
const _target = Color(0xFFC8D2F5);

/// Report (business owners): the month's Performance Summary against the month before, then the Growth Action Report
/// (what was done against the targets) or the Performance Report (12-month trends), and Download as PDF.
class OwnerReportScreen extends StatefulWidget {
  const OwnerReportScreen({super.key, required this.clientId});
  final int clientId;

  /// Opens the PDF link; replaceable in tests.
  static Future<bool> Function(Uri url) openUrl = (url) => launchUrl(url, mode: LaunchMode.externalApplication);

  @override
  State<OwnerReportScreen> createState() => _OwnerReportScreenState();
}

class _OwnerReportScreenState extends State<OwnerReportScreen> {
  Map<String, dynamic>? _d;
  String? _error, _month;
  bool _performance = false, _downloading = false;
  final _growthPeriod = <String, String>{};
  final _trendPeriod = <String, int>{};

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}/monthly-report';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await _api.get(_base, {'month': ?_month}) as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _d = d;
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _download() async {
    setState(() => _downloading = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final link = await _api.post('$_base/link${_month == null ? '' : '?month=$_month'}') as Map<String, dynamic>;
      final ok = await OwnerReportScreen.openUrl(Uri.parse(link['url'] as String));
      messenger.showSnackBar(SnackBar(
        content: Text(ok ? 'Report downloaded — ${link['filename']}' : 'Couldn’t open the report on this phone'),
        backgroundColor: ok ? green : Colors.red.shade700,
      ));
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _downloading = false);
    }
  }

  Future<void> _pickMonth() async {
    final now = DateTime.now();
    final months = [for (var i = 1; i <= 12; i++) DateTime(now.year, now.month - i)];
    final picked = await showModalBottomSheet<DateTime>(
      context: context,
      showDragHandle: true,
      builder: (s) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          for (final m in months)
            ListTile(
              key: Key('month-${DateFormat('yyyy-MM').format(m)}'),
              title: Text('${DateFormat('MMMM yyyy').format(m)} report'),
              trailing: _d?['month'] == DateFormat('yyyy-MM').format(m) ? const Icon(Icons.check, color: green) : null,
              onTap: () => Navigator.pop(s, m),
            ),
        ]),
      ),
    );
    if (picked == null) return;
    setState(() {
      _month = DateFormat('yyyy-MM').format(picked);
      _d = null;
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    return Scaffold(
      appBar: navyBar('Report', subtitle: context.read<Session>().me!.clientName, actions: [
        Padding(
          padding: const EdgeInsets.only(right: 10),
          child: OutlinedButton.icon(
            key: const Key('report-download'),
            style: OutlinedButton.styleFrom(foregroundColor: Colors.white, side: const BorderSide(color: Colors.white70), shape: const StadiumBorder(),
                visualDensity: VisualDensity.compact),
            onPressed: d == null || _downloading ? null : _download,
            icon: _downloading
                ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.download, size: 18),
            label: const Text('Download'),
          ),
        ),
      ]),
      body: d == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(key: const Key('report-list'), padding: const EdgeInsets.fromLTRB(12, 14, 12, 24), children: [
                InkWell(
                  key: const Key('report-month'),
                  onTap: _pickMonth,
                  child: Text.rich(
                    TextSpan(children: [
                      TextSpan(text: '${d['month_label']} Performance Summary ', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                      TextSpan(text: '(vs ${d['previous_label']})', style: const TextStyle(fontSize: 13, color: Colors.black54)),
                      const WidgetSpan(alignment: PlaceholderAlignment.middle, child: Icon(Icons.expand_more, size: 20, color: Colors.black54)),
                    ]),
                  ),
                ),
                const SizedBox(height: 10),
                _SummaryGrid(tiles: (d['summary'] as List).cast<Map<String, dynamic>>()),
                const SizedBox(height: 14),
                Row(children: [
                  Expanded(child: _Toggle(key: const Key('tab-growth'), label: 'Growth Action Report', on: !_performance,
                      onTap: () => setState(() => _performance = false))),
                  const SizedBox(width: 8),
                  Expanded(child: _Toggle(key: const Key('tab-performance'), label: 'Performance Report', on: _performance,
                      onTap: () => setState(() => _performance = true))),
                ]),
                const SizedBox(height: 8),
                if (!_performance)
                  for (final g in (d['growth'] as List).cast<Map<String, dynamic>>()) _growth(g)
                else
                  for (final t in (d['trends'] as List).cast<Map<String, dynamic>>()) _trend(t),
              ]),
            ),
    );
  }

  static const _growthLabels = {'last_month': 'Last Month', '3m': 'Last 3 Months', '6m': 'Last 6 Months', '12m': 'Last 12 Months'};

  Widget _growth(Map<String, dynamic> g) {
    final key = g['key'] as String;
    final period = _growthPeriod[key] ?? 'last_month';
    final rows = ((g['periods'] as Map)[period] as List).cast<Map<String, dynamic>>();
    return _Section(
      title: g['label'] as String,
      filter: _Filter(
        key: Key('filter-$key'),
        value: period,
        options: _growthLabels,
        onChanged: (v) => setState(() => _growthPeriod[key] = v),
      ),
      child: Column(children: [
        const _Legend(),
        const SizedBox(height: 8),
        _Scrollable(width: math.max(1, rows.length) * 56.0, child: CustomPaint(painter: _BarsPainter(rows), size: const Size.fromHeight(220))),
      ]),
    );
  }

  Widget _trend(Map<String, dynamic> t) {
    final key = t['key'] as String;
    final n = _trendPeriod[key] ?? 6;
    final points = (t['points'] as List).cast<Map<String, dynamic>>();
    final shown = points.sublist(points.length - n);
    final empty = !shown.any((p) => p['value'] != null && p['value'] != 0);
    return _Section(
      title: t['label'] as String,
      filter: _Filter(
        key: Key('filter-$key'),
        value: '$n',
        options: const {'6': 'Last 6 Months', '12': 'Last 12 Months'},
        onChanged: (v) => setState(() => _trendPeriod[key] = int.parse(v)),
      ),
      child: empty
          ? _NoHistory(score: key == 'score')
          : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              _Scrollable(
                width: shown.length * 58.0,
                child: CustomPaint(painter: _TrendPainter(shown, unit: t['unit'] as String), size: const Size.fromHeight(200)),
              ),
              const SizedBox(height: 10),
              Container(
                key: Key('insight-$key'),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: _blue, borderRadius: BorderRadius.circular(12)),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.lightbulb, color: Color(0xFFFFD60A), size: 20),
                  const SizedBox(width: 8),
                  Expanded(child: Text(t['insight'] as String, style: const TextStyle(color: Colors.white, fontSize: 13, height: 1.35))),
                ]),
              ),
            ]),
    );
  }
}

/// Three rows of tiles that scroll sideways together, with a progress bar under them.
class _SummaryGrid extends StatefulWidget {
  const _SummaryGrid({required this.tiles});
  final List<Map<String, dynamic>> tiles;

  @override
  State<_SummaryGrid> createState() => _SummaryGridState();
}

class _SummaryGridState extends State<_SummaryGrid> {
  final _c = ScrollController();
  double _progress = 0;

  @override
  void initState() {
    super.initState();
    _c.addListener(() {
      final max = _c.position.maxScrollExtent;
      setState(() => _progress = max <= 0 ? 1 : _c.offset / max);
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  static IconData _icon(String key) => switch (key) {
        'views' => Icons.visibility_outlined,
        'leads' => Icons.groups_outlined,
        'calls' => Icons.call_outlined,
        'directions' => Icons.place_outlined,
        'media' => Icons.photo_outlined,
        'engagement' => Icons.thumb_up_alt_outlined,
        'replies' => Icons.chat_bubble_outline,
        'posts' => Icons.article_outlined,
        _ => Icons.language,
      };

  @override
  Widget build(BuildContext context) {
    final rows = [for (var i = 0; i < widget.tiles.length; i += 3) widget.tiles.sublist(i, math.min(i + 3, widget.tiles.length))];
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      SingleChildScrollView(
        key: const Key('summary-scroll'),
        controller: _c,
        scrollDirection: Axis.horizontal,
        child: Column(children: [
          for (final row in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(children: [for (final t in row) _tile(t)]),
            ),
        ]),
      ),
      ClipRRect(
        borderRadius: BorderRadius.circular(4),
        child: LinearProgressIndicator(value: 0.45 + 0.55 * _progress, minHeight: 4, color: Colors.black26, backgroundColor: Colors.black12),
      ),
    ]);
  }

  Widget _tile(Map<String, dynamic> t) {
    final ch = (t['change_pct'] as num).toDouble();
    final colour = ch > 0 ? green : ch < 0 ? red : Colors.black45;
    final v = t['value'] as num;
    final value = t['unit'] == '%' ? '${v.toStringAsFixed(1)}%' : NumberFormat.decimalPattern('en_IN').format(v);
    return Container(
      key: Key('tile-${t['key']}'),
      width: 158,
      margin: const EdgeInsets.only(right: 8),
      padding: const EdgeInsets.fromLTRB(10, 10, 8, 10),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFE3E8EF))),
      child: Row(children: [
        CircleAvatar(radius: 16, backgroundColor: const Color(0xFFEAF0FB), child: Icon(_icon(t['key'] as String), size: 17, color: _blue)),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(t['label'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11.5, color: Colors.black54)),
            Row(children: [
              Flexible(child: Text(value, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800))),
              const SizedBox(width: 4),
              if (ch != 0) Icon(ch > 0 ? Icons.arrow_drop_up : Icons.arrow_drop_down, color: colour, size: 18) else const SizedBox(width: 4),
              Text('${ch.abs().toStringAsFixed(1)}%', style: TextStyle(fontSize: 10.5, color: colour)),
            ]),
          ]),
        ),
      ]),
    );
  }
}

class _Toggle extends StatelessWidget {
  const _Toggle({super.key, required this.label, required this.on, required this.onTap});
  final String label;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: on ? const Color(0xFFE6ECFB) : Colors.white,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: on ? const Color(0xFFC8D2F5) : const Color(0xFFE3E8EF)),
          ),
          child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 13, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? navy : Colors.black54)),
        ),
      );
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.filter, required this.child});
  final String title;
  final Widget filter, child;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
            filter,
          ]),
          const SizedBox(height: 10),
          child,
        ]),
      );
}

class _Filter extends StatelessWidget {
  const _Filter({super.key, required this.value, required this.options, required this.onChanged});
  final String value;
  final Map<String, String> options;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => PopupMenuButton<String>(
        tooltip: 'Date Filters',
        initialValue: value,
        onSelected: onChanged,
        itemBuilder: (_) => [
          const PopupMenuItem<String>(enabled: false, height: 32, child: Text('Date Filters', style: TextStyle(fontWeight: FontWeight.w700, color: Colors.black87))),
          for (final e in options.entries)
            PopupMenuItem<String>(
              value: e.key,
              child: Row(children: [
                Expanded(child: Text(e.value)),
                Icon(e.key == value ? Icons.radio_button_checked : Icons.radio_button_off, size: 18, color: e.key == value ? navy : Colors.black38),
              ]),
            ),
        ],
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.filter_alt_outlined, size: 16, color: red),
          const SizedBox(width: 3),
          Text(options[value]!, style: const TextStyle(fontSize: 12.5, color: Colors.black87)),
        ]),
      );
}

class _Legend extends StatelessWidget {
  const _Legend();

  @override
  Widget build(BuildContext context) {
    Widget dot(Color c, String t) => Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 10, height: 10, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
          const SizedBox(width: 5),
          Text(t, style: const TextStyle(fontSize: 12, color: Colors.black54)),
        ]);
    return Row(mainAxisAlignment: MainAxisAlignment.center, children: [dot(_target, 'Target'), const SizedBox(width: 16), dot(_blue, 'Achieved')]);
  }
}

/// Fills the width, and scrolls sideways when the chart needs more room (12 months).
class _Scrollable extends StatelessWidget {
  const _Scrollable({required this.width, required this.child});
  final double width;
  final Widget child;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
        builder: (context, box) => SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: SizedBox(width: math.max(box.maxWidth, width), child: child),
        ),
      );
}

class _NoHistory extends StatelessWidget {
  const _NoHistory({required this.score});
  final bool score;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Column(children: [
          const CircleAvatar(radius: 30, backgroundColor: Color(0xFFEAF0FB), child: Icon(Icons.speed, color: _blue, size: 30)),
          const SizedBox(height: 12),
          Text(score ? 'No score history yet' : 'No history yet', style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          const SizedBox(height: 6),
          Text(
            score ? 'Your Marketing Score is calculated every Monday. The first point lands next week.' : 'This fills in as the months go by.',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.black54),
          ),
        ]),
      );
}

// (on the web every number is a double, so whole numbers are detected by value, not by type)
String _short(num v) => v >= 1000 ? '${(v / 1000).toStringAsFixed(v >= 10000 ? 0 : 1)}k' : (v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(1));

/// A tidy gridline step (1, 2 or 5 × 10^n) so 4 steps reach at least [max].
double _niceStep(num max) {
  final raw = math.max(max, 1) / 4;
  final mag = math.pow(10, (math.log(raw) / math.ln10).floor()).toDouble();
  return [1, 2, 5, 10].map((m) => m * mag).firstWhere((s) => s >= raw);
}

TextPainter _label(String s, double size, Color c) =>
    TextPainter(text: TextSpan(text: s, style: TextStyle(fontSize: size, color: c)), textDirection: TextDirection.ltr)..layout();

/// Target (light) and achieved (blue) bars side by side, a gridline scale on the left, labels under each pair.
class _BarsPainter extends CustomPainter {
  _BarsPainter(this.rows);
  final List<Map<String, dynamic>> rows;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 30.0, bottom = 22.0;
    final h = size.height - bottom;
    final step = _niceStep(rows.fold<num>(1, (m, r) => math.max(m, math.max(r['target'] as num, r['achieved'] as num))));
    final top = step * 4;
    final grid = Paint()..color = const Color(0xFFE9EDF3);
    for (var k = 0; k <= 4; k++) {
      final y = h - h * k / 4;
      canvas.drawLine(Offset(left, y), Offset(size.width, y), grid);
      final tp = _label(_short(step * k), 10, Colors.black45);
      tp.paint(canvas, Offset(left - tp.width - 6, y - tp.height / 2));
    }
    if (rows.isEmpty) return;
    final slot = (size.width - left) / rows.length;
    final bw = math.min(14.0, slot / 4);
    for (var i = 0; i < rows.length; i++) {
      final r = rows[i];
      final cx = left + slot * i + slot / 2;
      for (final (dx, v, c) in [(-bw - 1, r['target'] as num, _target), (1.0, r['achieved'] as num, _blue)]) {
        final bh = h * v / top;
        canvas.drawRRect(RRect.fromRectAndCorners(Rect.fromLTWH(cx + dx, h - bh, bw, bh), topLeft: const Radius.circular(3), topRight: const Radius.circular(3)),
            Paint()..color = c);
      }
      final tp = _label(r['label'] as String, 10.5, Colors.black54);
      tp.paint(canvas, Offset(cx - tp.width / 2, h + 6));
    }
  }

  @override
  bool shouldRepaint(_BarsPainter old) => old.rows != rows;
}

/// A smooth line through each month's value, with dots and month labels.
class _TrendPainter extends CustomPainter {
  _TrendPainter(this.points, {required this.unit});
  final List<Map<String, dynamic>> points;
  final String unit;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 34.0, bottom = 22.0, topPad = 8.0;
    final h = size.height - bottom;
    final vals = [for (final p in points) (p['value'] as num?)?.toDouble()];
    final present = vals.whereType<double>().toList();
    final gridStep = _niceStep(present.isEmpty ? 1 : present.reduce(math.max));
    final top = gridStep * 4;
    final grid = Paint()..color = const Color(0xFFE9EDF3);
    for (var k = 0; k <= 4; k++) {
      final y = h - (h - topPad) * k / 4;
      canvas.drawLine(Offset(left, y), Offset(size.width, y), grid);
      final tp = _label(_short(gridStep * k), 10, Colors.black45);
      tp.paint(canvas, Offset(left - tp.width - 6, y - tp.height / 2));
    }
    final step = (size.width - left - 20) / math.max(1, points.length - 1);
    Offset at(int i) => Offset(left + 10 + step * i, h - (h - topPad) * (vals[i]! / top));
    final idx = [for (var i = 0; i < vals.length; i++) if (vals[i] != null) i];
    if (idx.isNotEmpty) {
      final path = Path()..moveTo(at(idx.first).dx, at(idx.first).dy);
      for (var k = 1; k < idx.length; k++) {
        final a = at(idx[k - 1]), b = at(idx[k]);
        final mx = (a.dx + b.dx) / 2;
        path.cubicTo(mx, a.dy, mx, b.dy, b.dx, b.dy);
      }
      canvas.drawPath(path, Paint()
        ..color = _blue
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.5);
      for (final i in idx) {
        canvas.drawCircle(at(i), 4.5, Paint()..color = _blue);
      }
    }
    for (var i = 0; i < points.length; i++) {
      final tp = _label(points[i]['label'] as String, 10.5, Colors.black54);
      tp.paint(canvas, Offset(left + 10 + step * i - tp.width / 2, h + 6));
    }
  }

  @override
  bool shouldRepaint(_TrendPainter old) => old.points != points;
}
