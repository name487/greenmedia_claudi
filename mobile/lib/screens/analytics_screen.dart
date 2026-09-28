import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  int _days = 30;
  int? _clientId;
  List<ClientBrief>? _clients;

  @override
  void initState() {
    super.initState();
    final s = context.read<Session>();
    if (!s.me!.isClient) {
      loadClients(s.api).then((c) {
        if (mounted) setState(() => _clients = c);
      }).catchError((_) {});
    }
  }

  @override
  Widget build(BuildContext context) {
    return AsyncList<Map<String, dynamic>>(
      load: (api) async => await api.get('/api/analytics', {'days': _days, 'client_id': _clientId}) as Map<String, dynamic>,
      builder: (context, d, reload) {
        final t = d['totals'] as Map<String, dynamic>;
        final s = (d['series'] as List).cast<Map<String, dynamic>>();
        num cur(String k) => t[k]['current'] as num;
        num pct(String k) => t[k]['change_pct'] as num;
        List<num> col(String k, [num scale = 1]) => [for (final r in s) (r[k] as num) * scale];
        final top = (d['top_clients'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        return [
          if (_clients != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: ClientPicker(clients: _clients!, value: _clientId, onChanged: (v) {
                _clientId = v;
                reload();
              }),
            ),
          SegmentedButton<int>(
            segments: const [ButtonSegment(value: 7, label: Text('7 days')), ButtonSegment(value: 30, label: Text('30 days')), ButtonSegment(value: 45, label: Text('45 days'))],
            selected: {_days},
            onSelectionChanged: (v) {
              _days = v.first;
              reload();
            },
          ),
          const SizedBox(height: 8),
          StatGrid(children: [
            StatTile(label: 'GMB views', value: compact(cur('gmb_views')), delta: pct('gmb_views')),
            StatTile(label: 'Website traffic', value: compact(cur('organic_sessions')), delta: pct('organic_sessions')),
            StatTile(label: 'Social reach', value: compact(cur('social_reach')), delta: pct('social_reach')),
            StatTile(label: 'Engagement', value: compact(cur('engagement')), delta: pct('engagement')),
            StatTile(label: 'Calls', value: compact(cur('gmb_calls')), delta: pct('gmb_calls')),
            StatTile(label: 'Leads', value: compact(cur('leads')), delta: pct('leads')),
          ]),
          SectionCard(title: 'Google Business Profile', child: LineChart(series: [ChartSeries('Views', col('gmb_views'), const Color(0xFF0F7A45)), ChartSeries('Web clicks ×10', col('web_clicks', 10), const Color(0xFFD9822B))])),
          SectionCard(title: 'Website (GA4)', child: LineChart(series: [ChartSeries('Organic sessions', col('organic_sessions'), const Color(0xFF1F63C6))])),
          SectionCard(title: 'Social', child: LineChart(series: [ChartSeries('Reach', col('social_reach'), const Color(0xFF8A4FD1)), ChartSeries('Engagement ×10', col('engagement', 10), const Color(0xFFD9822B))])),
          SectionCard(
            title: 'Leads by source',
            child: BarList([('Google calls', cur('gmb_calls')), ('Directions', cur('gmb_directions')), ('Website clicks', cur('web_clicks')), ('Form & WhatsApp', cur('leads'))]),
          ),
          if (top.isNotEmpty) SectionCard(title: 'Top clients by leads', child: BarList([for (final c in top) (c['client_name'] as String, c['leads'] as num)])),
        ];
      },
    );
  }
}
