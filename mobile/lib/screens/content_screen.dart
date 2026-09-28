import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class ContentScreen extends StatefulWidget {
  const ContentScreen({super.key});

  @override
  State<ContentScreen> createState() => _ContentScreenState();
}

class _ContentScreenState extends State<ContentScreen> {
  final _pipelineKey = GlobalKey<AsyncListState<List<ContentItem>>>();

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    return Scaffold(
      floatingActionButton: me.can('content.create')
          ? FloatingActionButton.extended(
              icon: const Icon(Icons.auto_awesome),
              label: const Text('New with AI'),
              onPressed: () async {
                final created = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const ComposeScreen()));
                if (created == true) _pipelineKey.currentState?.reload();
              },
            )
          : null,
      body: AsyncList<List<ContentItem>>(
        key: _pipelineKey,
        load: (api) async => [for (final c in await api.get('/api/content') as List) ContentItem.fromJson(c as Map<String, dynamic>)],
        builder: (context, items, reload) => [
          if (items.isEmpty) const EmptyState('No content yet.'),
          for (final c in items) ContentTile(item: c, onChanged: reload),
          const SizedBox(height: 72),
        ],
      ),
    );
  }
}

class ContentTile extends StatelessWidget {
  const ContentTile({super.key, required this.item, required this.onChanged});
  final ContentItem item;
  final VoidCallback onChanged;

  Future<void> _act(BuildContext context, String action, String done) async {
    if (await runAction(context, (api) => api.post('/api/content/${item.id}/$action'), success: done)) onChanged();
  }

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    final t = Theme.of(context).textTheme;
    final actions = <Widget>[
      if (item.status == 'draft' && me.can('content.create'))
        FilledButton.tonal(onPressed: () => _act(context, 'submit', 'Sent for approval'), child: const Text('Send for approval')),
      if (item.status == 'in_review' && me.can('content.approve')) ...[
        OutlinedButton(onPressed: () => _act(context, 'request_changes', 'Sent back to draft'), child: const Text('Request changes')),
        FilledButton(onPressed: () => _act(context, 'approve', 'Approved & scheduled'), child: const Text('Approve')),
      ],
      if ((item.status == 'scheduled' || item.status == 'failed') && me.can('content.publish'))
        FilledButton(onPressed: () => _act(context, 'publish', 'Published'), child: Text(item.status == 'failed' ? 'Retry' : 'Publish now')),
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(item.topic, style: const TextStyle(fontWeight: FontWeight.w600))),
            StatusChip(item.status),
          ]),
          Text('${item.clientName} · ${fmtDateTime(item.scheduledAt)}', style: t.bodySmall),
          const SizedBox(height: 6),
          Text(item.masterCopy, maxLines: 3, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 6),
          Wrap(spacing: 4, runSpacing: 4, children: [for (final v in item.variants) Chip(label: Text(platformLabels[v.platform] ?? v.platform), visualDensity: VisualDensity.compact)]),
          if (actions.isNotEmpty) ...[const SizedBox(height: 8), Wrap(spacing: 6, runSpacing: 6, children: actions)],
        ]),
      ),
    );
  }
}

/// Topic → AI draft → per-platform variants → schedule → save / send for approval / approve.
class ComposeScreen extends StatefulWidget {
  const ComposeScreen({super.key});

  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  List<ClientBrief>? _clients;
  int? _clientId;
  Map<String, dynamic>? _meta; // platforms, brand_voice, can_schedule
  final _topic = TextEditingController();
  String _type = 'post';
  final Set<String> _platforms = {'gmb'};
  bool _busy = false;
  String? _error;

  // Draft
  final _master = TextEditingController();
  List<Variant> _variants = [];
  List<String> _hashtags = [];
  String _brief = '';
  String? _source;
  DateTime _when = DateTime.now().add(const Duration(days: 1)).copyWith(hour: 10, minute: 0, second: 0, millisecond: 0, microsecond: 0);

  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    loadClients(_api).then((c) {
      if (!mounted) return;
      setState(() => _clients = c);
      if (c.isNotEmpty) _selectClient(c.first.id);
    }).catchError((Object e) {
      if (mounted) setState(() => _error = '$e');
    });
  }

  @override
  void dispose() {
    _topic.dispose();
    _master.dispose();
    super.dispose();
  }

  Future<void> _selectClient(int id) async {
    setState(() {
      _clientId = id;
      _meta = null;
      _source = null;
    });
    try {
      final meta = await _api.get('/api/content/platforms/$id') as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _meta = meta;
        _platforms.retainAll(List<String>.from(meta['platforms'] as List));
        if (_platforms.isEmpty) _platforms.add('gmb');
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _generate() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final d = await _api.post('/api/content/generate', {
        'client_id': _clientId,
        'topic': _topic.text.trim(),
        'content_type': _type,
        'platforms': _platforms.toList(),
      }) as Map<String, dynamic>;
      setState(() {
        _master.text = d['master_copy'] as String;
        _hashtags = List<String>.from(d['hashtags'] as List? ?? []);
        _brief = d['creative_brief'] as String? ?? '';
        _variants = [for (final v in d['variants'] as List) Variant.fromJson(v as Map<String, dynamic>)];
        _source = d['source'] as String;
      });
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save(String status) async {
    setState(() => _busy = true);
    final ok = await runAction(
      context,
      (api) => api.post('/api/content', {
        'client_id': _clientId,
        'topic': _topic.text.trim(),
        'content_type': _type,
        'master_copy': _master.text,
        'hashtags': _hashtags,
        'creative_brief': _brief,
        'variants': [for (final v in _variants) v.toJson()],
        'status': status,
        'scheduled_at': _when.toUtc().toIso8601String(),
      }),
      success: {'draft': 'Draft saved', 'in_review': 'Sent for approval', 'scheduled': 'Approved & scheduled'}[status],
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) Navigator.pop(context, true);
  }

  Future<void> _pickWhen() async {
    final d = await showDatePicker(context: context, initialDate: _when, firstDate: DateTime.now(), lastDate: DateTime.now().add(const Duration(days: 365)));
    if (d == null || !mounted) return;
    final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(_when));
    if (t == null) return;
    setState(() => _when = DateTime(d.year, d.month, d.day, t.hour, t.minute));
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final meta = _meta;
    final voice = meta?['brand_voice'] as Map<String, dynamic>?;
    return Scaffold(
      appBar: AppBar(title: const Text('AI Content Studio')),
      body: _clients == null
          ? Center(child: _error != null ? Text(_error!) : const CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(12), children: [
              SectionCard(
                title: '1. Brief',
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  ClientPicker(clients: _clients!, value: _clientId, allowAll: false, onChanged: (v) => v == null ? null : _selectClient(v)),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _topic,
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(labelText: 'Topic or offer', hintText: 'e.g. Diwali 20% off teeth whitening'),
                  ),
                  const SizedBox(height: 12),
                  Text('Type', style: t.labelLarge),
                  Wrap(spacing: 6, children: [
                    for (final ty in ['post', 'offer', 'event', 'update']) ChoiceChip(label: Text(ty), selected: _type == ty, onSelected: (_) => setState(() => _type = ty)),
                  ]),
                  const SizedBox(height: 8),
                  Text('Platforms', style: t.labelLarge),
                  if (meta == null)
                    const LinearProgressIndicator()
                  else
                    Wrap(spacing: 6, children: [
                      for (final p in List<String>.from(meta['platforms'] as List))
                        FilterChip(
                          label: Text(platformLabels[p] ?? p),
                          selected: _platforms.contains(p),
                          onSelected: (on) => setState(() => on ? _platforms.add(p) : _platforms.remove(p)),
                        ),
                    ]),
                  if (voice != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text('Voice: ${voice['tone']} · CTA “${voice['cta_style']}”', style: t.bodySmall),
                    ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed: _busy || meta == null || _topic.text.trim().length < 2 || _platforms.isEmpty ? null : _generate,
                    icon: const Icon(Icons.auto_awesome, size: 18),
                    label: Text(_busy && _source == null ? 'Generating…' : _source == null ? 'Generate with AI' : 'Regenerate'),
                  ),
                  if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
                ]),
              ),
              if (_source != null)
                SectionCard(
                  title: '2. Review & schedule',
                  action: StatusChip(_source == 'ai' ? 'drafted' : 'draft', label: _source == 'ai' ? 'AI' : 'Offline template'),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    TextField(controller: _master, maxLines: null, decoration: const InputDecoration(labelText: 'Master copy')),
                    for (final v in _variants) ...[
                      const SizedBox(height: 12),
                      TextFormField(
                        initialValue: v.copy,
                        maxLines: null,
                        decoration: InputDecoration(labelText: '${platformLabels[v.platform]} · ${v.format}'),
                        onChanged: (s) => v.copy = s,
                      ),
                    ],
                    if (_brief.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Text('Creative brief', style: t.labelLarge),
                      Text(_brief, style: t.bodySmall),
                    ],
                    const SizedBox(height: 12),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.schedule),
                      title: Text('Schedule for ${fmtDateTime(_when)}'),
                      trailing: const Icon(Icons.edit_calendar_outlined),
                      onTap: _pickWhen,
                    ),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      OutlinedButton(onPressed: _busy ? null : () => _save('draft'), child: const Text('Save draft')),
                      FilledButton.tonal(onPressed: _busy ? null : () => _save('in_review'), child: const Text('Send for approval')),
                      if (meta?['can_schedule'] == true) FilledButton(onPressed: _busy ? null : () => _save('scheduled'), child: const Text('Approve & schedule')),
                    ]),
                  ]),
                ),
            ]),
    );
  }
}
