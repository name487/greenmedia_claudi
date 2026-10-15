import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state/session.dart';
import '../widgets/common.dart';
import 'content_screen.dart';
import 'keyword_planner_screen.dart';
import 'reviews_screen.dart';

void openBusinessScore(BuildContext context, int clientId) =>
    Navigator.push(context, MaterialPageRoute<void>(builder: (_) => Scaffold(body: BusinessScoreScreen(clientId: clientId))));

const navy = Color(0xFF0E1A3A);
const _flame = LinearGradient(colors: [Color(0xFFFF7A2F), Color(0xFFE8457C)]);
const _flameSoft = LinearGradient(colors: [Color(0xFFB04DE8), Color(0xFFFF7A2F)]);

/// The business owner's home: marketing score (with this week's growth and tracker), Google performance,
/// social calendar, keywords, competitors, social accounts, review QR, and the Growth Action checklist.
class BusinessScoreScreen extends StatefulWidget {
  const BusinessScoreScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<BusinessScoreScreen> createState() => _BusinessScoreScreenState();
}

class _BusinessScoreScreenState extends State<BusinessScoreScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<Map<String, dynamic>> _load() async => await context.read<Session>().api.get('/api/clients/${widget.clientId}/score') as Map<String, dynamic>;

  void _reload() => setState(() => _future = _load());

  Future<void> _open(Widget page, String title) async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => Scaffold(appBar: AppBar(title: Text(title)), body: SafeArea(top: false, child: page))));
    if (mounted) _reload();
  }

  Future<void> _openPlanner() async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => KeywordPlannerScreen(clientId: widget.clientId)));
    if (mounted) _reload();
  }

  /// Where a Growth Action / tracker row leads.
  Future<void> go(String target, Map<String, dynamic> d) async {
    final me = context.read<Session>().me!;
    switch (target) {
      case 'reviews':
        if (me.sees('reviews')) return _open(ReviewsScreen(clientId: widget.clientId), 'Review Replies');
      case 'content':
        if (me.sees('content')) return _open(const ContentScreen(), 'AI Post');
      case 'keyword_planner':
        return _openPlanner();
      case 'score':
        return showScoreBreakdown(context, d['score'] as Map<String, dynamic>, widget.clientId);
      case 'review_qr':
        return showReviewQr(context, d['client'] as Map<String, dynamic>);
    }
    return showHelp(context, d, reason: target == 'social' ? 'connect your social media' : target == 'profile' ? 'complete your profile' : null);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>>(
      future: _future,
      builder: (context, snap) {
        final d = snap.data;
        return Column(children: [
          _TopBar(client: d?['client'] as Map<String, dynamic>?, onHelp: d == null ? null : () => showHelp(context, d)),
          Expanded(child: _body(context, snap)),
        ]);
      },
    );
  }

  Widget _body(BuildContext context, AsyncSnapshot<Map<String, dynamic>> snap) {
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
    final actions = (d['actions'] as List).cast<Map<String, dynamic>>();
    return Stack(children: [
      RefreshIndicator(
        onRefresh: () async => _reload(),
        child: ListView(padding: const EdgeInsets.fromLTRB(12, 10, 12, 96), children: [
          _ScoreCarousel(data: d, clientId: widget.clientId, onGo: (t) => go(t, d)),
          _PerformanceCard(clientId: widget.clientId),
          _CalendarCard(clientId: widget.clientId, onPending: () => go('content', d)),
          _KeywordsCard(tracked: (d['tracked_keywords'] as List).cast<Map<String, dynamic>>(), onPlanner: () => go('keyword_planner', d)),
          _CompetitorCard(groups: d['competitor_groups'] as Map<String, dynamic>),
          _SocialCard(rows: (d['social'] as List).cast<Map<String, dynamic>>(), onConnect: () => go('social', d)),
          _ReviewQrCard(client: d['client'] as Map<String, dynamic>),
        ]),
      ),
      Positioned(
        left: 24,
        right: 24,
        bottom: 14,
        child: _GrowthActionPill(actions: actions, onTap: () => _showActions(d, actions)),
      ),
    ]);
  }

  void _showActions(Map<String, dynamic> d, List<Map<String, dynamic>> actions) {
    final done = actions.where((a) => a['done'] == true).length;
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (sheet) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .7,
        maxChildSize: .95,
        builder: (context, scroll) => ListView(controller: scroll, padding: const EdgeInsets.fromLTRB(16, 0, 16, 24), children: [
          Row(children: [
            const Icon(Icons.bolt_rounded, color: Color(0xFFFF7A2F)),
            const SizedBox(width: 6),
            Expanded(child: Text('Growth Action', style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700))),
            Text('$done of ${actions.length} done', style: Theme.of(context).textTheme.bodySmall),
          ]),
          const SizedBox(height: 8),
          ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: done / actions.length, minHeight: 6)),
          const SizedBox(height: 8),
          for (final a in actions)
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(a['done'] == true ? Icons.check_circle : Icons.radio_button_unchecked,
                  color: a['done'] == true ? const Color(0xFF2E9E5B) : Theme.of(context).hintColor),
              title: Text(a['title'] as String,
                  style: TextStyle(fontWeight: FontWeight.w600, decoration: a['done'] == true ? TextDecoration.lineThrough : null)),
              subtitle: Text(a['detail'] as String),
              trailing: a['done'] == true
                  ? null
                  : FilledButton.tonal(
                      onPressed: () {
                        Navigator.pop(sheet);
                        go(a['target'] as String, d);
                      },
                      child: Text(a['action'] as String),
                    ),
            ),
        ]),
      ),
    );
  }
}

// ---------- top bar ----------

class _TopBar extends StatelessWidget {
  const _TopBar({required this.client, required this.onHelp});
  final Map<String, dynamic>? client;
  final VoidCallback? onHelp;

  @override
  Widget build(BuildContext context) {
    final name = client?['company_name'] as String? ?? '';
    final phone = client?['phone'] as String? ?? '';
    final canPop = Navigator.of(context).canPop();
    return Container(
      color: navy,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 8, 12, 10),
          child: Row(children: [
            if (canPop) IconButton(icon: const Icon(Icons.arrow_back, color: Colors.white), tooltip: 'Back', onPressed: () => Navigator.pop(context)),
            if (!canPop) const SizedBox(width: 6),
            CircleAvatar(
              radius: 19,
              backgroundColor: Colors.white,
              child: Text(name.isEmpty ? '·' : name[0].toUpperCase(), style: const TextStyle(color: navy, fontWeight: FontWeight.w800)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 15)),
                if (phone.isNotEmpty || (client?['city'] as String? ?? '').isNotEmpty)
                  Text([phone, client?['city'] ?? ''].where((s) => '$s'.isNotEmpty).join(' | '), maxLines: 1,
                      style: const TextStyle(color: Colors.white70, fontSize: 11)),
              ]),
            ),
            OutlinedButton.icon(
              onPressed: onHelp,
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.white,
                side: const BorderSide(color: Colors.white54),
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.symmetric(horizontal: 10),
              ),
              icon: const Icon(Icons.call_outlined, size: 16),
              label: const Text('Help'),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Contact the account manager (calls, WhatsApp). Connections and profile changes are done by the agency.
void showHelp(BuildContext context, Map<String, dynamic> d, {String? reason}) {
  final s = d['support'] as Map<String, dynamic>?;
  final name = s?['name'] as String? ?? 'your account manager';
  final phone = (s?['phone'] as String? ?? '').replaceAll(RegExp(r'[^\d+]'), '');
  final business = (d['client'] as Map)['company_name'];
  final text = reason == null ? 'Hi $name, I need help with $business.' : 'Hi $name, please help me $reason for $business.';
  showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (sheet) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(reason == null ? 'Need help?' : 'We’ll $reason for you',
              style: Theme.of(sheet).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(s == null ? 'Contact your agency.' : '$name is your account manager.', style: Theme.of(sheet).textTheme.bodyMedium),
          const SizedBox(height: 14),
          if (phone.isNotEmpty) ...[
            FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFF25D366), foregroundColor: Colors.white, minimumSize: const Size.fromHeight(46)),
              icon: const Icon(Icons.chat_rounded),
              label: const Text('WhatsApp'),
              onPressed: () => launchUrl(Uri.parse('https://wa.me/${phone.replaceAll('+', '')}?text=${Uri.encodeComponent(text)}'),
                  mode: LaunchMode.externalApplication),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(46)),
              icon: const Icon(Icons.call),
              label: Text('Call $phone'),
              onPressed: () => launchUrl(Uri.parse('tel:$phone')),
            ),
          ],
        ]),
      ),
    ),
  );
}

// ---------- marketing score carousel ----------

const _labelColors = {'poor': Color(0xFFD64545), 'average': Color(0xFFE5A100), 'good': Color(0xFF2E9E5B), 'excellent': Color(0xFF0F7A45)};
const _statusColors = {'poor': Color(0xFFD64545), 'ok': Color(0xFFE08A1E), 'good': Color(0xFF2E9E5B)};

class _ScoreCarousel extends StatefulWidget {
  const _ScoreCarousel({required this.data, required this.clientId, required this.onGo});
  final Map<String, dynamic> data;
  final int clientId;
  final ValueChanged<String> onGo;

  @override
  State<_ScoreCarousel> createState() => _ScoreCarouselState();
}

class _ScoreCarouselState extends State<_ScoreCarousel> {
  final _pages = PageController();
  int _page = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.data;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(0, 14, 0, 10),
        child: Column(children: [
          SizedBox(
            height: 300,
            // swipe with a mouse or trackpad too (desktop and web), not only touch
            child: ScrollConfiguration(
              behavior: ScrollConfiguration.of(context).copyWith(dragDevices: PointerDeviceKind.values.toSet()),
              child: PageView(
                controller: _pages,
                onPageChanged: (i) => setState(() => _page = i),
                children: [
                  _ScorePage(score: d['score'] as Map<String, dynamic>, onImprove: () => widget.onGo('score')),
                  _GrowthPage(history: (d['history'] as List).cast<Map<String, dynamic>>()),
                  _TrackerPage(tracker: d['tracker'] as Map<String, dynamic>, onGo: widget.onGo),
                ],
              ),
            ),
          ),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            for (var i = 0; i < 3; i++)
              GestureDetector(
                onTap: () => _pages.animateToPage(i, duration: const Duration(milliseconds: 300), curve: Curves.easeOut),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  margin: const EdgeInsets.all(3),
                  width: _page == i ? 16 : 6,
                  height: 6,
                  decoration: BoxDecoration(
                      color: _page == i ? const Color(0xFFE8457C) : Theme.of(context).dividerColor, borderRadius: BorderRadius.circular(99)),
                ),
              ),
          ]),
        ]),
      ),
    );
  }
}

Widget _pageTitle(BuildContext context, String title, [String? filter]) => Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(children: [
        Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
        if (filter != null) ...[
          Icon(Icons.filter_alt_outlined, size: 16, color: Theme.of(context).hintColor),
          Text(filter, style: Theme.of(context).textTheme.bodySmall),
        ],
      ]),
    );

class _ScorePage extends StatelessWidget {
  const _ScorePage({required this.score, required this.onImprove});
  final Map<String, dynamic> score;
  final VoidCallback onImprove;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final value = score['value'] as int;
    final label = score['label'] as String;
    final colour = _labelColors[label] ?? Colors.green;
    return Column(children: [
      _pageTitle(context, 'Marketing Score'),
      const SizedBox(height: 10),
      SizedBox(
        width: 240,
        height: 136,
        child: CustomPaint(
          painter: ScoreGaugePainter(value / 100, track: Theme.of(context).dividerColor.withValues(alpha: .35)),
          child: Padding(
            padding: const EdgeInsets.only(top: 62),
            child: Text('$value%', key: const Key('score-value'), textAlign: TextAlign.center, style: t.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
          ),
        ),
      ),
      SizedBox(
        width: 250,
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text('0', style: t.bodySmall?.copyWith(color: const Color(0xFFD64545), fontWeight: FontWeight.w700)),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 3),
            decoration: BoxDecoration(color: colour, borderRadius: BorderRadius.circular(99)),
            child: Text('${label[0].toUpperCase()}${label.substring(1)}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
          ),
          Text('100', style: t.bodySmall?.copyWith(color: const Color(0xFF2E9E5B), fontWeight: FontWeight.w700)),
        ]),
      ),
      const Spacer(),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: OutlinedButton(
          style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(44),
              foregroundColor: const Color(0xFFB04DE8),
              side: const BorderSide(color: Color(0xFFE8457C)),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
          onPressed: onImprove,
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Flexible(child: Text('Improve Marketing Score', overflow: TextOverflow.ellipsis)),
            SizedBox(width: 6),
            Icon(Icons.arrow_forward, size: 18),
          ]),
        ),
      ),
    ]);
  }
}

class _GrowthPage extends StatelessWidget {
  const _GrowthPage({required this.history});
  final List<Map<String, dynamic>> history;

  @override
  Widget build(BuildContext context) {
    final labels = [for (final h in history) DateFormat('E').format(DateTime.parse(h['date'] as String))];
    final values = [for (final h in history) (h['value'] as num?)?.toDouble()];
    final known = values.whereType<double>().toList();
    final change = known.length >= 2 ? known.last - known.first : 0.0;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _pageTitle(context, 'Growth in Marketing Score', 'This Week'),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
        child: Text(
            known.length < 2
                ? 'Your score is recorded every day — the line fills in as the week goes on.'
                : change >= 0
                    ? 'Up ${change.toStringAsFixed(0)} points this week'
                    : 'Down ${(-change).toStringAsFixed(0)} points this week',
            style: Theme.of(context).textTheme.bodySmall),
      ),
      Expanded(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(8, 12, 16, 8),
          child: CustomPaint(
            painter: WeekLinePainter(values, labels,
                grid: Theme.of(context).dividerColor.withValues(alpha: .5),
                text: Theme.of(context).textTheme.labelSmall!.copyWith(color: Theme.of(context).hintColor),
                colour: const Color(0xFF1F63C6)),
          ),
        ),
      ),
    ]);
  }
}

/// 0-100% line for one week; missing days leave a gap.
class WeekLinePainter extends CustomPainter {
  WeekLinePainter(this.values, this.labels, {required this.grid, required this.text, required this.colour});
  final List<double?> values;
  final List<String> labels;
  final Color grid, colour;
  final TextStyle text;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 34.0, bottom = 18.0;
    final w = size.width - left, h = size.height - bottom;
    void label(String s, Offset at, {bool right = false}) {
      final tp = TextPainter(text: TextSpan(text: s, style: text), textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, at - Offset(right ? tp.width : tp.width / 2, tp.height / 2));
    }

    for (final f in [0, 25, 50, 75, 100]) {
      final y = h - h * f / 100;
      canvas.drawLine(Offset(left, y), Offset(size.width, y), Paint()..color = grid);
      label('$f%', Offset(left - 4, y), right: true);
    }
    double x(int i) => left + 8 + i / (values.length - 1) * (w - 16);
    final line = Paint()
      ..color = colour
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    Offset? prev;
    for (var i = 0; i < values.length; i++) {
      label(labels[i], Offset(x(i), h + bottom / 2 + 2));
      final v = values[i];
      if (v == null) {
        prev = null;
        continue;
      }
      final p = Offset(x(i), h - v / 100 * h);
      if (prev != null) canvas.drawLine(prev, p, line);
      canvas.drawCircle(p, 4.5, Paint()..color = colour);
      canvas.drawCircle(p, 2, Paint()..color = Colors.white);
      prev = p;
    }
  }

  @override
  bool shouldRepaint(covariant WeekLinePainter old) => old.values != values;
}

class _TrackerPage extends StatelessWidget {
  const _TrackerPage({required this.tracker, required this.onGo});
  final Map<String, dynamic> tracker;
  final ValueChanged<String> onGo;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final tasks = (tracker['tasks'] as List).cast<Map<String, dynamic>>();
    final target = tasks.fold<int>(0, (a, r) => a + (r['target'] as int));
    final achieved = tasks.fold<int>(0, (a, r) => a + math.min(r['achieved'] as int, r['target'] as int));
    final head = t.labelSmall?.copyWith(fontWeight: FontWeight.w700);
    Widget cell(String s, {Color? colour, bool first = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 4),
          child: Text(s, textAlign: first ? TextAlign.left : TextAlign.center, style: t.bodySmall?.copyWith(color: colour, fontWeight: colour == null ? null : FontWeight.w700)),
        );
    return SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _pageTitle(context, 'Marketing Tracker', 'This Week'),
      const SizedBox(height: 8),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Table(
          columnWidths: const {0: FlexColumnWidth(2.6), 1: FlexColumnWidth(), 2: FlexColumnWidth(1.2), 3: FlexColumnWidth(1.1), 4: FixedColumnWidth(38)},
          border: TableBorder.all(color: Theme.of(context).dividerColor.withValues(alpha: .6), borderRadius: BorderRadius.circular(6)),
          defaultVerticalAlignment: TableCellVerticalAlignment.middle,
          children: [
            TableRow(children: [
              for (final (i, h) in ['Tasks', 'Target', 'Achieved', 'Pending', 'View'].indexed)
                Padding(padding: const EdgeInsets.all(6), child: Text(h, style: head, textAlign: i == 0 ? TextAlign.left : TextAlign.center)),
            ]),
            for (final r in tasks)
              TableRow(children: [
                cell(r['label'] as String, first: true),
                cell('${r['target']}'.padLeft(2, '0')),
                cell('${r['achieved']}'.padLeft(2, '0')),
                cell('${r['pending']}'.padLeft(2, '0'), colour: (r['pending'] as int) > 0 ? const Color(0xFFE5484D) : const Color(0xFF2E9E5B)),
                IconButton(
                  tooltip: 'Open ${r['label']}',
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.north_east_rounded, size: 18, color: Color(0xFFE8457C)),
                  onPressed: () => onGo(r['section'] as String),
                ),
              ]),
          ],
        ),
      ),
      const SizedBox(height: 16),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Column(children: [
          Row(children: [
            const Icon(Icons.directions_run_rounded, color: Color(0xFFFF7A2F)),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(99),
                child: LinearProgressIndicator(value: target == 0 ? 0 : achieved / target, minHeight: 6, color: const Color(0xFFFF7A2F)),
              ),
            ),
            const Icon(Icons.sports_score_rounded),
          ]),
          const SizedBox(height: 6),
          Text(tracker['headline'] as String, textAlign: TextAlign.center, style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w500)),
        ]),
      ),
    ]));
  }
}

void showScoreBreakdown(BuildContext context, Map<String, dynamic> score, int clientId) {
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
        const SizedBox(height: 8),
        FilledButton.tonalIcon(
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

/// Half-circle gauge: the full red → yellow → green scale with a knob at the score.
class ScoreGaugePainter extends CustomPainter {
  ScoreGaugePainter(this.fraction, {required this.track});
  final double fraction;
  final Color track;

  static const stroke = 13.0;

  @override
  void paint(Canvas canvas, Size size) {
    final radius = math.min(size.width / 2, size.height) - stroke;
    final center = Offset(size.width / 2, radius + stroke);
    final rect = Rect.fromCircle(center: center, radius: radius);
    const colours = [Color(0xFFE5484D), Color(0xFFF08A24), Color(0xFFF2C230), Color(0xFF8BC34A), Color(0xFF1FA463)];
    canvas.drawArc(rect, math.pi, math.pi, false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = stroke
          ..strokeCap = StrokeCap.round
          ..shader = const SweepGradient(startAngle: math.pi, endAngle: 2 * math.pi, colors: colours).createShader(rect));
    final f = fraction.clamp(0.0, 1.0);
    final angle = math.pi + math.pi * f;
    final knob = center + Offset(math.cos(angle), math.sin(angle)) * radius;
    final knobColour = Color.lerp(Color.lerp(colours[0], colours[2], math.min(1, f * 2))!, colours[4], math.max(0, f * 2 - 1))!;
    canvas.drawCircle(knob, stroke / 2 + 4, Paint()..color = Colors.white);
    canvas.drawCircle(knob, stroke / 2 + 1, Paint()..color = knobColour);
  }

  @override
  bool shouldRepaint(covariant ScoreGaugePainter old) => old.fraction != fraction || old.track != track;
}

// ---------- Google's performance ----------

class _PerformanceCard extends StatefulWidget {
  const _PerformanceCard({required this.clientId});
  final int clientId;

  @override
  State<_PerformanceCard> createState() => _PerformanceCardState();
}

class _PerformanceCardState extends State<_PerformanceCard> {
  int _days = 30;
  String _metric = 'views';
  late Future<Map<String, dynamic>> _future = _load();

  Future<Map<String, dynamic>> _load() async =>
      await context.read<Session>().api.get('/api/clients/${widget.clientId}/performance', {'days': _days}) as Map<String, dynamic>;

  static const metrics = [('views', 'Views', Icons.visibility_outlined), ('leads', 'Leads', Icons.person_add_alt), ('calls', 'Calls', Icons.call_outlined),
    ('directions', 'Directions', Icons.directions_outlined), ('website', 'Website', Icons.language)];

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final scheme = Theme.of(context).colorScheme;
    return SectionCard(
      title: "Google's Performance",
      action: PopupMenuButton<int>(
        initialValue: _days,
        tooltip: 'Date filter',
        onSelected: (v) => setState(() {
          _days = v;
          _future = _load();
        }),
        itemBuilder: (_) => [for (final v in const [30, 60, 120]) CheckedPopupMenuItem(value: v, checked: v == _days, child: Text('$v Days'))],
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.filter_alt_outlined, size: 16, color: Theme.of(context).hintColor),
          Text('$_days Days', key: const Key('perf-days'), style: t.bodySmall),
        ]),
      ),
      child: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) return const SizedBox(height: 230, child: Center(child: CircularProgressIndicator()));
          if (snap.hasError) return EmptyState('${snap.error}');
          final p = snap.data!;
          final totals = p['totals'] as Map<String, dynamic>;
          final series = (p['series'] as List).cast<Map<String, dynamic>>();
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                for (final (key, label, icon) in metrics)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(10),
                      onTap: () => setState(() => _metric = key),
                      child: Container(
                        width: 96,
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: _metric == key ? scheme.primaryContainer.withValues(alpha: .7) : null,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: _metric == key ? scheme.primary : Theme.of(context).dividerColor),
                        ),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [
                            Icon(icon, size: 14, color: Theme.of(context).hintColor),
                            const SizedBox(width: 4),
                            Flexible(child: Text(label, style: t.bodySmall, maxLines: 1, overflow: TextOverflow.ellipsis)),
                          ]),
                          const SizedBox(height: 4),
                          FittedBox(
                            fit: BoxFit.scaleDown,
                            alignment: Alignment.centerLeft,
                            child: Text(NumberFormat.decimalPattern('en_IN').format(totals[key]), style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                          ),
                        ]),
                      ),
                    ),
                  ),
              ]),
            ),
            const SizedBox(height: 14),
            if (series.isEmpty)
              const EmptyState('No data yet — it appears after the first Google sync.')
            else
              SizedBox(
                height: 170,
                child: CustomPaint(
                  painter: AreaChartPainter(
                    series: [[for (final r in series) r[_metric] as num]],
                    colours: const [Color(0xFF3B6FE0)],
                    grid: Theme.of(context).dividerColor.withValues(alpha: .5),
                    text: t.labelSmall!.copyWith(color: Theme.of(context).hintColor),
                    labels: [for (final r in series) DateFormat('d MMM').format(DateTime.parse(r['date'] as String))],
                    fill: .12,
                  ),
                ),
              ),
          ]);
        },
      ),
    );
  }
}

/// Area/line chart with a y-axis scale and a few x labels.
class AreaChartPainter extends CustomPainter {
  AreaChartPainter({required this.series, required this.colours, required this.grid, required this.text, required this.labels, this.fill = .55});
  final List<List<num>> series;
  final List<Color> colours;
  final Color grid;
  final TextStyle text;
  final List<String> labels;
  final double fill;

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
      canvas.drawPath(area, Paint()..color = colours[s].withValues(alpha: fill));
      canvas.drawPath(line, Paint()
        ..color = colours[s]
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6);
    }
    label(labels.first, Offset(left, h + bottom / 2 + 2));
    if (n > 1) label(labels.last, Offset(size.width, h + bottom / 2 + 2), right: true);
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

// ---------- social calendar ----------

const _calColours = {'generated': Color(0xFFF2B01E), 'approved': Color(0xFF3B6FE0), 'posted': Color(0xFF2E9E5B)};

class _CalendarCard extends StatefulWidget {
  const _CalendarCard({required this.clientId, required this.onPending});
  final int clientId;
  final VoidCallback onPending;

  @override
  State<_CalendarCard> createState() => _CalendarCardState();
}

class _CalendarCardState extends State<_CalendarCard> {
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);
  late Future<Map<String, dynamic>> _future = _load();

  Future<Map<String, dynamic>> _load() async => await context.read<Session>().api.get('/api/clients/${widget.clientId}/calendar',
      {'month': DateFormat('yyyy-MM').format(_month)}) as Map<String, dynamic>;

  void _shift(int months) => setState(() {
        _month = DateTime(_month.year, _month.month + months);
        _future = _load();
      });

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return SectionCard(
      title: 'Social Calendar',
      child: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) {
          final cal = snap.data;
          final days = (cal?['days'] as Map?)?.cast<String, String>() ?? const <String, String>{};
          final pending = cal?['pending_approval'] as int? ?? 0;
          final first = _month;
          final lead = first.weekday - 1;
          final count = DateTime(first.year, first.month + 1, 0).day;
          final today = DateTime.now();
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            InkWell(
              onTap: widget.onPending,
              borderRadius: BorderRadius.circular(10),
              child: Ink(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(gradient: _flameSoft, borderRadius: BorderRadius.circular(10)),
                child: Row(children: [
                  const Icon(Icons.schedule, color: Colors.white, size: 18),
                  const SizedBox(width: 8),
                  Expanded(child: Text('$pending post${pending == 1 ? '' : 's'} pending for approval', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
                  const Icon(Icons.chevron_right, color: Colors.white),
                ]),
              ),
            ),
            const SizedBox(height: 10),
            Row(children: [
              IconButton.outlined(tooltip: 'Previous month', onPressed: () => _shift(-1), icon: const Icon(Icons.chevron_left, color: Color(0xFFE8457C))),
              Expanded(child: Text(DateFormat('MMMM yyyy').format(_month), key: const Key('cal-month'), textAlign: TextAlign.center, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
              IconButton.outlined(tooltip: 'Next month', onPressed: () => _shift(1), icon: const Icon(Icons.chevron_right, color: Color(0xFFE8457C))),
            ]),
            const SizedBox(height: 6),
            GridView.count(
              crossAxisCount: 7,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 1.15,
              children: [
                for (final d in const ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']) Center(child: Text(d, style: t.labelSmall?.copyWith(fontWeight: FontWeight.w700))),
                for (var i = 0; i < lead; i++) const SizedBox.shrink(),
                for (var day = 1; day <= count; day++)
                  Builder(builder: (context) {
                    final key = DateFormat('yyyy-MM-dd').format(DateTime(first.year, first.month, day));
                    final state = days[key];
                    final isToday = today.year == first.year && today.month == first.month && today.day == day;
                    return Center(
                      child: Container(
                        width: 30,
                        height: 30,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: state == null ? null : _calColours[state]!.withValues(alpha: .18),
                          shape: BoxShape.circle,
                          border: isToday ? Border.all(color: Theme.of(context).colorScheme.primary, width: 1.5) : null,
                        ),
                        child: Text('$day', style: t.bodySmall?.copyWith(color: state == null ? null : _calColours[state], fontWeight: state == null ? null : FontWeight.w700)),
                      ),
                    );
                  }),
              ],
            ),
            Wrap(spacing: 12, runSpacing: 4, children: [
              for (final (k, label) in const [('generated', 'Generated'), ('approved', 'Approved'), ('posted', 'Posted')])
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Container(width: 8, height: 8, decoration: BoxDecoration(color: _calColours[k], shape: BoxShape.circle)),
                  const SizedBox(width: 4),
                  Text(label, style: t.bodySmall),
                ]),
              Row(mainAxisSize: MainAxisSize.min, children: [
                Container(width: 8, height: 8, decoration: BoxDecoration(color: Theme.of(context).dividerColor, shape: BoxShape.circle)),
                const SizedBox(width: 4),
                Text('No Post', style: t.bodySmall),
              ]),
            ]),
          ]);
        },
      ),
    );
  }
}

// ---------- keywords ----------

class _KeywordsCard extends StatelessWidget {
  const _KeywordsCard({required this.tracked, required this.onPlanner});
  final List<Map<String, dynamic>> tracked;
  final VoidCallback onPlanner;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final head = t.labelMedium?.copyWith(fontWeight: FontWeight.w700);
    return SectionCard(
      title: 'Keywords',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (tracked.isEmpty)
          Text('Add the searches you want to be found for — the Keyword Planner shows how often people search them.', style: t.bodySmall)
        else ...[
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            color: Theme.of(context).dividerColor.withValues(alpha: .25),
            child: Row(children: [SizedBox(width: 64, child: Text('Search', style: head)), Expanded(child: Text('Keyword', style: head))]),
          ),
          for (final k in tracked.take(6))
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
              child: Row(children: [
                SizedBox(width: 64, child: Text(compact(k['volume'] as num), style: t.bodyMedium)),
                Expanded(child: Text(k['keyword'] as String, maxLines: 1, overflow: TextOverflow.ellipsis)),
              ]),
            ),
        ],
        const SizedBox(height: 10),
        OutlinedButton(
          style: OutlinedButton.styleFrom(
              minimumSize: const Size.fromHeight(44),
              foregroundColor: const Color(0xFFB04DE8),
              side: const BorderSide(color: Color(0xFFE8457C)),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
          onPressed: onPlanner,
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Flexible(child: Text('Access Keyword Planner', overflow: TextOverflow.ellipsis)),
            SizedBox(width: 4),
            Icon(Icons.chevron_right, size: 18),
          ]),
        ),
      ]),
    );
  }
}

// ---------- competitors ----------

class _CompetitorCard extends StatelessWidget {
  const _CompetitorCard({required this.groups});
  final Map<String, dynamic> groups;

  @override
  Widget build(BuildContext context) {
    final local = (groups['local'] as List).cast<Map<String, dynamic>>();
    final far = (groups['surrounding'] as List).cast<Map<String, dynamic>>();
    final km = (groups['local_km'] as num).toStringAsFixed(0);
    final sample = [...local, ...far].any((r) => r['is_sample'] == true);
    return SectionCard(
      title: 'Competitor Analysis',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _CompetitorTable(title: 'LOCAL COMPETITORS · WITHIN $km KM', rows: local),
        if (far.isNotEmpty) ...[const SizedBox(height: 14), _CompetitorTable(title: 'SURROUNDING AREA · BEYOND $km KM', rows: far)],
        if (sample)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('Sample competitors — your account manager can add the real ones.',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.orange.shade800)),
          ),
      ]),
    );
  }
}

class _CompetitorTable extends StatelessWidget {
  const _CompetitorTable({required this.title, required this.rows});
  final String title;
  final List<Map<String, dynamic>> rows;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final scheme = Theme.of(context).colorScheme;
    final head = t.labelSmall?.copyWith(fontWeight: FontWeight.w800, letterSpacing: .4);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Icon(Icons.location_on_outlined, size: 14, color: scheme.primary),
        const SizedBox(width: 4),
        Expanded(child: Text(title, style: t.labelSmall?.copyWith(color: scheme.primary, fontWeight: FontWeight.w700, letterSpacing: .5))),
      ]),
      const SizedBox(height: 6),
      DecoratedBox(
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(8)),
        child: Column(children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            color: Theme.of(context).dividerColor.withValues(alpha: .25),
            child: Row(children: [Expanded(child: Text('BUSINESS', style: head)), Text('RATING', style: head)]),
          ),
          for (final r in rows)
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                dense: true,
                visualDensity: VisualDensity.compact,
                tilePadding: const EdgeInsets.only(left: 12, right: 4),
                backgroundColor: r['is_you'] == true ? scheme.primaryContainer.withValues(alpha: .4) : null,
                collapsedBackgroundColor: r['is_you'] == true ? scheme.primaryContainer.withValues(alpha: .4) : null,
                title: Row(children: [
                  Expanded(
                    child: Text(r['is_you'] == true ? '${r['name']} (you)' : r['name'] as String, maxLines: 2, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontWeight: r['is_you'] == true ? FontWeight.w700 : FontWeight.w400)),
                  ),
                  const Icon(Icons.star_rounded, size: 15, color: Color(0xFFF2B01E)),
                  Text((r['rating'] as num).toStringAsFixed(1), style: const TextStyle(fontWeight: FontWeight.w600)),
                ]),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
                children: [
                  if ((r['address'] as String? ?? '').isNotEmpty) _infoLine(context, Icons.place_outlined, r['address'] as String),
                  if (r['distance_km'] != null && r['is_you'] != true) _infoLine(context, Icons.near_me_outlined, '${r['distance_km']} km away'),
                  _infoLine(context, Icons.groups_outlined, '${NumberFormat.decimalPattern('en_IN').format(r['review_count'])} ratings'),
                ],
              ),
            ),
        ]),
      ),
    ]);
  }

  Widget _infoLine(BuildContext context, IconData icon, String text) => Padding(
        padding: const EdgeInsets.only(top: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(icon, size: 14, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 6),
          Expanded(child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
        ]),
      );
}

// ---------- social media ----------

class _SocialCard extends StatelessWidget {
  const _SocialCard({required this.rows, required this.onConnect});
  final List<Map<String, dynamic>> rows;
  final VoidCallback onConnect;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return SectionCard(
      title: 'Stay active on Social Media',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Connect profiles to automate marketing', style: t.bodySmall),
        const SizedBox(height: 6),
        for (final r in rows)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: r['platform'] == 'facebook'
                ? const CircleAvatar(backgroundColor: Color(0xFF1877F2), child: Icon(Icons.facebook, color: Colors.white))
                : const CircleAvatar(backgroundColor: Color(0xFFE1306C), child: Icon(Icons.camera_alt_outlined, color: Colors.white)),
            title: Text(r['platform'] == 'facebook' ? 'Facebook' : 'Instagram', style: const TextStyle(fontWeight: FontWeight.w600)),
            subtitle: Text(r['connected'] == true ? ((r['handle'] as String).isEmpty ? 'Connected' : r['handle'] as String) : r['status'] == 'expired' ? 'Needs reconnecting' : 'Not connected'),
            trailing: r['connected'] == true
                ? const StatusChip('connected', label: 'Connected')
                : TextButton(
                    onPressed: onConnect,
                    child: const Row(mainAxisSize: MainAxisSize.min, children: [Text('Connect'), Icon(Icons.chevron_right, size: 18)]),
                  ),
          ),
      ]),
    );
  }
}

// ---------- review QR ----------

void showReviewQr(BuildContext context, Map<String, dynamic> client) {
  showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (_) => SafeArea(child: Padding(padding: const EdgeInsets.fromLTRB(4, 0, 4, 12), child: _ReviewQrCard(client: client))),
  );
}

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

// ---------- Growth Action pill ----------

class _GrowthActionPill extends StatelessWidget {
  const _GrowthActionPill({required this.actions, required this.onTap});
  final List<Map<String, dynamic>> actions;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final done = actions.where((a) => a['done'] == true).length;
    return Material(
      elevation: 6,
      shadowColor: const Color(0x55E8457C),
      borderRadius: BorderRadius.circular(99),
      child: InkWell(
        key: const Key('growth-action'),
        borderRadius: BorderRadius.circular(99),
        onTap: onTap,
        child: Ink(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          decoration: BoxDecoration(gradient: _flame, borderRadius: BorderRadius.circular(99)),
          child: Row(children: [
            const CircleAvatar(radius: 16, backgroundColor: Color(0x33FFFFFF), child: Icon(Icons.bolt_rounded, color: Colors.white, size: 20)),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                const Text('Growth Action', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
                Text('$done of ${actions.length} done · ${actions.length - done} left', style: const TextStyle(color: Colors.white70, fontSize: 11)),
              ]),
            ),
            const Icon(Icons.chevron_right, color: Colors.white),
          ]),
        ),
      ),
    );
  }
}
