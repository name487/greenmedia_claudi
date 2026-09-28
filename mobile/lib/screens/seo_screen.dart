import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class SeoScreen extends StatefulWidget {
  const SeoScreen({super.key});

  @override
  State<SeoScreen> createState() => _SeoScreenState();
}

class _SeoScreenState extends State<SeoScreen> {
  String _sort = 'change';
  int? _clientId;
  List<ClientBrief>? _clients;

  @override
  void initState() {
    super.initState();
    loadClients(context.read<Session>().api).then((c) {
      if (mounted) setState(() => _clients = c);
    }).catchError((_) {});
  }

  Future<void> _addKeyword(VoidCallback reload) async {
    final ctrl = TextEditingController();
    final kw = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Track keyword'),
        content: TextField(controller: ctrl, autofocus: true, decoration: const InputDecoration(hintText: 'e.g. dentist near me')),
        actions: [TextButton(onPressed: () => Navigator.pop(d), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(d, ctrl.text), child: const Text('Add'))],
      ),
    );
    ctrl.dispose();
    if (kw == null || kw.trim().length < 2 || !mounted) return;
    if (await runAction(context, (api) => api.post('/api/seo/keywords', {'client_id': _clientId, 'keyword': kw.trim()}), success: 'Keyword added')) reload();
  }

  @override
  Widget build(BuildContext context) {
    return AsyncList<Map<String, dynamic>>(
      load: (api) async => await api.get('/api/seo', {'sort': _sort, 'client_id': _clientId}) as Map<String, dynamic>,
      builder: (context, d, reload) {
        final s = d['summary'] as Map<String, dynamic>;
        final traffic = (d['traffic'] as List).cast<Map<String, dynamic>>();
        final kws = (d['keywords'] as List).cast<Map<String, dynamic>>();
        return [
          if (_clients != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(children: [
                Expanded(child: ClientPicker(clients: _clients!, value: _clientId, onChanged: (v) {
                  _clientId = v;
                  reload();
                })),
                if (_clientId != null) ...[const SizedBox(width: 8), IconButton.filledTonal(tooltip: 'Track keyword', onPressed: () => _addKeyword(reload), icon: const Icon(Icons.add))],
              ]),
            ),
          StatGrid(children: [
            StatTile(label: 'Tracked', value: '${s['tracked']}'),
            StatTile(label: 'Top 10', value: '${s['top10']}'),
            StatTile(label: 'Improved', value: '${s['improved']}'),
            StatTile(label: 'Organic sessions', value: compact(s['organic_sessions']['current'] as num), delta: s['organic_sessions']['change_pct'] as num),
          ]),
          SectionCard(
            title: 'Organic traffic — 90 days',
            child: LineChart(series: [
              ChartSeries('Organic sessions', [for (final r in traffic) r['organic_sessions'] as num], const Color(0xFF0F7A45)),
              ChartSeries('GSC clicks ×5', [for (final r in traffic) (r['web_clicks'] as num) * 5], const Color(0xFF8A4FD1)),
            ]),
          ),
          SectionCard(
            title: 'Keywords',
            action: DropdownButton<String>(
              value: _sort,
              underline: const SizedBox(),
              items: const [DropdownMenuItem(value: 'change', child: Text('Movers')), DropdownMenuItem(value: 'rank', child: Text('Best rank')), DropdownMenuItem(value: 'volume', child: Text('Volume'))],
              onChanged: (v) {
                _sort = v!;
                reload();
              },
            ),
            child: Column(children: [
              for (final k in kws)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  title: Text(k['keyword'] as String),
                  subtitle: Text('${k['client_name']} · vol ${k['volume']}'),
                  trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                    Text((k['current_rank'] as int) >= 100 ? '—' : '#${k['current_rank']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(width: 6),
                    StatusChip(
                      (k['change'] as int) > 0 ? 'published' : (k['change'] as int) < 0 ? 'failed' : 'draft',
                      label: (k['change'] as int) > 0 ? '▲ ${k['change']}' : (k['change'] as int) < 0 ? '▼ ${-(k['change'] as int)}' : '—',
                    ),
                  ]),
                ),
            ]),
          ),
        ];
      },
    );
  }
}
