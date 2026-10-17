import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'reply_settings_screen.dart';

const _navy = Color(0xFF0E1A3A);
const _avatarColours = [Color(0xFF5B3CC4), Color(0xFF9C3FBF), Color(0xFF1F63C6), Color(0xFF0F7A45), Color(0xFFD0364F), Color(0xFFE08A1E)];

String timeAgo(DateTime? d) {
  if (d == null) return '';
  final s = DateTime.now().difference(d);
  if (s.inDays >= 365) return '${s.inDays ~/ 365}y ago';
  if (s.inDays >= 30) return '${s.inDays ~/ 30}mo ago';
  if (s.inDays >= 1) return '${s.inDays}d ago';
  if (s.inHours >= 1) return '${s.inHours}h ago';
  if (s.inMinutes >= 1) return '${s.inMinutes}m ago';
  return '${math.max(1, s.inSeconds)}s ago';
}

void showSuccess(BuildContext context, String message) => (ScaffoldMessenger.of(context)..hideCurrentSnackBar()).showSnackBar(SnackBar(
      behavior: SnackBarBehavior.floating,
      backgroundColor: Colors.white,
      content: Row(children: [
        const CircleAvatar(radius: 14, backgroundColor: Color(0xFF2E9E5B), child: Icon(Icons.check, color: Colors.white, size: 18)),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            const Text('Success', style: TextStyle(color: Colors.black87, fontWeight: FontWeight.w700)),
            Text(message, style: const TextStyle(color: Colors.black54, fontSize: 12)),
          ]),
        ),
      ]),
    ));

/// The business owner's Review Replies: reviews trend and Google rating, All / Pending / Replied, and every review
/// with its reply — post, edit or delete it, and see which search keywords the reply uses.
class OwnerReviewsScreen extends StatefulWidget {
  const OwnerReviewsScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<OwnerReviewsScreen> createState() => _OwnerReviewsScreenState();
}

class _OwnerReviewsScreenState extends State<OwnerReviewsScreen> {
  String _tab = 'all', _sort = 'newest', _period = 'month';
  int? _rating;
  Map<String, dynamic>? _summary;
  List<Map<String, dynamic>>? _items;
  String? _error;

  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([
        _api.get('/api/reviews/summary', {'client_id': widget.clientId, 'period': _period}),
        _api.get('/api/reviews', {'client_id': widget.clientId, 'filter': _tab, 'sort': _sort, 'rating': _rating, 'limit': 100}),
      ]);
      if (!mounted) return;
      setState(() {
        _summary = results[0] as Map<String, dynamic>;
        _items = ((results[1] as Map)['items'] as List).cast<Map<String, dynamic>>();
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _setTab(String tab) {
    setState(() {
      _tab = tab;
      _items = null;
    });
    _load();
  }

  Future<void> _openSettings() async {
    await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => ReplySettingsScreen(clientId: widget.clientId)));
  }

  Future<void> _filters() async {
    final picked = await showModalBottomSheet<(String, int?)>(
      context: context,
      showDragHandle: true,
      builder: (s) => _FilterSheet(sort: _sort, rating: _rating),
    );
    if (picked == null) return;
    setState(() {
      _sort = picked.$1;
      _rating = picked.$2;
      _items = null;
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    return Column(children: [
      _NavyBar(title: 'Review Replies', subtitle: me.clientName ?? '', onSettings: _openSettings),
      Expanded(
        child: _error != null && _summary == null
            ? Center(child: Column(mainAxisSize: MainAxisSize.min, children: [Text(_error!), TextButton(onPressed: _load, child: const Text('Retry'))]))
            : _summary == null
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(padding: const EdgeInsets.fromLTRB(12, 10, 12, 24), children: [
                      _TrendCarousel(
                        summary: _summary!,
                        period: _period,
                        onPeriod: (p) {
                          setState(() => _period = p);
                          _load();
                        },
                      ),
                      Align(
                        alignment: Alignment.centerRight,
                        child: IconButton(
                          tooltip: 'Filter',
                          icon: Icon(Icons.filter_alt_outlined, color: _rating != null || _sort != 'newest' ? const Color(0xFFE8457C) : null),
                          onPressed: _filters,
                        ),
                      ),
                      _Tabs(tab: _tab, counts: _summary!['counts'] as Map<String, dynamic>, onTab: _setTab),
                      const SizedBox(height: 8),
                      if (_items == null)
                        const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
                      else if (_items!.isEmpty)
                        EmptyState(_tab == 'pending' ? 'No pending reviews' : _tab == 'published' ? 'No replied reviews yet' : 'No reviews yet')
                      else
                        for (final r in _items!) ReviewReplyCard(key: ValueKey(r['id']), review: r, onChanged: _load),
                    ]),
                  ),
      ),
    ]);
  }
}

class _NavyBar extends StatelessWidget {
  const _NavyBar({required this.title, required this.subtitle, required this.onSettings});
  final String title, subtitle;
  final VoidCallback onSettings;

  @override
  Widget build(BuildContext context) {
    final canPop = Navigator.of(context).canPop();
    return Container(
      color: _navy,
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
              child: Text(subtitle.isEmpty ? '·' : subtitle[0].toUpperCase(), style: const TextStyle(color: _navy, fontWeight: FontWeight.w800)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 15)),
                if (subtitle.isNotEmpty) Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white70, fontSize: 11)),
              ]),
            ),
            OutlinedButton.icon(
              key: const Key('reply-settings'),
              onPressed: onSettings,
              style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white, side: const BorderSide(color: Colors.white54), visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 10)),
              icon: const Icon(Icons.settings_outlined, size: 16),
              label: const Text('Settings'),
            ),
          ]),
        ),
      ),
    );
  }
}

// ---------- trend + rating carousel ----------

class _TrendCarousel extends StatefulWidget {
  const _TrendCarousel({required this.summary, required this.period, required this.onPeriod});
  final Map<String, dynamic> summary;
  final String period;
  final ValueChanged<String> onPeriod;

  @override
  State<_TrendCarousel> createState() => _TrendCarouselState();
}

class _TrendCarouselState extends State<_TrendCarousel> {
  final _pages = PageController();
  int _page = 0;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.summary;
    final trend = (s['trend'] as List).cast<Map<String, dynamic>>();
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(0, 12, 0, 8),
        child: Column(children: [
          SizedBox(
            height: 210,
            child: ScrollConfiguration(
              behavior: ScrollConfiguration.of(context).copyWith(dragDevices: PointerDeviceKind.values.toSet()),
              child: PageView(controller: _pages, onPageChanged: (i) => setState(() => _page = i), children: [
                Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Row(children: [
                      Expanded(child: Text('Reviews Trend', style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
                      PopupMenuButton<String>(
                        tooltip: 'Period',
                        initialValue: widget.period,
                        onSelected: widget.onPeriod,
                        itemBuilder: (_) => const [
                          CheckedPopupMenuItem(value: 'month', child: Text('This Month')),
                          CheckedPopupMenuItem(value: 'quarter', child: Text('Last 3 Months')),
                        ],
                        child: Row(mainAxisSize: MainAxisSize.min, children: [
                          Icon(Icons.filter_alt_outlined, size: 16, color: Theme.of(context).hintColor),
                          Text(widget.period == 'month' ? 'This Month' : 'Last 3 Months', style: t.bodySmall),
                        ]),
                      ),
                    ]),
                  ),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(8, 12, 16, 4),
                      child: CustomPaint(
                        painter: CountLinePainter([for (final w in trend) (w['count'] as num).toDouble()], [for (final w in trend) w['label'] as String],
                            grid: Theme.of(context).dividerColor.withValues(alpha: .5), text: t.labelSmall!.copyWith(color: Theme.of(context).hintColor)),
                      ),
                    ),
                  ),
                ]),
                _RatingCard(rating: (s['rating'] as num).toDouble(), count: s['review_count'] as int),
              ]),
            ),
          ),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            for (var i = 0; i < 2; i++)
              Container(
                margin: const EdgeInsets.all(3),
                width: 6,
                height: 6,
                decoration: BoxDecoration(shape: BoxShape.circle, color: _page == i ? const Color(0xFF1F63C6) : Theme.of(context).dividerColor),
              ),
          ]),
        ]),
      ),
    );
  }
}

class _RatingCard extends StatelessWidget {
  const _RatingCard({required this.rating, required this.count});
  final double rating;
  final int count;

  @override
  Widget build(BuildContext context) {
    const g = [Color(0xFF4285F4), Color(0xFFEA4335), Color(0xFFFBBC05), Color(0xFF4285F4), Color(0xFF34A853), Color(0xFFEA4335)];
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        gradient: const LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Color(0xFFFFFFFF), Color(0xFFFFF0DE)]),
        border: Border.all(color: const Color(0xFFFBE3C4)),
      ),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text.rich(TextSpan(children: [
          for (final (i, ch) in 'Google'.split('').indexed) TextSpan(text: ch, style: TextStyle(color: g[i], fontWeight: FontWeight.w700, fontSize: 20)),
          const TextSpan(text: ' Ratings', style: TextStyle(color: Colors.black87, fontSize: 20)),
        ])),
        const SizedBox(height: 6),
        Text(rating.toStringAsFixed(1), key: const Key('google-rating'), style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w800, color: Color(0xFFF2A100))),
        Row(mainAxisSize: MainAxisSize.min, children: [
          for (var i = 1; i <= 5; i++)
            Icon(rating >= i ? Icons.star_rounded : rating >= i - .5 ? Icons.star_half_rounded : Icons.star_outline_rounded, color: const Color(0xFFF2A100)),
        ]),
        const SizedBox(height: 4),
        Text('Based on ${NumberFormat.decimalPattern('en_IN').format(count)} ratings', style: const TextStyle(color: Colors.black54)),
      ]),
    );
  }
}

/// Counts per week with a 0..max axis and dots.
class CountLinePainter extends CustomPainter {
  CountLinePainter(this.values, this.labels, {required this.grid, required this.text});
  final List<double> values;
  final List<String> labels;
  final Color grid;
  final TextStyle text;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 30.0, bottom = 18.0;
    final w = size.width - left, h = size.height - bottom;
    final top = math.max(4.0, (values.fold<double>(0, math.max) / 2).ceil() * 2.0 + 2);
    void label(String s, Offset at, {bool right = false}) {
      final tp = TextPainter(text: TextSpan(text: s, style: text), textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, at - Offset(right ? tp.width : tp.width / 2, tp.height / 2));
    }

    for (var i = 0; i <= 4; i++) {
      final y = h - h * i / 4;
      canvas.drawLine(Offset(left, y), Offset(size.width, y), Paint()..color = grid);
      label((top * i / 4).toStringAsFixed(top % 4 == 0 ? 0 : 1), Offset(left - 4, y), right: true);
    }
    if (values.isEmpty) return;
    double x(int i) => values.length == 1 ? left + w / 2 : left + 6 + i / (values.length - 1) * (w - 12);
    const colour = Color(0xFF1F63C6);
    final path = Path();
    for (var i = 0; i < values.length; i++) {
      final p = Offset(x(i), h - values[i] / top * h);
      i == 0 ? path.moveTo(p.dx, p.dy) : path.lineTo(p.dx, p.dy);
    }
    canvas.drawPath(path, Paint()
      ..color = colour
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke);
    final every = math.max(1, (values.length / 6).ceil());
    for (var i = 0; i < values.length; i++) {
      canvas.drawCircle(Offset(x(i), h - values[i] / top * h), 4.5, Paint()..color = colour);
      if (i % every == 0 || i == values.length - 1) label(labels[i], Offset(x(i), h + bottom / 2 + 2));
    }
  }

  @override
  bool shouldRepaint(covariant CountLinePainter old) => old.values != values;
}

// ---------- tabs + filters ----------

class _Tabs extends StatelessWidget {
  const _Tabs({required this.tab, required this.counts, required this.onTab});
  final String tab;
  final Map<String, dynamic> counts;
  final ValueChanged<String> onTab;

  @override
  Widget build(BuildContext context) {
    final tabs = [('all', 'All (${counts['all']})'), ('pending', 'Pending${(counts['pending'] as int) > 0 ? ' (${counts['pending']})' : ''}'),
      ('published', 'Replied (${counts['replied']})')];
    return Row(children: [
      for (final (key, label) in tabs)
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            child: InkWell(
              key: Key('tab-$key'),
              borderRadius: BorderRadius.circular(8),
              onTap: () => onTab(key),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 9),
                decoration: BoxDecoration(color: tab == key ? _navy : null, borderRadius: BorderRadius.circular(8)),
                child: Text(label, textAlign: TextAlign.center, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: tab == key ? Colors.white : Theme.of(context).hintColor, fontWeight: tab == key ? FontWeight.w700 : FontWeight.w500)),
              ),
            ),
          ),
        ),
    ]);
  }
}

class _FilterSheet extends StatefulWidget {
  const _FilterSheet({required this.sort, required this.rating});
  final String sort;
  final int? rating;

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late String _sort = widget.sort;
  late int? _rating = widget.rating;

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Sort', style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            Wrap(spacing: 8, children: [
              for (final (k, l) in const [('newest', 'Newest'), ('oldest', 'Oldest'), ('rating', 'Lowest rating')])
                ChoiceChip(label: Text(l), selected: _sort == k, onSelected: (_) => setState(() => _sort = k)),
            ]),
            const SizedBox(height: 12),
            Text('Rating', style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
            Wrap(spacing: 8, children: [
              ChoiceChip(label: const Text('All'), selected: _rating == null, onSelected: (_) => setState(() => _rating = null)),
              for (var i = 5; i >= 1; i--) ChoiceChip(label: Text('$i★'), selected: _rating == i, onSelected: (_) => setState(() => _rating = i)),
            ]),
            const SizedBox(height: 16),
            FilledButton(onPressed: () => Navigator.pop(context, (_sort, _rating)), child: const Text('Apply')),
          ]),
        ),
      );
}

// ---------- one review ----------

class ReviewReplyCard extends StatefulWidget {
  const ReviewReplyCard({super.key, required this.review, required this.onChanged});
  final Map<String, dynamic> review;
  final Future<void> Function() onChanged;

  @override
  State<ReviewReplyCard> createState() => _ReviewReplyCardState();
}

class _ReviewReplyCardState extends State<ReviewReplyCard> {
  bool _editing = false, _busy = false, _expanded = false;
  final _text = TextEditingController();

  Map<String, dynamic> get r => widget.review;
  int get _id => r['id'] as int;
  ApiClient get _api => context.read<Session>().api;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  void _edit([String? text]) => setState(() {
        _text.text = text ?? r['reply'] as String? ?? '';
        _editing = true;
      });

  Future<void> _run(Future<void> Function() action) async {
    setState(() => _busy = true);
    try {
      await action();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _draft() => _run(() async {
        final out = await _api.post('/api/reviews/$_id/draft') as Map<String, dynamic>;
        _edit(out['reply'] as String? ?? '');
        await widget.onChanged();
      });

  Future<void> _save() => _run(() async {
        final text = _text.text.trim();
        if (text.isEmpty) return;
        final out = await _api.post('/api/reviews/$_id/post', {'reply': text}) as Map<String, dynamic>;
        if (!mounted) return;
        setState(() => _editing = false);
        out['posted'] == true ? showSuccess(context, out['message'] as String) : ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(out['message'] as String)));
        await widget.onChanged();
      });

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Delete reply?'),
        content: Text(r['reply_status'] == 'published' ? 'This removes your reply from Google. The review moves back to Pending.' : 'This deletes the draft reply.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: const Color(0xFFE5484D)), onPressed: () => Navigator.pop(d, true), child: const Text('Delete')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await _run(() async {
      await _api.delete('/api/reviews/$_id/reply');
      if (mounted) showSuccess(context, 'Reply deleted');
      await widget.onChanged();
    });
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final author = r['author'] as String? ?? 'Customer';
    final status = r['reply_status'] as String;
    final reply = r['reply'] as String?;
    final waitingForManager = status == 'approved' && r['approval_rule'] == 'owner' && (r['rating'] as int) <= 2;
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            CircleAvatar(
              radius: 16,
              backgroundColor: _avatarColours[author.hashCode.abs() % _avatarColours.length],
              child: Text(author.isEmpty ? '?' : author[0].toUpperCase(), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(author, style: const TextStyle(fontWeight: FontWeight.w700, decoration: TextDecoration.underline)),
                Row(children: [
                  for (var i = 1; i <= 5; i++) Icon(i <= (r['rating'] as int) ? Icons.star_rounded : Icons.star_outline_rounded, size: 15, color: const Color(0xFFF2A100)),
                ]),
              ]),
            ),
            Text(timeAgo(parseDate(r['created_at'])), style: t.bodySmall?.copyWith(color: Theme.of(context).hintColor)),
          ]),
          if ((r['text'] as String? ?? '').isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(r['text'] as String)),
          const SizedBox(height: 10),
          if (_editing)
            _editor(context)
          else if (status == 'published' && reply != null)
            _published(context, reply)
          else if (reply != null && status != 'rejected')
            _draftBox(context, reply, waitingForManager)
          else
            Row(children: [
              Expanded(
                child: FilledButton.icon(
                  key: Key('ai-reply-$_id'),
                  onPressed: _busy ? null : _draft,
                  icon: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.auto_awesome, size: 18),
                  label: const Text('Reply with AI'),
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton(onPressed: _busy ? null : () => _edit(''), child: const Text('Write reply')),
            ]),
        ]),
      ),
    );
  }

  Widget _ownerRow(BuildContext context, String when, {bool actions = true}) => Row(children: [
        const CircleAvatar(radius: 12, backgroundColor: Color(0xFFE8457C), child: Text('O', style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700))),
        const SizedBox(width: 8),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Text('Owner', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            Text(when, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Theme.of(context).hintColor)),
          ]),
        ),
        if (actions) ...[
          IconButton(tooltip: 'Delete reply', visualDensity: VisualDensity.compact, icon: const Icon(Icons.delete_outline, size: 20), onPressed: _busy ? null : _delete),
          IconButton(tooltip: 'Edit reply', visualDensity: VisualDensity.compact, icon: const Icon(Icons.edit_outlined, size: 20), onPressed: _busy ? null : () => _edit()),
        ],
      ]);

  Widget _published(BuildContext context, String reply) {
    final kws = (r['keywords_used'] as List? ?? const []).cast<Map<String, dynamic>>();
    final words = {for (final k in kws) ...(k['words'] as List).cast<String>()};
    final t = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _ownerRow(context, 'You replied ${timeAgo(parseDate(r['published_at']))}'),
      if (kws.isNotEmpty) ...[
        const SizedBox(height: 6),
        Table(
          key: Key('keywords-$_id'),
          border: TableBorder.all(color: Theme.of(context).dividerColor, borderRadius: BorderRadius.circular(6)),
          columnWidths: const {0: FlexColumnWidth(2), 1: FlexColumnWidth()},
          children: [
            TableRow(children: [
              for (final h in ['Keyword Used', 'Search Volume'])
                Padding(padding: const EdgeInsets.all(8), child: Text(h, textAlign: TextAlign.center, style: t.labelSmall?.copyWith(fontWeight: FontWeight.w600))),
            ]),
            for (final k in kws)
              TableRow(children: [
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(children: [
                    Icon(Icons.search, size: 14, color: Theme.of(context).hintColor),
                    const SizedBox(width: 6),
                    Expanded(child: Text(k['keyword'] as String, style: t.bodySmall)),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Text(NumberFormat.decimalPattern('en_IN').format(k['volume']), style: t.bodySmall),
                    const Icon(Icons.trending_up, size: 14, color: Color(0xFF1F63C6)),
                  ]),
                ),
              ]),
          ],
        ),
      ],
      const SizedBox(height: 8),
      Text.rich(_bolded(reply, words), key: Key('reply-$_id'), maxLines: _expanded ? null : 4, overflow: _expanded ? null : TextOverflow.ellipsis),
      if (reply.length > 180)
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            style: TextButton.styleFrom(padding: EdgeInsets.zero, visualDensity: VisualDensity.compact, foregroundColor: const Color(0xFFE8457C)),
            onPressed: () => setState(() => _expanded = !_expanded),
            child: Text(_expanded ? 'Show less' : 'Read more'),
          ),
        ),
    ]);
  }

  /// The reply with the keyword words in bold, like Dhanda's.
  TextSpan _bolded(String text, Set<String> words) {
    if (words.isEmpty) return TextSpan(text: text);
    final spans = <TextSpan>[];
    final re = RegExp(r'[\p{L}\p{N}]+', unicode: true);
    var last = 0;
    for (final m in re.allMatches(text)) {
      if (words.contains(m.group(0)!.toLowerCase())) {
        if (m.start > last) spans.add(TextSpan(text: text.substring(last, m.start)));
        spans.add(TextSpan(text: m.group(0), style: const TextStyle(fontWeight: FontWeight.w800)));
        last = m.end;
      }
    }
    if (last < text.length) spans.add(TextSpan(text: text.substring(last)));
    return TextSpan(children: spans);
  }

  Widget _draftBox(BuildContext context, String reply, bool waiting) {
    final t = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _ownerRow(context, waiting ? 'Saved — your account manager will post it' : 'AI suggested reply · not posted yet'),
      const SizedBox(height: 6),
      Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: .5), borderRadius: BorderRadius.circular(8)),
        child: Text(reply, style: t.bodyMedium),
      ),
      if (!waiting) ...[
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _busy ? null : () => _edit(), child: const Text('Edit'))),
          const SizedBox(width: 8),
          Expanded(
            child: FilledButton(
              key: Key('post-$_id'),
              onPressed: _busy
                  ? null
                  : () {
                      _text.text = reply;
                      _save();
                    },
              child: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('Post reply'),
            ),
          ),
        ]),
      ],
    ]);
  }

  Widget _editor(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        TextField(
          key: Key('reply-editor-$_id'),
          controller: _text,
          minLines: 4,
          maxLines: 12,
          maxLength: 4000,
          decoration: const InputDecoration(hintText: 'Write your reply…'),
        ),
        Row(mainAxisAlignment: MainAxisAlignment.end, children: [
          OutlinedButton(onPressed: _busy ? null : () => setState(() => _editing = false), child: const Text('Cancel')),
          const SizedBox(width: 8),
          FilledButton(
            key: Key('save-$_id'),
            style: FilledButton.styleFrom(backgroundColor: _navy),
            onPressed: _busy ? null : _save,
            child: _busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Save'),
          ),
        ]),
      ]);
}
