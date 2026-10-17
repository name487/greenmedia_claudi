import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../widgets/common.dart';
import 'items_screen.dart';
import 'shared.dart';

Color hexColour(String h) => Color(int.parse('FF${h.replaceFirst('#', '')}', radix: 16));

/// A template's intro line with the business's own name and city filled in.
String introLine(String l, Map<String, dynamic>? business, String fallbackName) {
  final name = (business?['name'] as String?) ?? fallbackName;
  final city = (business?['city'] as String?) ?? '';
  return l.replaceAll('{business}', name).replaceAll('{city}', city.isEmpty ? 'town' : city).toUpperCase();
}

// ---------- 1. pick a template ----------

class VideoTemplatesScreen extends StatefulWidget {
  const VideoTemplatesScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<VideoTemplatesScreen> createState() => _VideoTemplatesScreenState();
}

class _VideoTemplatesScreenState extends State<VideoTemplatesScreen> {
  Map<String, dynamic>? _business;
  late final Future<List<Map<String, dynamic>>> _templates = () async {
    final api = context.read<Session>().api;
    final r = await Future.wait([api.get('/api/video-templates'), api.get('/api/clients/${widget.clientId}/ai-posts/overview')]);
    _business = (r[1] as Map)['business'] as Map<String, dynamic>?;
    return ((r[0] as Map)['templates'] as List).cast<Map<String, dynamic>>();
  }();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: navyBar('Select video template', subtitle: context.read<Session>().me!.clientName),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _templates,
        builder: (context, snap) {
          if (snap.hasError) return EmptyState('${snap.error}');
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          return GridView.builder(
            padding: const EdgeInsets.all(12),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 2, mainAxisSpacing: 10, crossAxisSpacing: 10, childAspectRatio: .62),
            itemCount: snap.data!.length,
            itemBuilder: (context, i) {
              final t = snap.data![i];
              return InkWell(
                key: Key('template-${t['key']}'),
                borderRadius: BorderRadius.circular(10),
                onTap: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => TemplatePreviewScreen(clientId: widget.clientId, template: t))),
                child: Card(
                  margin: EdgeInsets.zero,
                  clipBehavior: Clip.antiAlias,
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Expanded(child: _TemplateThumb(t, business: _business)),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(t['name'] as String, style: const TextStyle(fontWeight: FontWeight.w700)),
                        Text(t['tagline'] as String, maxLines: 2, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodySmall),
                        const SizedBox(height: 4),
                        const Text('Included in your plan', style: TextStyle(color: green, fontSize: 11, fontWeight: FontWeight.w600)),
                      ]),
                    ),
                  ]),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class _TemplateThumb extends StatelessWidget {
  const _TemplateThumb(this.t, {this.business});
  final Map<String, dynamic> t;
  final Map<String, dynamic>? business;

  @override
  Widget build(BuildContext context) {
    final bg = hexColour(t['bg'] as String), accent = hexColour(t['accent'] as String);
    final lines = (t['intro'] as List).cast<String>();
    return Container(
      color: bg,
      padding: const EdgeInsets.all(10),
      child: Stack(children: [
        Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (final (i, l) in lines.indexed)
              Text(introLine(l, business, context.read<Session>().me?.clientName ?? ''), textAlign: TextAlign.center,
                  style: TextStyle(color: i.isOdd ? accent : Colors.white, fontWeight: FontWeight.w900, fontSize: 15)),
          ]),
        ),
        const Positioned(
            right: 0, bottom: 0, child: CircleAvatar(radius: 14, backgroundColor: Colors.black38, child: Icon(Icons.play_arrow, color: Colors.white, size: 18))),
      ]),
    );
  }
}

// ---------- 2. preview with the business's own products ----------

class TemplatePreviewScreen extends StatefulWidget {
  const TemplatePreviewScreen({super.key, required this.clientId, required this.template});
  final int clientId;
  final Map<String, dynamic> template;

  @override
  State<TemplatePreviewScreen> createState() => _TemplatePreviewScreenState();
}

class _TemplatePreviewScreenState extends State<TemplatePreviewScreen> {
  List<Map<String, dynamic>>? _items;
  Map<String, dynamic>? _business;
  int _frame = 0;
  Timer? _timer;
  bool _busy = false;

  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(milliseconds: 1600), (_) {
      if (mounted) setState(() => _frame++);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await Future.wait([_api.get('/api/clients/${widget.clientId}/items'), _api.get('/api/clients/${widget.clientId}/ai-posts/overview')]);
    if (!mounted) return;
    setState(() {
      _items = ((r[0] as Map)['items'] as List).cast<Map<String, dynamic>>();
      _business = (r[1] as Map)['business'] as Map<String, dynamic>?;
    });
  }

  Future<void> _generate() async {
    setState(() => _busy = true);
    try {
      final post = await _api.post('/api/clients/${widget.clientId}/ai-posts/video', {'template': widget.template['key']}) as Map<String, dynamic>;
      if (!mounted) return;
      await Navigator.pushReplacement(context, MaterialPageRoute<void>(builder: (_) => GeneratingScreen(clientId: widget.clientId, postId: post['id'] as int)));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.template;
    final items = _items ?? const [];
    final withPhoto = items.where((i) => (i['image_url'] as String? ?? '').isNotEmpty).take(4).toList();
    final frames = 2 + math.max<int>(1, withPhoto.length);
    final f = _frame % frames;
    final bg = hexColour(t['bg'] as String), accent = hexColour(t['accent'] as String);
    final name = (_business?['name'] as String?) ?? context.read<Session>().me!.clientName ?? '';
    Widget frame;
    if (f == 0) {
      frame = Container(
        color: bg,
        alignment: Alignment.center,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final (i, l) in (t['intro'] as List).cast<String>().indexed)
            Text(introLine(l, _business, name), textAlign: TextAlign.center,
                style: TextStyle(color: i.isOdd ? accent : Colors.white, fontWeight: FontWeight.w900, fontSize: 30)),
        ]),
      );
    } else if (f == frames - 1) {
      frame = _EndCard(business: _business ?? {'name': name}, bg: bg, accent: accent);
    } else if (withPhoto.isEmpty) {
      frame = Container(color: Colors.black, alignment: Alignment.center, child: const Text('Your product photo', style: TextStyle(color: Colors.white70)));
    } else {
      frame = TweenAnimationBuilder<double>(
        key: ValueKey(_frame),
        tween: Tween(begin: 1, end: 1.12),
        duration: const Duration(milliseconds: 1600),
        builder: (_, s, child) => Transform.scale(scale: s, child: child),
        child: Image.network(withPhoto[f - 1]['image_url'] as String, fit: BoxFit.cover, width: double.infinity, height: double.infinity,
            errorBuilder: (_, _, _) => const ColoredBox(color: Colors.black, child: Center(child: Icon(Icons.image_outlined, color: Colors.white54, size: 40)))),
      );
    }
    return Scaffold(
      appBar: navyBar('Preview video', subtitle: name),
      body: Column(children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Center(
              child: AspectRatio(
                aspectRatio: 9 / 16,
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Stack(fit: StackFit.expand, children: [
                    AnimatedSwitcher(duration: const Duration(milliseconds: 300), child: KeyedSubtree(key: ValueKey(f), child: frame)),
                    IgnorePointer(
                      child: Center(
                        child: Transform.rotate(
                          angle: -.5,
                          child: Text('Preview', style: TextStyle(fontSize: 52, fontWeight: FontWeight.w800, color: Colors.white.withValues(alpha: .35))),
                        ),
                      ),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        ),
        if (_items != null && withPhoto.isEmpty)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(children: [
              const Expanded(child: Text('Your video is made from your products — add one with a photo first.')),
              TextButton(
                onPressed: () async {
                  await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => AddItemScreen(clientId: widget.clientId)));
                  _load();
                },
                child: const Text('Add product'),
              ),
            ]),
          ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
            child: GradientButton(
              key: const Key('generate-video'),
              label: 'Generate Viral Video',
              icon: Icons.auto_awesome,
              busy: _busy,
              onPressed: withPhoto.isEmpty ? null : _generate,
            ),
          ),
        ),
      ]),
    );
  }
}

class _EndCard extends StatelessWidget {
  const _EndCard({required this.business, required this.bg, required this.accent});
  final Map<String, dynamic> business;
  final Color bg, accent;

  @override
  Widget build(BuildContext context) {
    final name = business['name'] as String? ?? '';
    return Container(
      color: bg,
      padding: const EdgeInsets.fromLTRB(24, 60, 24, 40),
      child: Container(
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
        padding: const EdgeInsets.all(16),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          CircleAvatar(radius: 32, backgroundColor: bg, child: Text(name.isEmpty ? '·' : name.split(' ').take(2).map((w) => w[0]).join().toUpperCase(),
              style: TextStyle(color: accent, fontSize: 22, fontWeight: FontWeight.w800))),
          const SizedBox(height: 14),
          Text(name, textAlign: TextAlign.center, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: Colors.black87)),
          if ((business['phone'] as String? ?? '').isNotEmpty) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(border: Border.all(color: Colors.black87), borderRadius: BorderRadius.circular(99)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.call, size: 14, color: Colors.black87),
                const SizedBox(width: 4),
                Text(business['phone'] as String, style: const TextStyle(color: Colors.black87, fontWeight: FontWeight.w600)),
              ]),
            ),
          ],
          if ((business['address'] as String? ?? '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(business['address'] as String, textAlign: TextAlign.center, style: const TextStyle(fontSize: 11, color: Colors.black54)),
            ),
        ]),
      ),
    );
  }
}

// ---------- 3. the Content Agent at work ----------

class GeneratingScreen extends StatefulWidget {
  const GeneratingScreen({super.key, required this.clientId, required this.postId});
  final int clientId, postId;

  @override
  State<GeneratingScreen> createState() => _GeneratingScreenState();
}

class _GeneratingScreenState extends State<GeneratingScreen> with SingleTickerProviderStateMixin {
  Map<String, dynamic>? _post;
  Timer? _poll;
  late final AnimationController _shimmer = AnimationController(vsync: this, duration: const Duration(milliseconds: 1400))..repeat();

  @override
  void initState() {
    super.initState();
    _check();
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _check());
  }

  @override
  void dispose() {
    _poll?.cancel();
    _shimmer.dispose();
    super.dispose();
  }

  Future<void> _check() async {
    try {
      final p = await context.read<Session>().api.get('/api/clients/${widget.clientId}/ai-posts/${widget.postId}') as Map<String, dynamic>;
      if (!mounted) return;
      setState(() => _post = p);
      if (p['status'] != 'generating') {
        _poll?.cancel();
        if (p['status'] != 'gen_failed') {
          await Navigator.pushReplacement(context, MaterialPageRoute<void>(builder: (_) => PostReviewScreen(clientId: widget.clientId, post: p)));
        }
      }
    } on ApiException {
      // keep trying
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = _post;
    final steps = ((p?['gen_steps'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final done = p?['gen_progress'] as int? ?? 0;
    final failed = p?['status'] == 'gen_failed';
    final step = steps.isEmpty ? null : steps[math.min(done, steps.length - 1)];
    final label = step == null ? 'Getting started' : done >= steps.length ? '${steps.last['done']} ✓' : '${step['doing']}…';
    return Scaffold(
      appBar: navyBar('Creating your video'),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(children: [
            if (failed) ...[
              const SizedBox(height: 40),
              const Icon(Icons.error_outline, size: 48, color: red),
              const SizedBox(height: 10),
              const Text('We couldn’t create this video', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              Padding(padding: const EdgeInsets.all(8), child: Text(p?['gen_error'] as String? ?? '', textAlign: TextAlign.center)),
              FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Back')),
            ] else ...[
              Text('Content Agent is creating the best video for your business…', textAlign: TextAlign.center,
                  style: TextStyle(color: const Color(0xFFB04DE8).withValues(alpha: .9), fontWeight: FontWeight.w600)),
              const SizedBox(height: 16),
              Expanded(
                child: AnimatedBuilder(
                  animation: _shimmer,
                  builder: (context, _) {
                    final base = Theme.of(context).dividerColor.withValues(alpha: .25);
                    final hi = Theme.of(context).dividerColor.withValues(alpha: .08);
                    final shade = LinearGradient(
                        colors: [base, hi, base], stops: [(_shimmer.value - .3).clamp(0, 1), _shimmer.value, (_shimmer.value + .3).clamp(0, 1)]);
                    Widget bar(double w, double h) => Container(width: w, height: h, margin: const EdgeInsets.only(bottom: 8),
                        decoration: BoxDecoration(gradient: shade, borderRadius: BorderRadius.circular(6)));
                    return Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(14)),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Center(
                          child: Container(
                            width: 160,
                            height: 240,
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(gradient: shade, borderRadius: BorderRadius.circular(10)),
                            child: Text(label, key: const Key('gen-step'), style: const TextStyle(fontSize: 12)),
                          ),
                        ),
                        const SizedBox(height: 16),
                        bar(80, 10),
                        bar(double.infinity, 8),
                        bar(double.infinity, 8),
                        bar(200, 8),
                        const Spacer(),
                        LinearProgressIndicator(value: steps.isEmpty ? null : done / steps.length, minHeight: 4),
                        const SizedBox(height: 6),
                        Text('Step ${math.min(done + 1, math.max(1, steps.length))} of ${math.max(1, steps.length)}', style: Theme.of(context).textTheme.bodySmall),
                      ]),
                    );
                  },
                ),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                key: const Key('notify-me'),
                icon: const Icon(Icons.notifications_none),
                label: const Text('Notify me when it’s ready'),
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('We’ll keep working — find it under Scheduled → Pending.')));
                  Navigator.pop(context);
                },
              ),
            ],
          ]),
        ),
      ),
    );
  }
}

// ---------- 4. review: approve or reject ----------

class PostReviewScreen extends StatefulWidget {
  const PostReviewScreen({super.key, required this.clientId, required this.post});
  final int clientId;
  final Map<String, dynamic> post;

  @override
  State<PostReviewScreen> createState() => _PostReviewScreenState();
}

class _PostReviewScreenState extends State<PostReviewScreen> {
  bool _more = false, _busy = false;

  Future<void> _reject() async {
    setState(() => _busy = true);
    final ok = await runAction(context, (api) => api.post('/api/clients/${widget.clientId}/ai-posts/${widget.post['id']}/reject'), success: 'Post rejected');
    if (mounted) setState(() => _busy = false);
    if (ok && mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.post;
    final video = p['media_type'] == 'video';
    final caption = '${p['caption']}\n\n${(p['hashtags'] as List).join(' ')}'.trim();
    return Scaffold(
      appBar: navyBar(video ? 'Your video is ready' : 'Your post is ready'),
      body: Column(children: [
        Expanded(
          child: ListView(padding: const EdgeInsets.all(12), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Icon(Icons.chat_bubble, size: 18, color: Color(0xFF1F63C6)),
                    const SizedBox(width: 8),
                    Expanded(child: Text(caption, key: const Key('review-caption'), maxLines: _more ? null : 3, overflow: _more ? null : TextOverflow.ellipsis)),
                  ]),
                  TextButton(onPressed: () => setState(() => _more = !_more), child: Text(_more ? 'Show less' : 'Show more')),
                ]),
              ),
            ),
            PostMedia(post: p, height: 460),
          ]),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
            child: Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(foregroundColor: red, side: const BorderSide(color: red), minimumSize: const Size.fromHeight(46)),
                  icon: const Icon(Icons.cancel_outlined),
                  label: Text(video ? 'Reject Video' : 'Reject Post'),
                  onPressed: _busy ? null : _reject,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  key: const Key('approve-post'),
                  style: OutlinedButton.styleFrom(foregroundColor: green, side: const BorderSide(color: green), minimumSize: const Size.fromHeight(46)),
                  icon: const Icon(Icons.check_circle_outline),
                  label: Text(video ? 'Approve Video' : 'Approve Post'),
                  onPressed: _busy
                      ? null
                      : () => Navigator.pushReplacement(
                          context, MaterialPageRoute<void>(builder: (_) => ScheduleScreen(clientId: widget.clientId, postId: p['id'] as int))),
                ),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}

// ---------- 5. pick date & time, then schedule ----------

class ScheduleScreen extends StatefulWidget {
  const ScheduleScreen({super.key, required this.clientId, required this.postId});
  final int clientId, postId;

  @override
  State<ScheduleScreen> createState() => _ScheduleScreenState();
}

class _ScheduleScreenState extends State<ScheduleScreen> {
  DateTime? _day;
  DateTime _month = DateTime(_ist(DateTime.now()).year, _ist(DateTime.now()).month);
  Set<String> _taken = {};
  int _hour = 7, _minute = 0;
  bool _pm = false, _busy = false, _finding = true;

  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    _findFree();
  }

  Future<void> _findFree() async {
    try {
      final s = await _api.get('/api/clients/${widget.clientId}/ai-posts/free-slot') as Map<String, dynamic>;
      final at = _ist(DateTime.parse(s['suggested'] as String));
      if (!mounted) return;
      setState(() {
        _day = DateTime(at.year, at.month, at.day);
        _month = DateTime(at.year, at.month);
        _hour = at.hour % 12 == 0 ? 12 : at.hour % 12;
        _pm = at.hour >= 12;
        _minute = at.minute;
        _taken = (s['scheduled_dates'] as List).cast<String>().toSet();
        _finding = false;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _finding = false);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _month0(int delta) async {
    final m = DateTime(_month.year, _month.month + delta);
    setState(() => _month = m);
    try {
      final s = await _api.get('/api/clients/${widget.clientId}/ai-posts/free-slot', {'month': DateFormat('yyyy-MM').format(m)}) as Map<String, dynamic>;
      if (mounted) setState(() => _taken = (s['scheduled_dates'] as List).cast<String>().toSet());
    } on ApiException {
      // calendar marks are a hint only
    }
  }

  // Posting times are the business's own (India) wall-clock time, whatever zone the phone is in.
  static const _istOffset = Duration(hours: 5, minutes: 30);
  static DateTime _ist(DateTime t) => t.toUtc().add(_istOffset);
  DateTime get _when => DateTime(_day!.year, _day!.month, _day!.day, (_hour % 12) + (_pm ? 12 : 0), _minute);
  DateTime get _whenUtc => DateTime.utc(_when.year, _when.month, _when.day, _when.hour, _when.minute).subtract(_istOffset);

  Future<void> _schedule() async {
    setState(() => _busy = true);
    try {
      await _api.post('/api/clients/${widget.clientId}/ai-posts/${widget.postId}/approve', {'scheduled_at': _whenUtc.toIso8601String()});
      if (!mounted) return;
      final label = DateFormat('d MMMM, h:mm a').format(_when);
      await Navigator.pushReplacement(context, MaterialPageRoute<void>(builder: (_) => ScheduledScreen(label: label)));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final first = _month;
    final days = DateTime(first.year, first.month + 1, 0).day;
    final today = _ist(DateTime.now());
    return Scaffold(
      appBar: navyBar('Select Date & Time'),
      body: Column(children: [
        Expanded(
          child: ListView(padding: const EdgeInsets.all(12), children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(children: [
                  Row(children: [
                    IconButton(tooltip: 'Previous month', onPressed: () => _month0(-1), icon: const Icon(Icons.chevron_left)),
                    Expanded(child: Text(DateFormat('MMMM yyyy').format(_month), textAlign: TextAlign.center, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
                    IconButton(tooltip: 'Next month', onPressed: () => _month0(1), icon: const Icon(Icons.chevron_right)),
                  ]),
                  GridView.count(
                    crossAxisCount: 7,
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    childAspectRatio: 1.1,
                    children: [
                      for (final d in const ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) Center(child: Text(d, style: t.labelSmall)),
                      for (var i = 0; i < first.weekday - 1; i++) const SizedBox.shrink(),
                      for (var d = 1; d <= days; d++)
                        Builder(builder: (context) {
                          final date = DateTime(first.year, first.month, d);
                          final past = date.isBefore(DateTime(today.year, today.month, today.day));
                          final taken = _taken.contains(DateFormat('yyyy-MM-dd').format(date));
                          final selected = _day == date;
                          return InkWell(
                            key: Key('day-$d'),
                            onTap: past ? null : () => setState(() => _day = date),
                            customBorder: const CircleBorder(),
                            child: Center(
                              child: Container(
                                width: 32,
                                height: 32,
                                alignment: Alignment.center,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: selected ? navy : taken ? green : null,
                                ),
                                child: Text('$d',
                                    style: TextStyle(color: selected || taken ? Colors.white : past ? Theme.of(context).disabledColor : null,
                                        fontWeight: selected ? FontWeight.w700 : null)),
                              ),
                            ),
                          );
                        }),
                    ],
                  ),
                  Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Container(width: 10, height: 10, decoration: const BoxDecoration(color: green, shape: BoxShape.circle)),
                    const SizedBox(width: 6),
                    Text('Already Scheduled', style: t.bodySmall),
                  ]),
                ]),
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: _Wheel(values: [for (var h = 1; h <= 12; h++) h.toString().padLeft(2, '0')], index: _hour - 1, onChanged: (i) => setState(() => _hour = i + 1))),
              const SizedBox(width: 8),
              Expanded(child: _Wheel(values: [for (var m = 0; m < 60; m += 5) m.toString().padLeft(2, '0')], index: _minute ~/ 5, onChanged: (i) => setState(() => _minute = i * 5))),
              const SizedBox(width: 8),
              Expanded(child: _Wheel(values: const ['AM', 'PM'], index: _pm ? 1 : 0, onChanged: (i) => setState(() => _pm = i == 1))),
            ]),
          ]),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
            child: GradientButton(
              key: const Key('schedule-post'),
              label: _finding ? 'Finding a free date…' : _busy ? 'Scheduling…' : 'Schedule for ${DateFormat('d MMMM').format(_day ?? today)}',
              icon: Icons.event_available,
              busy: _finding || _busy,
              onPressed: _day == null ? null : _schedule,
            ),
          ),
        ),
      ]),
    );
  }
}

class _Wheel extends StatefulWidget {
  const _Wheel({required this.values, required this.index, required this.onChanged});
  final List<String> values;
  final int index;
  final ValueChanged<int> onChanged;

  @override
  State<_Wheel> createState() => _WheelState();
}

class _WheelState extends State<_Wheel> {
  late final _c = FixedExtentScrollController(initialItem: widget.index);

  @override
  void didUpdateWidget(covariant _Wheel old) {
    super.didUpdateWidget(old);
    // jumping fires onSelectedItemChanged, which sets the parent's state — not allowed mid-build
    if (old.index != widget.index) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _c.hasClients && _c.selectedItem != widget.index) _c.jumpToItem(widget.index);
      });
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Container(
        height: 120,
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(12)),
        child: ListWheelScrollView.useDelegate(
          controller: _c,
          itemExtent: 38,
          physics: const FixedExtentScrollPhysics(),
          onSelectedItemChanged: widget.onChanged,
          childDelegate: ListWheelChildBuilderDelegate(
            childCount: widget.values.length,
            builder: (_, i) => Center(child: Text(widget.values[i], style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700))),
          ),
        ),
      );
}

class ScheduledScreen extends StatefulWidget {
  const ScheduledScreen({super.key, required this.label});
  final String label;

  @override
  State<ScheduledScreen> createState() => _ScheduledScreenState();
}

class _ScheduledScreenState extends State<ScheduledScreen> {
  Timer? _close;

  @override
  void initState() {
    super.initState();
    _close = Timer(const Duration(milliseconds: 1600), () {
      if (mounted) Navigator.of(context).pop(true);
    });
  }

  @override
  void dispose() {
    _close?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final label = widget.label;
    return Scaffold(
      body: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const CircleAvatar(radius: 34, backgroundColor: green, child: Icon(Icons.check, color: Colors.white, size: 40)),
          const SizedBox(height: 16),
          const Text('Successfully Scheduled', key: Key('scheduled-ok'), style: TextStyle(color: green, fontSize: 20, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text('Post scheduled for $label'),
        ]),
      ),
    );
  }
}
