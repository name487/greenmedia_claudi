import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'reports_screen.dart';
import 'reviews_screen.dart';

void openClient(BuildContext context, int id) =>
    Navigator.push(context, MaterialPageRoute<void>(builder: (_) => ClientDetailScreen(clientId: id)));

class ClientDetailScreen extends StatelessWidget {
  const ClientDetailScreen({super.key, required this.clientId});
  final int clientId;

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    return Scaffold(
      appBar: AppBar(title: const Text('Client')),
      body: AsyncList<Map<String, dynamic>>(
        load: (api) async => await api.get('/api/clients/$clientId') as Map<String, dynamic>,
        builder: (context, c, reload) {
          final k = c['kpis'] as Map<String, dynamic>;
          final gmb = c['gmb'] as Map<String, dynamic>?;
          final social = (c['social_accounts'] as List).cast<Map<String, dynamic>>();
          final voice = c['brand_voice'] as Map<String, dynamic>;
          final auto = Map<String, dynamic>.from(c['auto_publish'] as Map);
          final contact = (c['contacts'] as List).isEmpty ? null : (c['contacts'] as List).first as Map<String, dynamic>;
          final channels = ['reviews', 'gmb', ...social.map((s) => s['platform'] as String)];
          final t = Theme.of(context).textTheme;
          final editable = me.can('client.edit');

          Future<void> toggle(String ch, bool on) async {
            auto[ch] = on;
            if (await runAction(context, (api) => api.patch('/api/clients/$clientId', {'auto_publish': auto}), success: 'Publishing safety updated')) reload();
          }

          return [
            Text(c['company_name'] as String, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
            Row(children: [
              Expanded(child: Text('${c['industry']} · ${c['city']} · ${c['plan']} plan', style: t.bodySmall)),
              StatusChip(c['status'] as String),
            ]),
            const SizedBox(height: 8),
            StatGrid(children: [
              StatTile(label: 'Google rating', value: '${gmb?['rating'] ?? '—'}', hint: '${gmb?['review_count'] ?? 0} reviews'),
              StatTile(label: 'GMB views (30d)', value: compact(k['gmb_views']['current'] as num), delta: k['gmb_views']['change_pct'] as num),
              StatTile(label: 'Calls (30d)', value: '${k['gmb_calls']['current']}', delta: k['gmb_calls']['change_pct'] as num),
              StatTile(label: 'Leads (30d)', value: '${k['leads']['current']}', delta: k['leads']['change_pct'] as num),
            ]),
            Wrap(spacing: 6, children: [
              if (me.sees('reviews'))
                FilledButton.tonal(
                  onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => Scaffold(appBar: AppBar(title: const Text('Reviews')), body: ReviewsScreen(clientId: clientId)))),
                  child: const Text('Reviews'),
                ),
              if (me.sees('reports'))
                FilledButton.tonal(
                  onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => Scaffold(appBar: AppBar(title: const Text('Reports')), body: ReportsScreen(clientId: clientId)))),
                  child: const Text('Reports'),
                ),
            ]),
            SectionCard(
              title: 'Connected accounts',
              child: Column(children: [
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Google Business Profile'),
                  subtitle: Text('Last sync ${fmtDateTime(parseDate(gmb?['last_sync']))}'),
                  trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                    StatusChip(gmb?['status'] as String? ?? 'disconnected'),
                    if (me.sees('gmb'))
                      IconButton(
                        tooltip: 'Sync',
                        icon: const Icon(Icons.sync),
                        onPressed: () async {
                          if (await runAction(context, (api) => api.post('/api/clients/$clientId/gmb/sync'), success: 'Google Business Profile synced')) reload();
                        },
                      ),
                  ]),
                ),
                for (final s in social)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(platformLabels[s['platform']] ?? '${s['platform']}'),
                    subtitle: Text(s['handle'] as String),
                    trailing: s['status'] == 'connected' || !me.sees('social')
                        ? StatusChip(s['status'] as String)
                        : TextButton(
                            onPressed: () async {
                              if (await runAction(context, (api) => api.post('/api/clients/$clientId/social/${s['platform']}/reconnect'), success: 'Reconnected')) reload();
                            },
                            child: const Text('Reconnect'),
                          ),
                  ),
              ]),
            ),
            SectionCard(
              title: 'Publishing safety',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Nothing publishes without approval unless auto-publish is on for that channel.', style: t.bodySmall),
                for (final ch in channels)
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(ch == 'reviews' ? 'Positive review replies' : platformLabels[ch] ?? ch),
                    value: auto[ch] == true,
                    onChanged: editable ? (v) => toggle(ch, v) : null,
                  ),
              ]),
            ),
            SectionCard(
              title: 'Profile & brand voice',
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _kv('Website', c['website'] as String),
                if (contact != null) ...[_kv('Contact', '${contact['name']} (${contact['designation']})'), _kv('Phone', contact['phone'] as String), _kv('Email', contact['email'] as String)],
                _kv('Manager', c['account_manager_name'] as String? ?? '—'),
                _kv('Tone', voice['tone'] as String? ?? ''),
                _kv('CTA', voice['cta_style'] as String? ?? ''),
                _kv('Never say', (voice['prohibited_claims'] as List? ?? []).join(', ')),
              ]),
            ),
            SectionCard(
              title: 'SEO keywords',
              child: Column(children: [
                for (final kw in (c['keywords'] as List).cast<Map<String, dynamic>>())
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: Text(kw['keyword'] as String),
                    trailing: StatusChip((kw['change'] as int) >= 0 ? 'published' : 'failed', label: '#${kw['current_rank']}'),
                  ),
              ]),
            ),
            if ((c['notes'] as String).isNotEmpty) SectionCard(title: 'Notes', child: Text(c['notes'] as String)),
          ];
        },
      ),
    );
  }

  static Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 90, child: Text(k, style: const TextStyle(color: Colors.grey))),
          Expanded(child: Text(v)),
        ]),
      );
}
