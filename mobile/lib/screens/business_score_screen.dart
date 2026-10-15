import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'reviews_screen.dart';

void openBusinessScore(BuildContext context, int clientId) => Navigator.push(
    context,
    MaterialPageRoute<void>(
        builder: (_) => Scaffold(appBar: AppBar(title: const Text('Business score')), body: SafeArea(top: false, child: BusinessScoreScreen(clientId: clientId)))));

/// One business at a glance: Google profile score with what to fix, activity, 30-day stats, views chart,
/// what people searched to find it, how it compares with nearby competitors, and a review QR to share.
class BusinessScoreScreen extends StatefulWidget {
  const BusinessScoreScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<BusinessScoreScreen> createState() => _BusinessScoreScreenState();
}

class _BusinessScoreScreenState extends State<BusinessScoreScreen> {
  late Future<Map<String, dynamic>> _future;
  final _scoreKey = GlobalKey(), _keywordsKey = GlobalKey(), _competitorKey = GlobalKey();
  String _tab = 'score';

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<Map<String, dynamic>> _load() async => await context.read<Session>().api.get('/api/clients/${widget.clientId}/score') as Map<String, dynamic>;

  void _reload() => setState(() => _future = _load());

  void _jump(String tab, GlobalKey key) {
    setState(() => _tab = tab);
    final ctx = key.currentContext;
    if (ctx != null) Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic, alignment: .02);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>>(
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
                FilledButton.tonal(onPressed: _reload, child: const Text('Retry')),
              ]),
            ),
          );
        }
        final d = snap.data!;
        final me = context.read<Session>().me!;
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              _Header(client: d['client'] as Map<String, dynamic>, asOf: parseDate(d['as_of']), tab: _tab, onTab: (t) {
                _jump(t, {'score': _scoreKey, 'keywords': _keywordsKey, 'competitor': _competitorKey}[t]!);
              }),
              _ScoreCard(key: _scoreKey, data: d, clientId: widget.clientId),
              _HeatmapCard(heatmap: d['heatmap'] as Map<String, dynamic>),
              _StatsGrid(stats: d['stats'] as Map<String, dynamic>),
              if (me.sees('reviews'))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: OutlinedButton.icon(
                    key: const Key('reply-with-ai'),
                    style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(46)),
                    icon: const Icon(Icons.auto_awesome),
                    label: const Text('Reply With AI'),
                    onPressed: () async {
                      await Navigator.push(context, MaterialPageRoute<void>(
                          builder: (_) => Scaffold(appBar: AppBar(title: const Text('Reviews')), body: ReviewsScreen(clientId: widget.clientId))));
                      _reload();
                    },
                  ),
                ),
              _ViewsChart(chart: d['chart'] as Map<String, dynamic>),
              _KeywordsCard(key: _keywordsKey, keywords: d['keywords'] as Map<String, dynamic>),
              _CompetitorCard(key: _competitorKey, rows: (d['competitors'] as List).cast<Map<String, dynamic>>()),
              _ReviewQrCard(client: d['client'] as Map<String, dynamic>),
            ]),
          ),
        );
      },
    );
  }
}

// ---------- header ----------

class _Header extends StatelessWidget {
  const _Header({required this.client, required this.asOf, required this.tab, required this.onTab});
  final Map<String, dynamic> client;
  final DateTime? asOf;
  final String tab;
  final ValueChanged<String> onTab;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final scheme = Theme.of(context).colorScheme;
    final name = client['company_name'] as String;
    final email = client['email'] as String? ?? '';
    final phone = client['phone'] as String? ?? '';
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            CircleAvatar(
              radius: 22,
              backgroundColor: scheme.primaryContainer,
              child: Text(name.isEmpty ? '?' : name[0].toUpperCase(), style: TextStyle(color: scheme.onPrimaryContainer, fontWeight: FontWeight.w700, fontSize: 18)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(email.isEmpty ? name : email, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w600), maxLines: 1, overflow: TextOverflow.ellipsis),
                if (phone.isNotEmpty) Text(phone, style: t.bodySmall),
                Text('Updated ${asOf == null ? '—' : DateFormat('d MMM yyyy').format(asOf!)}', style: t.bodySmall?.copyWith(color: Theme.of(context).hintColor)),
              ]),
            ),
            if (client['google_connected'] != true) const StatusChip('failed', label: 'Needs Google'),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            for (final (key, label) in const [('score', 'Score'), ('keywords', 'Keywords'), ('competitor', 'Competitor')])
              Expanded(
                child: InkWell(
                  onTap: () => onTab(key),
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    decoration: BoxDecoration(border: Border(bottom: BorderSide(width: 2.5, color: tab == key ? scheme.primary : Colors.transparent))),
                    child: Text(label, textAlign: TextAlign.center,
                        style: t.labelLarge?.copyWith(color: tab == key ? scheme.primary : Theme.of(context).hintColor, fontWeight: tab == key ? FontWeight.w700 : FontWeight.w500)),
                  ),
                ),
              ),
          ]),
        ]),
      ),
    );
  }
}

// ---------- score ----------

const _labelColors = {'poor': Color(0xFFD64545), 'average': Color(0xFFE08A1E), 'good': Color(0xFF2E9E5B), 'excellent': Color(0xFF0F7A45)};
const _statusColors = {'poor': Color(0xFFD64545), 'ok': Color(0xFFE08A1E), 'good': Color(0xFF2E9E5B)};

class _ScoreCard extends StatelessWidget {
  const _ScoreCard({super.key, required this.data, required this.clientId});
  final Map<String, dynamic> data;
  final int clientId;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final score = data['score'] as Map<String, dynamic>;
    final value = score['value'] as int;
    final label = score['label'] as String;
    final colour = _labelColors[label] ?? Colors.green;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text((data['client'] as Map)['company_name'] as String, textAlign: TextAlign.center, style: t.titleLarge?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          Center(
            child: SizedBox(
              width: 220,
              height: 128,
              child: CustomPaint(
                painter: ScoreGaugePainter(value / 100, track: Theme.of(context).dividerColor.withValues(alpha: .35)),
                child: Padding(
                  padding: const EdgeInsets.only(top: 46),
                  child: Column(children: [
                    Text('$value%', key: const Key('score-value'), style: t.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
                    Text('Out of 100', style: t.bodySmall),
                  ]),
                ),
              ),
            ),
          ),
          SizedBox(
            width: 236,
            child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Text('0', style: t.bodySmall),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 3),
                decoration: BoxDecoration(color: colour.withValues(alpha: .14), borderRadius: BorderRadius.circular(99)),
                child: Text(label, style: TextStyle(color: colour, fontWeight: FontWeight.w600)),
              ),
              Text('100', style: t.bodySmall),
            ]),
          ),
          const SizedBox(height: 14),
          Center(
            child: FilledButton(
              style: FilledButton.styleFrom(shape: const StadiumBorder(), padding: const EdgeInsets.symmetric(horizontal: 22)),
              onPressed: () => _showBreakdown(context, score),
              child: const Text('Check Detailed Report'),
            ),
          ),
          const SizedBox(height: 10),
          FilledButton.tonalIcon(
            style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
            icon: const Icon(Icons.download_rounded),
            label: const Text('Download Report'),
            onPressed: () => runAction(context, (api) async {
              final out = await api.post('/api/clients/$clientId/score/report-link') as Map<String, dynamic>;
              await launchUrl(Uri.parse(out['url'] as String), mode: LaunchMode.externalApplication);
            }),
          ),
        ]),
      ),
    );
  }

  void _showBreakdown(BuildContext context, Map<String, dynamic> score) {
    final items = (score['items'] as List).cast<Map<String, dynamic>>();
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheet) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .75,
        maxChildSize: .95,
        builder: (context, scroll) => ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(16, 0, 16, 24), children: [
          Text('Your score: ${score['value']} / 100', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          Text('Fix the red and orange items first — each one shows how many points it can add.', style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          for (final i in items) _BreakdownRow(i),
        ]),
      ),
    );
  }
}

class _BreakdownRow extends StatelessWidget {
  const _BreakdownRow(this.item);
  final Map<String, dynamic> item;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final colour = _statusColors[item['status']] ?? Colors.grey;
    final points = item['points'] as int, max = item['max'] as int;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(item['status'] == 'good' ? Icons.check_circle : Icons.error_outline, color: colour, size: 20),
          const SizedBox(width: 8),
          Expanded(child: Text(item['label'] as String, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w600))),
          Text('$points / $max', style: t.titleSmall?.copyWith(color: colour, fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: LinearProgressIndicator(value: max == 0 ? 0 : points / max, minHeight: 6, color: colour, backgroundColor: colour.withValues(alpha: .15)),
        ),
        const SizedBox(height: 4),
        Text(item['detail'] as String, style: t.bodySmall),
        if (item['status'] != 'good') Text('Tip: ${item['tip']}', style: t.bodySmall?.copyWith(color: Theme.of(context).hintColor)),
      ]),
    );
  }
}

/// Half-circle gauge: red → orange → yellow → green, with a knob at the score.
class ScoreGaugePainter extends CustomPainter {
  ScoreGaugePainter(this.fraction, {required this.track});
  final double fraction;
  final Color track;

  static const stroke = 14.0;

  @override
  void paint(Canvas canvas, Size size) {
    final radius = math.min(size.width / 2, size.height) - stroke;
    final center = Offset(size.width / 2, radius + stroke);
    final rect = Rect.fromCircle(center: center, radius: radius);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(rect, math.pi, math.pi, false, base..color = track);
    const colours = [Color(0xFFD64545), Color(0xFFF08A24), Color(0xFFF2C230), Color(0xFF2E9E5B), Color(0xFF1FB57A)];
    final f = fraction.clamp(0.0, 1.0);
    if (f > 0) {
      canvas.drawArc(rect, math.pi, math.pi * f, false,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = stroke
            ..strokeCap = StrokeCap.round
            ..shader = const SweepGradient(startAngle: math.pi, endAngle: 2 * math.pi, colors: colours).createShader(rect));
    }
    final angle = math.pi + math.pi * f;
    final knob = center + Offset(math.cos(angle), math.sin(angle)) * radius;
    canvas.drawCircle(knob, stroke / 2 + 3, Paint()..color = Colors.white);
    canvas.drawCircle(knob, stroke / 2, Paint()..color = const Color(0xFF1F63C6));
  }

  @override
  bool shouldRepaint(covariant ScoreGaugePainter old) => old.fraction != fraction || old.track != track;
}

// ---------- activity heatmap ----------

class _HeatmapCard extends StatelessWidget {
  const _HeatmapCard({required this.heatmap});
  final Map<String, dynamic> heatmap;

  @override
  Widget build(BuildContext context) {
    final counts = (heatmap['counts'] as List).cast<int>();
    final weeks = heatmap['weeks'] as int;
    final todayIndex = heatmap['today_index'] as int;
    final start = DateTime.parse(heatmap['start'] as String);
    final peak = counts.isEmpty ? 1 : math.max(1, counts.reduce(math.max));
    final base = Theme.of(context).colorScheme.primary;
    final empty = Theme.of(context).dividerColor.withValues(alpha: .25);
    final t = Theme.of(context).textTheme;
    Color cell(int i) {
      if (i > todayIndex) return Colors.transparent;
      final c = counts[i];
      return c == 0 ? empty : base.withValues(alpha: .25 + .75 * c / peak);
    }

    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    return SectionCard(
      title: 'Activity',
      action: Text('${counts.fold<int>(0, (a, b) => a + b)} in $weeks weeks', style: t.bodySmall),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        LayoutBuilder(builder: (context, box) {
          final size = math.min(18.0, (box.maxWidth - 36) / weeks - 3);
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Column(children: [
              for (final d in days) SizedBox(height: size + 3, width: 34, child: Align(alignment: Alignment.centerLeft, child: Text(d, style: t.labelSmall))),
            ]),
            for (var w = 0; w < weeks; w++)
              Column(children: [
                for (var d = 0; d < 7; d++)
                  Tooltip(
                    message: '${DateFormat('d MMM').format(start.add(Duration(days: w * 7 + d)))}: ${counts[w * 7 + d]}',
                    child: Container(
                      width: size,
                      height: size,
                      margin: const EdgeInsets.all(1.5),
                      decoration: BoxDecoration(color: cell(w * 7 + d), borderRadius: BorderRadius.circular(3)),
                    ),
                  ),
              ]),
          ]);
        }),
        const SizedBox(height: 6),
        Text('Reviews received, replies and posts published each day', style: t.bodySmall?.copyWith(color: Theme.of(context).hintColor)),
      ]),
    );
  }
}

// ---------- stats ----------

class _StatsGrid extends StatelessWidget {
  const _StatsGrid({required this.stats});
  final Map<String, dynamic> stats;

  @override
  Widget build(BuildContext context) {
    final n = NumberFormat.decimalPattern('en_IN');
    return StatGrid(children: [
      _IconStat(icon: Icons.forum_outlined, label: 'Reply Pending', value: '${stats['reply_pending']} / ${stats['reply_window']}',
          hint: (stats['reply_pending'] as int) == 0 ? 'All caught up' : 'Waiting for a reply', alert: (stats['reply_pending'] as int) > 0),
      _IconStat(icon: Icons.star_border_rounded, label: 'Reviews (lifetime)', value: n.format(stats['reviews_lifetime']),
          hint: '${(stats['rating'] as num).toStringAsFixed(1)} average rating'),
      _IconStat(icon: Icons.visibility_outlined, label: 'Views (last 30 days)', value: n.format(stats['views_30d']), delta: stats['views_change_pct'] as num?),
      _IconStat(icon: Icons.trending_up, label: 'Engagements (last 30 days)', value: n.format(stats['engagements_30d']),
          hint: '${stats['engagement_rate']}% of views', delta: stats['engagements_change_pct'] as num?),
    ]);
  }
}

class _IconStat extends StatelessWidget {
  const _IconStat({required this.icon, required this.label, required this.value, this.hint, this.delta, this.alert = false});
  final IconData icon;
  final String label, value;
  final String? hint;
  final num? delta;
  final bool alert;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final colour = alert ? Colors.orange.shade800 : Theme.of(context).colorScheme.primary;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text(label, style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          Row(children: [
            Icon(icon, size: 20, color: colour),
            const SizedBox(width: 6),
            Flexible(child: Text(value, style: t.titleLarge?.copyWith(fontWeight: FontWeight.w700), maxLines: 1, overflow: TextOverflow.ellipsis)),
          ]),
          if (delta != null) Delta(delta!),
          if (hint != null) Text(hint!, style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
    );
  }
}

// ---------- views chart ----------

class _ViewsChart extends StatefulWidget {
  const _ViewsChart({required this.chart});
  final Map<String, dynamic> chart;

  @override
  State<_ViewsChart> createState() => _ViewsChartState();
}

class _ViewsChartState extends State<_ViewsChart> {
  String _period = 'monthly';

  @override
  Widget build(BuildContext context) {
    final rows = (widget.chart[_period] as List).cast<Map<String, dynamic>>();
    final fmt = _period == 'monthly' ? DateFormat('MMM') : DateFormat('d MMM');
    final labels = [for (final r in rows) fmt.format(DateTime.parse(r['start'] as String))];
    const views = Color(0xFF6C8EF5), actions = Color(0xFFE5507A);
    return SectionCard(
      title: 'Profile views',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SegmentedButton<String>(
          showSelectedIcon: false,
          segments: const [
            ButtonSegment(value: 'monthly', label: Text('Monthly')),
            ButtonSegment(value: 'daily', label: Text('Daily')),
            ButtonSegment(value: 'weekly', label: Text('Weekly')),
          ],
          selected: {_period},
          onSelectionChanged: (s) => setState(() => _period = s.first),
        ),
        const SizedBox(height: 14),
        if (rows.isEmpty)
          const EmptyState('No data yet — it appears after the first Google sync.')
        else ...[
          SizedBox(
            height: 170,
            child: CustomPaint(
              painter: AreaChartPainter(
                series: [[for (final r in rows) r['views'] as num], [for (final r in rows) r['actions'] as num]],
                colours: const [views, actions],
                grid: Theme.of(context).dividerColor.withValues(alpha: .5),
                text: Theme.of(context).textTheme.labelSmall!.copyWith(color: Theme.of(context).hintColor),
                labels: labels,
              ),
            ),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 16, children: [
            for (final (label, c) in const [('Views', views), ('Calls, directions & clicks', actions)])
              Row(mainAxisSize: MainAxisSize.min, children: [
                Container(width: 12, height: 12, decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(3))),
                const SizedBox(width: 5),
                Text(label, style: Theme.of(context).textTheme.bodySmall),
              ]),
          ]),
        ],
      ]),
    );
  }
}

/// Filled area chart with a y-axis scale and a few x labels.
class AreaChartPainter extends CustomPainter {
  AreaChartPainter({required this.series, required this.colours, required this.grid, required this.text, required this.labels});
  final List<List<num>> series;
  final List<Color> colours;
  final Color grid;
  final TextStyle text;
  final List<String> labels;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 40.0, bottom = 18.0;
    final w = size.width - left, h = size.height - bottom;
    final peak = math.max(1, series.expand((s) => s).fold<num>(0, math.max)).toDouble();
    final top = _niceCeil(peak);
    void label(String s, Offset at, {bool right = false, bool centre = false}) {
      final tp = TextPainter(text: TextSpan(text: s, style: text), textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, at - Offset(right ? tp.width : centre ? tp.width / 2 : 0, tp.height / 2));
    }

    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    for (var i = 0; i <= 2; i++) {
      final y = h - h * i / 2;
      canvas.drawLine(Offset(left, y), Offset(size.width, y), gridPaint);
      label(compact(top * i / 2), Offset(left - 6, y), right: true);
    }
    final n = series.first.length;
    double x(int i) => left + (n == 1 ? w / 2 : i / (n - 1) * w);
    for (var s = 0; s < series.length; s++) {
      final vals = series[s];
      final line = Path();
      for (var i = 0; i < n; i++) {
        final p = Offset(x(i), h - vals[i] / top * h);
        i == 0 ? line.moveTo(p.dx, p.dy) : line.lineTo(p.dx, p.dy);
      }
      final area = Path.from(line)
        ..lineTo(x(n - 1), h)
        ..lineTo(x(0), h)
        ..close();
      canvas.drawPath(area, Paint()..color = colours[s].withValues(alpha: s == 0 ? .55 : .7));
      canvas.drawPath(line, Paint()
        ..color = colours[s]
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6);
    }
    final every = math.max(1, (n / 4).ceil());
    for (var i = 0; i < n; i += every) {
      label(labels[i], Offset(x(i), h + bottom / 2 + 2), centre: i > 0, right: false);
    }
  }

  static double _niceCeil(double v) {
    final mag = math.pow(10, (math.log(v) / math.ln10).floor()).toDouble();
    for (final m in [1, 2, 2.5, 5, 10]) {
      if (m * mag >= v) return m * mag;
    }
    return 10 * mag;
  }

  @override
  bool shouldRepaint(covariant AreaChartPainter old) => old.series != series || old.labels != labels;
}

// ---------- search keywords ----------

class _KeywordsCard extends StatefulWidget {
  const _KeywordsCard({super.key, required this.keywords});
  final Map<String, dynamic> keywords;

  @override
  State<_KeywordsCard> createState() => _KeywordsCardState();
}

class _KeywordsCardState extends State<_KeywordsCard> {
  bool _all = false;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final items = (widget.keywords['items'] as List).cast<Map<String, dynamic>>();
    final shown = _all ? items : items.take(10).toList();
    final source = widget.keywords['source'] as String;
    final from = parseDate(widget.keywords['period_start']), to = parseDate(widget.keywords['period_end']);
    final period = from == null ? '' : '${DateFormat('MMM').format(from)} – ${DateFormat('MMM yyyy').format(to!)}';
    return SectionCard(
      title: 'Search Keywords',
      action: period.isEmpty ? null : Text(period, style: t.bodySmall),
      child: items.isEmpty
          ? const EmptyState('No search data yet. Connect Google to see what people search before they find you.')
          : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text('What people typed on Google before your profile appeared', style: t.bodySmall?.copyWith(color: Theme.of(context).hintColor)),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: Text('Search Keyword', style: t.labelMedium?.copyWith(fontWeight: FontWeight.w600))),
                Text('Appeared', style: t.labelMedium?.copyWith(fontWeight: FontWeight.w600)),
              ]),
              const Divider(),
              for (final k in shown)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 7),
                  child: Row(children: [
                    Expanded(child: Text(k['keyword'] as String, maxLines: 1, overflow: TextOverflow.ellipsis)),
                    Text('${k['below_threshold'] == true ? '<' : ''}${k['impressions']}',
                        style: TextStyle(color: Theme.of(context).colorScheme.primary, fontWeight: FontWeight.w600)),
                  ]),
                ),
              if (items.length > 10)
                TextButton(onPressed: () => setState(() => _all = !_all), child: Text(_all ? 'Show less' : 'Show more (${items.length - 10})')),
              if (source == 'sample')
                Text('Sample data — connect Google Business Profile for your real searches.', style: t.bodySmall?.copyWith(color: Colors.orange.shade800)),
            ]),
    );
  }
}

// ---------- competitors ----------

class _CompetitorCard extends StatelessWidget {
  const _CompetitorCard({super.key, required this.rows});
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final scheme = Theme.of(context).colorScheme;
    final rank = rows.indexWhere((r) => r['is_you'] == true) + 1;
    final rivals = rows.where((r) => r['is_you'] != true).toList();
    final betterRated = rivals.where((r) => (r['rating'] as num) > (rows[rank - 1]['rating'] as num)).length;
    return SectionCard(
      title: 'Competitor Analysis',
      child: rivals.isEmpty
          ? const EmptyState('No competitors added yet. Ask your account manager to add the businesses near you.')
          : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text("You're #$rank of ${rows.length} by number of reviews"
                  "${betterRated == 0 ? ' and the best rated.' : ' · $betterRated rated higher than you.'}",
                  style: t.bodySmall),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(child: Text('Business Name', style: t.labelMedium?.copyWith(fontWeight: FontWeight.w600))),
                SizedBox(width: 58, child: Text('Rating', textAlign: TextAlign.right, style: t.labelMedium?.copyWith(fontWeight: FontWeight.w600))),
                SizedBox(width: 66, child: Text('Reviews', textAlign: TextAlign.right, style: t.labelMedium?.copyWith(fontWeight: FontWeight.w600))),
              ]),
              const Divider(),
              for (final r in rows)
                Container(
                  padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
                  margin: const EdgeInsets.symmetric(vertical: 1),
                  decoration: BoxDecoration(color: r['is_you'] == true ? scheme.primaryContainer.withValues(alpha: .6) : null, borderRadius: BorderRadius.circular(8)),
                  child: Row(children: [
                    Expanded(
                      child: Text(r['is_you'] == true ? '${r['name']} (you)' : r['name'] as String, maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontWeight: r['is_you'] == true ? FontWeight.w700 : FontWeight.w400)),
                    ),
                    SizedBox(
                      width: 58,
                      child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                        Text((r['rating'] as num).toStringAsFixed(1)),
                        const Icon(Icons.star_rounded, size: 15, color: Color(0xFFF2B01E)),
                      ]),
                    ),
                    SizedBox(width: 66, child: Text(NumberFormat.decimalPattern('en_IN').format(r['review_count']), textAlign: TextAlign.right)),
                  ]),
                ),
              if (rivals.any((r) => r['is_sample'] == true))
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text('Sample competitors — your account manager can add the real ones.', style: t.bodySmall?.copyWith(color: Colors.orange.shade800)),
                ),
            ]),
    );
  }
}

// ---------- review QR ----------

class _ReviewQrCard extends StatelessWidget {
  const _ReviewQrCard({required this.client});
  final Map<String, dynamic> client;

  @override
  Widget build(BuildContext context) {
    final link = client['review_uri'] as String? ?? '';
    final t = Theme.of(context).textTheme;
    if (link.isEmpty) return const SizedBox.shrink();
    final message = 'Thank you for visiting ${client['company_name']}! Please share your experience on Google — it takes 30 seconds: $link';
    return SectionCard(
      title: 'Get more Google reviews',
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(10), border: Border.all(color: Theme.of(context).dividerColor)),
          child: QrImageView(data: link, size: 116, padding: EdgeInsets.zero, backgroundColor: Colors.white),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Review us on Google', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            Text('Print this QR for your counter, or send the link to customers after a visit.', style: t.bodySmall),
            const SizedBox(height: 8),
            FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFF25D366), foregroundColor: Colors.white),
              icon: const Icon(Icons.chat_rounded, size: 18),
              label: const Text('Share on WhatsApp'),
              onPressed: () => launchUrl(Uri.parse('https://wa.me/?text=${Uri.encodeComponent(message)}'), mode: LaunchMode.externalApplication),
            ),
            TextButton.icon(
              icon: const Icon(Icons.copy_rounded, size: 18),
              label: const Text('Copy review link'),
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: link));
                if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Review link copied')));
              },
            ),
          ]),
        ),
      ]),
    );
  }
}
