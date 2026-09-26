import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const kpiLabels = {
  'gmb_views': 'GMB views', 'gmb_calls': 'Calls', 'gmb_directions': 'Directions', 'web_clicks': 'Website clicks',
  'organic_sessions': 'Organic sessions', 'social_reach': 'Social reach', 'engagement': 'Engagement', 'leads': 'Leads',
};

class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key, this.clientId});
  final int? clientId;

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  int? _clientId;
  List<ClientBrief>? _clients;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final s = context.read<Session>();
    _clientId = widget.clientId ?? s.me!.clientId;
    if (_clientId == null) {
      loadClients(s.api).then((c) {
        if (mounted) {
          setState(() {
            _clients = c;
            _clientId ??= c.isEmpty ? null : c.first.id;
          });
        }
      }).catchError((_) {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    if (_clientId == null) return const Center(child: CircularProgressIndicator());
    return AsyncList<(List<ReportItem>, Map<String, dynamic>?)>(
      load: (api) async {
        final list = [for (final r in await api.get('/api/reports', {'client_id': _clientId}) as List) ReportItem.fromJson(r as Map<String, dynamic>)];
        final detail = list.isEmpty ? null : await api.get('/api/reports/${list.first.id}') as Map<String, dynamic>;
        return (list, detail);
      },
      builder: (context, data, reload) {
        final (list, detail) = data;
        Future<void> generate() async {
          setState(() => _busy = true);
          await runAction(context, (api) => api.post('/api/reports/generate', {'client_id': _clientId}), success: 'Report generated');
          if (mounted) setState(() => _busy = false);
          reload();
        }

        Future<void> deliver(String via) async {
          await runAction(context, (api) async {
            final out = await api.post('/api/reports/${detail!['id']}/deliver', {'via': via}) as Map<String, dynamic>;
            await launchUrl(Uri.parse(out['share_url'] as String), mode: LaunchMode.externalApplication);
          });
          reload();
        }

        return [
          if (_clients != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: ClientPicker(clients: _clients!, value: _clientId, allowAll: false, onChanged: (v) {
                setState(() => _clientId = v);
                reload();
              }),
            ),
          if (me.can('report.deliver'))
            FilledButton.icon(onPressed: _busy ? null : generate, icon: const Icon(Icons.auto_awesome, size: 18), label: Text(_busy ? 'Generating…' : 'Generate monthly report')),
          if (detail == null) const EmptyState('No reports yet.'),
          if (detail != null) ...[
            SectionCard(
              title: '${fmtDate(parseDate(detail['period_start']))} – ${fmtDate(parseDate(detail['period_end']))}',
              action: detail['delivered_via'] != null ? StatusChip('published', label: 'Sent via ${detail['delivered_via']}') : null,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SelectableText(detail['summary'] as String),
                if (me.can('report.deliver')) ...[
                  const SizedBox(height: 12),
                  Wrap(spacing: 6, children: [
                    FilledButton.tonalIcon(onPressed: () => deliver('email'), icon: const Icon(Icons.email_outlined, size: 18), label: const Text('Email')),
                    FilledButton.tonalIcon(onPressed: () => deliver('whatsapp'), icon: const Icon(Icons.chat_outlined, size: 18), label: const Text('WhatsApp')),
                  ]),
                ],
              ]),
            ),
            SectionCard(
              title: 'KPI comparison',
              child: Table(
                columnWidths: const {0: FlexColumnWidth(2)},
                children: [
                  const TableRow(children: [Text('Metric', style: TextStyle(fontWeight: FontWeight.w600)), Text('Now', textAlign: TextAlign.right), Text('Before', textAlign: TextAlign.right), Text('Δ', textAlign: TextAlign.right)]),
                  for (final e in kpiLabels.entries)
                    TableRow(children: [
                      Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text(e.value)),
                      Text('${detail['kpis'][e.key]['current']}', textAlign: TextAlign.right),
                      Text('${detail['kpis'][e.key]['previous']}', textAlign: TextAlign.right),
                      Align(alignment: Alignment.centerRight, child: Delta(detail['kpis'][e.key]['change_pct'] as num)),
                    ]),
                ],
              ),
            ),
            if (list.length > 1)
              SectionCard(
                title: 'History',
                child: Column(children: [for (final r in list) ListTile(contentPadding: EdgeInsets.zero, dense: true, title: Text('${fmtDate(r.periodStart)} – ${fmtDate(r.periodEnd)}'), trailing: Text(r.source))]),
              ),
          ],
        ];
      },
    );
  }
}
