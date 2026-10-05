import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const reviewFilters = [
  ('pending', 'Needs reply'),
  ('approved', 'Approved'),
  ('negative', 'Negative'),
  ('published', 'Published'),
  ('all', 'All'),
];

class ReviewsScreen extends StatefulWidget {
  const ReviewsScreen({super.key, this.clientId});
  final int? clientId;

  @override
  State<ReviewsScreen> createState() => _ReviewsScreenState();
}

class _ReviewsScreenState extends State<ReviewsScreen> {
  String _filter = 'pending';
  int? _clientId;
  List<ClientBrief>? _clients;
  final _listKey = GlobalKey<AsyncListState<Map<String, dynamic>>>();

  @override
  void initState() {
    super.initState();
    _clientId = widget.clientId;
    final session = context.read<Session>();
    if (!session.me!.isClient) {
      loadClients(session.api).then((c) {
        if (mounted) setState(() => _clients = c);
      }).catchError((_) {});
    }
  }

  Future<Map<String, dynamic>> _load(ApiClient api) async =>
      await api.get('/api/reviews', {'filter': _filter, 'client_id': _clientId}) as Map<String, dynamic>;

  Future<void> _sync() async {
    await runAction(context, (api) async {
      final out = await api.post('/api/reviews/sync', {'client_id': _clientId}) as Map<String, dynamic>;
      if (!mounted) return;
      final errors = (out['errors'] as List).cast<String>();
      final pending = (out['approval_pending'] as List).cast<String>();
      final parts = [
        if ((out['profiles'] as int) > 0) '${out['new_reviews']} new from Google',
        if ((out['sample_reviews'] as int) > 0) '${out['sample_reviews']} sample',
      ];
      var msg = 'Synced: ${parts.isEmpty ? 'nothing new' : parts.join(' + ')} · ${out['drafted']} AI draft(s)';
      if ((out['auto_published'] as int) > 0) msg += ', ${out['auto_published']} auto-published';
      if (pending.isNotEmpty) msg += ' · Google API approval pending for ${pending.join(', ')}';
      if (errors.isNotEmpty) msg += ' · ${errors.join('; ')}';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    });
    _listKey.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    return AsyncList<Map<String, dynamic>>(
      key: _listKey,
      load: _load,
      builder: (context, data, reload) {
        final counts = data['counts'] as Map<String, dynamic>;
        final items = [for (final r in data['items'] as List) Review.fromJson(r as Map<String, dynamic>)];
        return [
          if (_clients != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(children: [
                Expanded(
                  child: ClientPicker(
                    clients: _clients!,
                    value: _clientId,
                    onChanged: (v) {
                      _clientId = v;
                      reload();
                    },
                  ),
                ),
                if (me.sees('gmb')) ...[
                  const SizedBox(width: 8),
                  IconButton.filledTonal(tooltip: 'Sync new reviews', onPressed: _sync, icon: const Icon(Icons.sync)),
                ],
              ]),
            ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              for (final (key, label) in reviewFilters)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text('$label (${counts[key]})'),
                    selected: _filter == key,
                    onSelected: (_) {
                      _filter = key;
                      reload();
                    },
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 8),
          if (items.isEmpty) const EmptyState('No reviews here.'),
          for (final r in items) ReviewCard(key: ValueKey('${r.id}-${r.replyStatus}-${r.reply.hashCode}'), review: r, onChanged: reload),
        ];
      },
    );
  }
}

class ReviewCard extends StatefulWidget {
  const ReviewCard({super.key, required this.review, required this.onChanged});
  final Review review;
  final VoidCallback onChanged;

  @override
  State<ReviewCard> createState() => _ReviewCardState();
}

class _ReviewCardState extends State<ReviewCard> {
  late final _reply = TextEditingController(text: widget.review.reply ?? '');
  bool _busy = false;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  Future<void> _do(Future<void> Function(ApiClient api) action, {String? success}) async {
    setState(() => _busy = true);
    final ok = await runAction(context, action, success: success);
    if (mounted) setState(() => _busy = false);
    if (ok) widget.onChanged();
  }

  /// Save a pending edit first so approve/publish act on what the user sees.
  Future<void> _saveIfEdited(ApiClient api) async {
    if (_reply.text.trim() != (widget.review.reply ?? '').trim()) {
      await api.patch('/api/reviews/${widget.review.id}', {'reply': _reply.text});
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.review;
    final me = context.read<Session>().me!;
    final t = Theme.of(context).textTheme;
    final editable = r.replyStatus == 'drafted' || r.replyStatus == 'approved' || r.replyStatus == 'failed';

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [Text(r.author, style: const TextStyle(fontWeight: FontWeight.w600)), const SizedBox(width: 6), Stars(r.rating)]),
                Text('${r.clientName} · ${fmtDateTime(r.createdAt)}', style: t.bodySmall),
              ]),
            ),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 6, children: [
            if (r.isSample) const StatusChip('drafted', label: 'Sample'),
            StatusChip(r.sentiment),
            if (r.language != 'en') StatusChip('scheduled', label: r.language),
            StatusChip(r.replyStatus),
          ]),
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(10)),
            child: Text(r.text),
          ),
          if (r.needsEscalation && r.replyStatus != 'published')
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('Escalation: replies to 2★ or lower need approval before publishing.', style: t.bodySmall?.copyWith(color: Colors.orange.shade800)),
            ),
          const SizedBox(height: 10),
          if (r.replyStatus == 'new')
            FilledButton.icon(
              onPressed: _busy ? null : () => _do((api) => api.post('/api/reviews/${r.id}/draft')),
              icon: const Icon(Icons.auto_awesome, size: 18),
              label: Text(_busy ? 'Drafting…' : 'Generate AI reply'),
            )
          else if (r.replyStatus == 'published')
            Text('${r.reply}\n\nPublished ${fmtDateTime(r.publishedAt)}', style: t.bodyMedium)
          else if (r.replyStatus == 'rejected')
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(onPressed: _busy ? null : () => _do((api) => api.post('/api/reviews/${r.id}/reopen')), child: const Text('Reopen')),
            )
          else if (editable) ...[
            TextField(controller: _reply, maxLines: null, minLines: 3, decoration: const InputDecoration(labelText: 'Reply')),
            const SizedBox(height: 8),
            Wrap(spacing: 6, runSpacing: 6, children: [
              OutlinedButton(
                onPressed: _busy ? null : () => _do((api) => api.patch('/api/reviews/${r.id}', {'reply': _reply.text}), success: 'Reply saved'),
                child: const Text('Save'),
              ),
              OutlinedButton(onPressed: _busy ? null : () => _do((api) => api.post('/api/reviews/${r.id}/draft')), child: const Text('Regenerate')),
              OutlinedButton(onPressed: _busy ? null : () => _do((api) => api.post('/api/reviews/${r.id}/reject')), child: const Text('Reject')),
              if (me.can('review.approve') && r.replyStatus != 'approved')
                FilledButton.tonal(
                  onPressed: _busy
                      ? null
                      : () => _do((api) async {
                            await _saveIfEdited(api);
                            await api.post('/api/reviews/${r.id}/approve');
                          }),
                  child: const Text('Approve'),
                ),
              if (me.can('review.publish'))
                FilledButton(
                  onPressed: _busy || (r.needsEscalation && r.replyStatus != 'approved')
                      ? null
                      : () => _do((api) async {
                            await _saveIfEdited(api);
                            // An edit resets approval, so low-rated replies must be approved again first.
                            await api.post('/api/reviews/${r.id}/publish');
                          }, success: 'Reply published to Google'),
                  child: const Text('Publish'),
                ),
            ]),
          ],
        ]),
      ),
    );
  }
}
