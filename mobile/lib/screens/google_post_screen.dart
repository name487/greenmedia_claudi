import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'ai_post/ai_post_screen.dart' show highlight;
import 'ai_post/shared.dart';
import 'keyword_planner_screen.dart';

/// Google Post (business owners): the text-only posts the Content Agent writes for the Google profile every day, each
/// built around one of the business's keywords. Posts wait for approval unless "Post automatically" is on.
class GooglePostScreen extends StatefulWidget {
  const GooglePostScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<GooglePostScreen> createState() => _GooglePostScreenState();
}

class _GooglePostScreenState extends State<GooglePostScreen> {
  Map<String, dynamic>? _d;
  String? _error;
  bool _writing = false;

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await _api.get('$_base/google-posts') as Map<String, dynamic>;
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

  Future<void> _settings(Map<String, dynamic> body) async {
    try {
      final d = await _api.put('$_base/google-posts/settings', body) as Map<String, dynamic>;
      if (mounted) setState(() => _d = d);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    }
  }

  Future<void> _toggleAuto(bool on) async {
    if (on) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (d) => AlertDialog(
          title: const Text('Post automatically?'),
          content: const Text('Google posts will go out on their day without asking you first. You can still edit or reject '
              'any post before then, and turn this off any time.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
            FilledButton(key: const Key('gp-auto-confirm'), onPressed: () => Navigator.pop(d, true), child: const Text('Turn on')),
          ],
        ),
      );
      if (ok != true) return;
    }
    await _settings({'auto': on});
  }

  Future<void> _pickTime(String hhmm) async {
    final p = hhmm.split(':');
    final t = await showTimePicker(context: context, initialTime: TimeOfDay(hour: int.parse(p[0]), minute: int.parse(p[1])));
    if (t != null) await _settings({'time': '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}'});
  }

  Future<void> _writeNow() async {
    setState(() => _writing = true);
    try {
      final p = await _api.post('$_base/google-posts/generate', {}) as Map<String, dynamic>;
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Post written for ${_day(p)} — “${p['keyword']}”')));
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _writing = false);
    }
  }

  Future<void> _planner() async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => KeywordPlannerScreen(clientId: widget.clientId)));
    if (mounted) _load();
  }

  Future<void> _approve(Map<String, dynamic> p) async {
    // Its own day and time, or a few minutes from now if that has passed
    final soon = DateTime.now().toUtc().add(const Duration(minutes: 10));
    final at = p['scheduled_at'] == null ? soon : DateTime.parse(p['scheduled_at'] as String).toUtc();
    final when = at.isBefore(soon) ? soon : at;
    final ok = await runAction(context, (api) => api.post('$_base/ai-posts/${p['id']}/approve', {'scheduled_at': when.toIso8601String()}),
        success: 'Approved — it posts on ${_day(p)}');
    if (ok) _load();
  }

  Future<void> _reject(Map<String, dynamic> p) async {
    final ok = await runAction(context, (api) => api.post('$_base/ai-posts/${p['id']}/reject'), success: 'Post rejected');
    if (ok) _load();
  }

  Future<void> _edit(Map<String, dynamic> p) async {
    final text = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _EditSheet(text: p['text'] as String, keyword: p['keyword'] as String),
    );
    if (text == null || text == p['text'] || !mounted) return;
    final ok = await runAction(context, (api) => api.patch('$_base/google-posts/${p['id']}', {'text': text}), success: 'Post updated');
    if (ok) _load();
  }

  void _help() => showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (_) => const SafeArea(
          child: Padding(
            padding: EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('How Google Post works', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              SizedBox(height: 10),
              Text('1. Add the searches you want to be found for in Optimise keywords.'),
              Text('2. Every day the Content Agent writes a short Google post around one of them, taking turns.'),
              Text('3. Approve it (or edit it) and it posts on your Google profile on its day. With Post automatically on, '
                  'it goes out without asking.'),
              Text('4. Regular posts with your keywords help Google show your profile for those searches.'),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final d = _d;
    final me = context.read<Session>().me!;
    return Scaffold(
      appBar: navyBar('Google Post', subtitle: me.clientName, actions: [IconButton(tooltip: 'How it works', icon: const Icon(Icons.help_outline), onPressed: _help)]),
      body: d == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : Column(children: [
              Expanded(child: RefreshIndicator(onRefresh: _load, child: _list(d))),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
                  child: Row(children: [
                    Expanded(child: GradientButton(key: const Key('optimise-keywords'), label: 'Optimise keywords', icon: Icons.tune, onPressed: _planner)),
                    if (d['can_create'] == true) ...[
                      const SizedBox(width: 10),
                      SizedBox(
                        width: 50,
                        height: 50,
                        child: IconButton.filled(
                          key: const Key('gp-write-now'),
                          tooltip: 'Write a post now',
                          style: IconButton.styleFrom(backgroundColor: navy),
                          onPressed: _writing ? null : _writeNow,
                          icon: _writing
                              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                              : const Icon(Icons.edit_note, color: Colors.white),
                        ),
                      ),
                    ],
                  ]),
                ),
              ),
            ]),
    );
  }

  Widget _list(Map<String, dynamic> d) {
    final s = d['settings'] as Map<String, dynamic>;
    final items = (d['items'] as List).cast<Map<String, dynamic>>();
    final kws = (d['keywords'] as List).cast<Map<String, dynamic>>();
    final groups = <(String, String)>[
      ('pending', 'Waiting for your approval'),
      ('approved', 'Scheduled'),
      ('posted', 'Posted'),
      ('not_posted', 'Not posted'),
      ('rejected', 'Rejected'),
    ];
    return ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 16), children: [
      _KeywordsCard(keywords: kws, count: d['keyword_count'] as int, onTap: _planner),
      const SizedBox(height: 10),
      if (d['connected'] != true)
        Card(
          color: Colors.orange.shade50,
          child: const ListTile(
            leading: Icon(Icons.link_off, color: Colors.orange),
            title: Text('Google profile not connected'),
            subtitle: Text('Posts are written, but can only go out once your Google Business Profile is connected. Ask your account manager.'),
          ),
        ),
      Card(
        child: Column(children: [
          SwitchListTile(
            key: const Key('gp-daily'),
            value: s['daily'] as bool,
            onChanged: d['can_create'] == true ? (v) => _settings({'daily': v}) : null,
            title: const Text('Post daily on Google'),
            subtitle: Text(s['daily'] == true ? 'A new post every day at ${_time(s['time'] as String)}' : 'Off — use ✎ to write one yourself'),
            secondary: const Icon(Icons.event_repeat),
          ),
          if (s['daily'] == true && d['can_create'] == true)
            ListTile(
              key: const Key('gp-time'),
              dense: true,
              leading: const SizedBox(width: 24),
              title: const Text('Posting time'),
              trailing: Text(_time(s['time'] as String), style: const TextStyle(fontWeight: FontWeight.w600)),
              onTap: () => _pickTime(s['time'] as String),
            ),
          if (d['can_approve'] == true)
            SwitchListTile(
              key: const Key('gp-auto'),
              value: s['auto'] as bool,
              onChanged: _toggleAuto,
              title: const Text('Post automatically'),
              subtitle: Text(s['auto'] == true ? 'On${(s['auto_by'] as String).isEmpty ? '' : ' (by ${s['auto_by']})'} — posts go out without asking'
                  : 'Off — each post waits for your approval'),
              secondary: const Icon(Icons.verified_outlined),
            ),
        ]),
      ),
      const SizedBox(height: 6),
      if (items.isEmpty)
        const _NoPosts()
      else
        for (final (g, title) in groups)
          if (items.any((p) => p['group'] == g)) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 12, 4, 6),
              child: Text(title.toUpperCase(), style: Theme.of(context).textTheme.labelMedium?.copyWith(letterSpacing: .6, color: Colors.black54)),
            ),
            for (final p in items.where((p) => p['group'] == g))
              _PostCard(
                post: p,
                canApprove: d['can_approve'] == true,
                canEdit: d['can_create'] == true,
                onApprove: () => _approve(p),
                onReject: () => _reject(p),
                onEdit: () => _edit(p),
              ),
          ],
    ]);
  }
}

String _time(String hhmm) {
  final p = hhmm.split(':');
  return DateFormat('h:mm a').format(DateTime(2000, 1, 1, int.parse(p[0]), int.parse(p[1])));
}

/// The search phrase in blue wherever it appears whole; single words only if it doesn't (so "Dental" in the business
/// name isn't marked when the post says "dental clinic near me").
TextSpan _highlightPhrase(String text, String keyword) {
  final at = RegExp(RegExp.escape(keyword), caseSensitive: false).allMatches(text).toList();
  if (keyword.isEmpty || at.isEmpty) return highlight(text, [{'keyword': keyword}]);
  final spans = <TextSpan>[];
  var last = 0;
  for (final m in at) {
    spans.add(TextSpan(text: text.substring(last, m.start)));
    spans.add(TextSpan(text: m.group(0), style: const TextStyle(color: Color(0xFF1F63C6), fontWeight: FontWeight.w600)));
    last = m.end;
  }
  spans.add(TextSpan(text: text.substring(last)));
  return TextSpan(children: spans);
}

String _day(Map<String, dynamic> p) => DateFormat('EEE, d MMM').format(DateTime.parse(p['day'] as String));

class _KeywordsCard extends StatelessWidget {
  const _KeywordsCard({required this.keywords, required this.count, required this.onTap});
  final List<Map<String, dynamic>> keywords;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      key: const Key('gp-keywords-card'),
      margin: EdgeInsets.zero,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Icon(Icons.lightbulb_outline),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Google works best with keywords', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text('Using your keywords we post daily on your Google Profile', style: t.bodySmall),
                ]),
              ),
            ]),
            const SizedBox(height: 10),
            if (count == 0)
              Text('Add your keywords to start — tap here', style: t.bodySmall?.copyWith(color: red, fontWeight: FontWeight.w600))
            else
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final k in keywords.take(3)) Chip(visualDensity: VisualDensity.compact, label: Text(k['keyword'] as String)),
                if (count > 3) Chip(visualDensity: VisualDensity.compact, label: Text('+${count - 3} more')),
              ]),
          ]),
        ),
      ),
    );
  }
}

class _NoPosts extends StatelessWidget {
  const _NoPosts();

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 24),
        child: Column(children: [
          Icon(Icons.send_rounded, size: 64, color: Colors.blueGrey.shade300),
          const SizedBox(height: 14),
          const Text('No text posts yet', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          const Text('Text-only posts the Content Agent publishes for you will appear here.', textAlign: TextAlign.center,
              style: TextStyle(color: Colors.black54)),
        ]),
      );
}

class _PostCard extends StatelessWidget {
  const _PostCard({required this.post, required this.canApprove, required this.canEdit, required this.onApprove, required this.onReject,
      required this.onEdit});
  final Map<String, dynamic> post;
  final bool canApprove, canEdit;
  final VoidCallback onApprove, onReject, onEdit;

  @override
  Widget build(BuildContext context) {
    final p = post;
    final t = Theme.of(context).textTheme;
    final (status, colour) = switch (p['group']) {
      'pending' => ('Needs approval', const Color(0xFFE08A1E)),
      'approved' => (p['auto_approved'] == true ? 'Posting automatically' : 'Approved', green),
      'posted' => ('Posted', green),
      'rejected' => ('Rejected', red),
      _ => ('Not posted', red),
    };
    final when = p['group'] == 'posted' && p['published_at'] != null
        ? DateFormat('EEE, d MMM · h:mm a').format(DateTime.parse(p['published_at'] as String).toLocal())
        : _day(p);
    final open = p['group'] == 'pending' || p['group'] == 'approved';
    return Card(
      key: Key('gp-post-${p['id']}'),
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.storefront_outlined, size: 18, color: Color(0xFF1F63C6)),
            const SizedBox(width: 6),
            Expanded(child: Text(when, style: t.labelLarge)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(color: colour.withValues(alpha: .12), borderRadius: BorderRadius.circular(99)),
              child: Text(status, style: TextStyle(color: colour, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
          ]),
          const SizedBox(height: 8),
          Text.rich(_highlightPhrase(p['text'] as String, p['keyword'] as String), key: Key('gp-text-${p['id']}')),
          const SizedBox(height: 8),
          Row(children: [
            const Icon(Icons.search, size: 16, color: Colors.black54),
            const SizedBox(width: 4),
            Expanded(
              child: Text(
                (p['volume'] as int) > 0 ? '${p['keyword']} · ${NumberFormat.decimalPattern('en_IN').format(p['volume'])} searches/month' : '${p['keyword']}',
                style: t.bodySmall,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ]),
          if ((p['error'] as String).isNotEmpty && p['group'] == 'not_posted')
            Padding(padding: const EdgeInsets.only(top: 6), child: Text(p['error'] as String, style: t.bodySmall?.copyWith(color: red))),
          if (open && (canApprove || canEdit))
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              if (canApprove) IconButton(key: Key('gp-reject-${p['id']}'), tooltip: 'Reject', onPressed: onReject, icon: const Icon(Icons.thumb_down_alt_outlined, color: red)),
              if (canEdit) TextButton.icon(key: Key('gp-edit-${p['id']}'), onPressed: onEdit, icon: const Icon(Icons.edit_outlined, size: 18), label: const Text('Edit')),
              if (canApprove && p['group'] == 'pending')
                FilledButton.icon(
                  key: Key('gp-approve-${p['id']}'),
                  style: FilledButton.styleFrom(backgroundColor: green),
                  onPressed: onApprove,
                  icon: const Icon(Icons.check, size: 18),
                  label: const Text('Approve'),
                ),
            ]),
        ]),
      ),
    );
  }
}

/// Owns its text controller, so it lives exactly as long as the sheet (including the closing animation).
class _EditSheet extends StatefulWidget {
  const _EditSheet({required this.text, required this.keyword});
  final String text, keyword;

  @override
  State<_EditSheet> createState() => _EditSheetState();
}

class _EditSheetState extends State<_EditSheet> {
  late final _c = TextEditingController(text: widget.text);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.of(context).viewInsets.bottom + 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Edit Google post', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text('Keep “${widget.keyword}” in it — that’s the search this post is for.', style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 10),
          TextField(key: const Key('gp-edit-text'), controller: _c, maxLines: 8, minLines: 4, maxLength: 1500,
              decoration: const InputDecoration(border: OutlineInputBorder())),
          const SizedBox(height: 8),
          FilledButton(key: const Key('gp-edit-save'), onPressed: () => Navigator.pop(context, _c.text.trim()), child: const Text('Save')),
        ]),
      );
}
