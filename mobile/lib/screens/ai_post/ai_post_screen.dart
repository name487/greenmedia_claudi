import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import '../../widgets/common.dart';
import 'create_flow.dart';
import 'items_screen.dart';
import 'shared.dart';

/// The owner's AI Post tab: viral video banner, Scheduled (Pending / Approved / Rejected) / Posted / Not Posted,
/// every post with its status, and Generate AI Post.
class AiPostScreen extends StatefulWidget {
  const AiPostScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<AiPostScreen> createState() => _AiPostScreenState();
}

class _AiPostScreenState extends State<AiPostScreen> {
  String _main = 'scheduled', _sub = 'pending', _period = 'lifetime';
  Map<String, dynamic>? _overview;
  List<Map<String, dynamic>>? _items;
  String? _error;

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}';
  String get _tab => _main == 'scheduled' ? _sub : _main;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Future.wait([
        _api.get('$_base/ai-posts/overview'),
        _api.get('$_base/ai-posts', {'tab': _tab, 'period': _period}),
      ]);
      if (!mounted) return;
      setState(() {
        _overview = r[0] as Map<String, dynamic>;
        _items = ((r[1] as Map)['items'] as List).cast<Map<String, dynamic>>();
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _select({String? main, String? sub, String? period}) {
    setState(() {
      _main = main ?? _main;
      _sub = sub ?? _sub;
      _period = period ?? _period;
      _items = null;
    });
    _load();
  }

  Future<void> _push(Widget page) async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => page));
    if (mounted) _load();
  }

  void _help() => showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (s) => const SafeArea(
          child: Padding(
            padding: EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('How AI Post works', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              SizedBox(height: 10),
              Text('1. Add your products with a photo.'),
              Text('2. Generate an AI post (a poster with a caption) or a viral video from a template.'),
              Text('3. Check it and tap Approve — pick the day and time it goes out.'),
              Text('4. It posts to Google, Facebook and Instagram at that time. Nothing is posted without your approval.'),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    final q = _overview?['quota'] as Map<String, dynamic>?;
    final videos = q?['videos'] as Map<String, dynamic>?;
    final posts = q?['posts'] as Map<String, dynamic>?;
    return Scaffold(
      appBar: navyBar('AI Post', subtitle: me.clientName, actions: [IconButton(tooltip: 'How it works', icon: const Icon(Icons.help_outline), onPressed: _help)]),
      body: _overview == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : Column(children: [
              Expanded(
                child: RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 16), children: [
                    _ViralBanner(used: videos!['used'] as int, limit: videos['limit'] as int,
                        onTap: () => _push(VideoTemplatesScreen(clientId: widget.clientId))),
                    const SizedBox(height: 12),
                    _Segments(
                      value: _main,
                      options: const [('scheduled', 'Scheduled', Icons.event_note), ('posted', 'Posted', Icons.check_circle_outline),
                        ('not_posted', 'Not Posted', Icons.cancel_outlined)],
                      onChanged: (v) => _select(main: v),
                      dark: true,
                    ),
                    const SizedBox(height: 8),
                    if (_main == 'scheduled')
                      _Segments(
                        value: _sub,
                        options: const [('pending', 'Pending', Icons.hourglass_bottom), ('approved', 'Approved', Icons.thumb_up_alt_outlined),
                          ('rejected', 'Rejected', Icons.thumb_down_alt_outlined)],
                        onChanged: (v) => _select(sub: v),
                      )
                    else if (_main == 'posted')
                      Row(children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(color: green.withValues(alpha: .12), borderRadius: BorderRadius.circular(99), border: Border.all(color: green)),
                          child: Text('${(_items?.length ?? 0).toString().padLeft(2, '0')} Posts', style: const TextStyle(color: green, fontSize: 12, fontWeight: FontWeight.w600)),
                        ),
                        const Spacer(),
                        PopupMenuButton<String>(
                          tooltip: 'Period',
                          initialValue: _period,
                          onSelected: (v) => _select(period: v),
                          itemBuilder: (_) => const [
                            CheckedPopupMenuItem(value: 'week', child: Text('This Week')),
                            CheckedPopupMenuItem(value: 'month', child: Text('This Month')),
                            CheckedPopupMenuItem(value: 'quarter', child: Text('Last 3 Months')),
                            CheckedPopupMenuItem(value: 'lifetime', child: Text('Lifetime')),
                          ],
                          child: Row(mainAxisSize: MainAxisSize.min, children: [
                            Text(const {'week': 'This Week', 'month': 'This Month', 'quarter': 'Last 3 Months', 'lifetime': 'Lifetime'}[_period]!),
                            const Icon(Icons.expand_more),
                          ]),
                        ),
                      ]),
                    const SizedBox(height: 10),
                    if (_items == null)
                      const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
                    else if (_items!.isEmpty)
                      _Empty(tab: _tab)
                    else
                      for (final (i, p) in _items!.indexed)
                        _PostTile(
                          post: p,
                          onTap: () => _push(p['status'] == 'generating'
                              ? GeneratingScreen(clientId: widget.clientId, postId: p['id'] as int)
                              : PostPagerScreen(clientId: widget.clientId, posts: _items!, initial: i)),
                        ),
                  ]),
                ),
              ),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
                  child: GradientButton(
                    key: const Key('generate-ai-post'),
                    label: 'Generate AI Post (${posts!['used']}/${posts['limit']})',
                    icon: Icons.auto_fix_high,
                    onPressed: (posts['used'] as int) >= (posts['limit'] as int) ? null : () => _push(ItemsScreen(clientId: widget.clientId)),
                  ),
                ),
              ),
            ]),
    );
  }
}

class _ViralBanner extends StatelessWidget {
  const _ViralBanner({required this.used, required this.limit, required this.onTap});
  final int used, limit;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
        key: const Key('viral-banner'),
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: const Color(0xFFFF7A2F)),
            gradient: const LinearGradient(colors: [Color(0xFFFFF4FB), Color(0xFFFFF7EF)]),
          ),
          child: Row(children: [
            const Icon(Icons.video_library_outlined, color: Color(0xFFE8457C), size: 20),
            const SizedBox(width: 8),
            const Expanded(child: Text('Try Generating Viral Video', style: TextStyle(color: Color(0xFFE8457C), fontWeight: FontWeight.w600))),
            Text('($used/$limit)', style: const TextStyle(color: Colors.black54, fontSize: 12)),
            const Icon(Icons.chevron_right, color: Color(0xFFE8457C)),
          ]),
        ),
      );
}

class _Segments extends StatelessWidget {
  const _Segments({required this.value, required this.options, required this.onChanged, this.dark = false});
  final String value;
  final List<(String, String, IconData)> options;
  final ValueChanged<String> onChanged;
  final bool dark;

  @override
  Widget build(BuildContext context) => Row(children: [
        for (final (key, label, icon) in options)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: InkWell(
                key: Key('seg-$key'),
                borderRadius: BorderRadius.circular(8),
                onTap: () => onChanged(key),
                child: Container(
                  padding: EdgeInsets.symmetric(vertical: dark ? 9 : 6),
                  decoration: BoxDecoration(
                    color: value == key ? (dark ? navy : green.withValues(alpha: .12)) : null,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: value == key ? (dark ? navy : green) : Theme.of(context).dividerColor),
                  ),
                  child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    Icon(icon, size: 14, color: value == key ? (dark ? Colors.white : green) : Theme.of(context).hintColor),
                    const SizedBox(width: 4),
                    Flexible(
                      child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: value == key ? (dark ? Colors.white : green) : Theme.of(context).hintColor)),
                    ),
                  ]),
                ),
              ),
            ),
          ),
      ]);
}

class _Empty extends StatelessWidget {
  const _Empty({required this.tab});
  final String tab;

  @override
  Widget build(BuildContext context) {
    final (icon, title, text) = switch (tab) {
      'pending' => (Icons.inbox_outlined, 'No pending posts', 'You\'ve reviewed everything. New posts will show up here.'),
      'approved' => (Icons.inbox_outlined, 'No approved posts', 'Approved posts will appear here once they\'re approved.'),
      'rejected' => (Icons.delete_outline, 'Nothing Rejected', 'Rejected posts will appear here.'),
      'posted' => (Icons.send_outlined, 'Nothing Posted Yet', 'Approve or create AI posts to keep your profile active.'),
      _ => (Icons.delete_outline, 'Nothing here', 'Posts that couldn\'t go out will appear here.'),
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 48),
      child: Column(children: [
        Icon(icon, size: 64, color: Theme.of(context).hintColor),
        const SizedBox(height: 12),
        Text(title, style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text(text, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
      ]),
    );
  }
}

class _PostTile extends StatelessWidget {
  const _PostTile({required this.post, required this.onTap});
  final Map<String, dynamic> post;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final (status, colour) = postStatus(post);
    final generating = post['status'] == 'generating';
    final steps = (post['gen_steps'] as List).length;
    return Card(
      child: InkWell(
        key: Key('post-${post['id']}'),
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Row(children: [
            PostThumb(post),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(post['caption'] as String? ?? '', maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
                const SizedBox(height: 6),
                Text(status, style: TextStyle(color: colour, fontWeight: FontWeight.w600, fontSize: 12)),
                if (generating)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: LinearProgressIndicator(value: (post['gen_progress'] as int) / steps, minHeight: 3),
                  ),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Swipe through posts: keywords targeted, status, caption with the keywords highlighted, media, reject / share / download.
class PostPagerScreen extends StatefulWidget {
  const PostPagerScreen({super.key, required this.clientId, required this.posts, required this.initial});
  final int clientId;
  final List<Map<String, dynamic>> posts;
  final int initial;

  @override
  State<PostPagerScreen> createState() => _PostPagerScreenState();
}

class _PostPagerScreenState extends State<PostPagerScreen> {
  late final _pages = PageController(initialPage: widget.initial);
  late int _i = widget.initial;

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  Future<void> _reject(Map<String, dynamic> p) async {
    final ok = await runAction(context, (api) => api.post('/api/clients/${widget.clientId}/ai-posts/${p['id']}/reject'), success: 'Post rejected');
    if (ok && mounted) Navigator.pop(context);
  }

  Future<void> _share(Map<String, dynamic> p) {
    final media = (p['video_url'] as String? ?? '').isNotEmpty ? p['video_url'] : p['image_url'];
    final text = '${p['caption']}\n\n${(p['hashtags'] as List).join(' ')}\n$media';
    return launchUrl(Uri.parse('https://wa.me/?text=${Uri.encodeComponent(text)}'), mode: LaunchMode.externalApplication);
  }

  Future<void> _download(Map<String, dynamic> p) {
    final media = (p['video_url'] as String? ?? '').isNotEmpty ? p['video_url'] as String : p['image_url'] as String;
    return launchUrl(Uri.parse(media), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.posts[_i];
    final canReject = const {'in_review', 'draft', 'scheduled'}.contains(p['status']);
    final canApprove = const {'in_review', 'draft', 'rejected'}.contains(p['status']);
    return Scaffold(
      appBar: navyBar('Post ${_i + 1} of ${widget.posts.length}'),
      body: Column(children: [
        Expanded(
          child: PageView(
            controller: _pages,
            onPageChanged: (i) => setState(() => _i = i),
            children: [for (final post in widget.posts) _PostDetail(post: post)],
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
            child: Row(children: [
              if (canReject)
                IconButton.outlined(
                  tooltip: 'Reject',
                  style: IconButton.styleFrom(side: const BorderSide(color: red)),
                  icon: const Icon(Icons.thumb_down_alt_outlined, color: red),
                  onPressed: () => _reject(p),
                ),
              const SizedBox(width: 8),
              if (canApprove)
                Expanded(
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: green),
                    icon: const Icon(Icons.check),
                    label: const Text('Approve'),
                    onPressed: () async {
                      await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => ScheduleScreen(clientId: widget.clientId, postId: p['id'] as int)));
                    },
                  ),
                )
              else ...[
                Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.share_outlined), label: const Text('Share'), onPressed: () => _share(p))),
                const SizedBox(width: 8),
                Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.download_outlined), label: const Text('Download'), onPressed: () => _download(p))),
              ],
            ]),
          ),
        ),
      ]),
    );
  }
}

class _PostDetail extends StatefulWidget {
  const _PostDetail({required this.post});
  final Map<String, dynamic> post;

  @override
  State<_PostDetail> createState() => _PostDetailState();
}

class _PostDetailState extends State<_PostDetail> {
  bool _more = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.post;
    final t = Theme.of(context).textTheme;
    final kws = (p['keywords'] as List).cast<Map<String, dynamic>>();
    final (status, colour) = postStatus(p);
    final caption = '${p['caption']}\n\n${(p['hashtags'] as List).join(' ')}'.trim();
    return ListView(padding: const EdgeInsets.all(12), children: [
      if (kws.isNotEmpty)
        Container(
          key: const Key('targets-keywords'),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: const Color(0xFFEEF3FF), borderRadius: BorderRadius.circular(12)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              const Icon(Icons.search, size: 18),
              const SizedBox(width: 6),
              Expanded(child: Text('This post targets the following keywords', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
            ]),
            const SizedBox(height: 8),
            Table(
              border: TableBorder.all(color: const Color(0xFFCBD6F2), borderRadius: BorderRadius.circular(6)),
              children: [
                const TableRow(decoration: BoxDecoration(color: Colors.white), children: [
                  Padding(padding: EdgeInsets.all(8), child: Text('Keywords', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
                  Padding(padding: EdgeInsets.all(8), child: Text('Search Volume (monthly)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
                ]),
                for (final k in kws)
                  TableRow(decoration: const BoxDecoration(color: Colors.white), children: [
                    Padding(padding: const EdgeInsets.all(8), child: Text(k['keyword'] as String, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600))),
                    Padding(padding: const EdgeInsets.all(8), child: Text('${k['volume']}', style: const TextStyle(fontSize: 12))),
                  ]),
              ],
            ),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(vertical: 6),
              decoration: BoxDecoration(color: const Color(0xFFE3F6EA), borderRadius: BorderRadius.circular(6)),
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                const Icon(Icons.visibility_outlined, size: 16, color: green),
                const SizedBox(width: 6),
                Text('~${p['estimated_views']} estimated views', style: const TextStyle(color: green, fontWeight: FontWeight.w600, fontSize: 12)),
              ]),
            ),
            const SizedBox(height: 6),
            const Row(children: [
              Icon(Icons.lightbulb_outline, size: 16, color: Color(0xFFF2B01E)),
              SizedBox(width: 6),
              Expanded(child: Text('Google reads the post description to match it with relevant searches.', style: TextStyle(fontSize: 11))),
            ]),
          ]),
        ),
      const SizedBox(height: 12),
      Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(99)),
          child: Text(status, key: const Key('post-status'), style: TextStyle(color: colour, fontSize: 12, fontWeight: FontWeight.w600)),
        ),
      ),
      const SizedBox(height: 8),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Icon(Icons.chat_bubble, size: 18, color: Color(0xFF1F63C6)),
              const SizedBox(width: 8),
              Expanded(child: Text.rich(highlight(caption, kws), maxLines: _more ? null : 3, overflow: _more ? null : TextOverflow.ellipsis)),
            ]),
            TextButton(onPressed: () => setState(() => _more = !_more), child: Text(_more ? 'Show less' : 'Show more')),
          ]),
        ),
      ),
      PostMedia(post: p),
    ]);
  }
}

/// The caption with the targeted keywords' words in blue.
TextSpan highlight(String text, List<Map<String, dynamic>> kws) {
  final words = {
    for (final k in kws) ...(k['keyword'] as String).toLowerCase().split(RegExp(r'\s+')).where((w) => w.length > 3),
  };
  if (words.isEmpty) return TextSpan(text: text);
  final spans = <TextSpan>[];
  var last = 0;
  for (final m in RegExp(r'[\p{L}\p{N}]+', unicode: true).allMatches(text)) {
    if (words.contains(m.group(0)!.toLowerCase())) {
      if (m.start > last) spans.add(TextSpan(text: text.substring(last, m.start)));
      spans.add(TextSpan(text: m.group(0), style: const TextStyle(color: Color(0xFF1F63C6), fontWeight: FontWeight.w600)));
      last = m.end;
    }
  }
  if (last < text.length) spans.add(TextSpan(text: text.substring(last)));
  return TextSpan(children: spans);
}
