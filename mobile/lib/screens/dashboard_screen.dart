import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/session.dart';
import '../widgets/common.dart';
import 'client_detail_screen.dart';

class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    final hour = DateTime.now().hour;
    final greeting = hour < 12 ? 'morning' : hour < 17 ? 'afternoon' : 'evening';
    return AsyncList<Map<String, dynamic>>(
      load: (api) async => await api.get('/api/dashboard') as Map<String, dynamic>,
      builder: (context, d, _) {
        final k = d['kpis'] as Map<String, dynamic>;
        final growth = (d['growth'] as List).cast<Map<String, dynamic>>();
        final perf = (d['client_performance'] as List).cast<Map<String, dynamic>>();
        final negative = (d['negative_reviews'] as List).cast<Map<String, dynamic>>();
        final alerts = (d['seo_alerts'] as List).cast<Map<String, dynamic>>();
        final src = d['lead_sources'] as Map<String, dynamic>;
        return [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 8, 4, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Good $greeting, ${firstName(me.name)}', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
              Text(me.isClient ? '${me.clientName} · last 30 days' : '${perf.length} clients · last 30 days', style: Theme.of(context).textTheme.bodySmall),
            ]),
          ),
          StatGrid(children: [
            if (!me.isClient) StatTile(label: 'Active clients', value: '${k['active_clients']}', hint: '${k['onboarding_clients']} onboarding'),
            StatTile(label: 'Pending reviews', value: '${k['pending_reviews']}', hint: '${k['negative_reviews']} negative'),
            StatTile(label: 'Scheduled posts', value: '${k['scheduled_posts']}', hint: k['failed_posts'] == 0 ? 'none failed' : '${k['failed_posts']} failed'),
            StatTile(label: 'Leads', value: compact(k['leads'] as num), delta: k['leads_change_pct'] as num),
            StatTile(label: 'GMB profiles', value: '${k['gmb_connected']}', hint: '${k['gmb_disconnected']} need connection'),
            StatTile(label: 'SEO alerts', value: '${k['seo_alerts']}', hint: 'dropped 3+ places'),
          ]),
          SectionCard(
            title: 'Growth — last 30 days',
            child: LineChart(series: [
              ChartSeries('GMB views', [for (final g in growth) g['gmb_views'] as num], const Color(0xFF0F7A45)),
              ChartSeries('Social reach ÷10', [for (final g in growth) (g['social_reach'] as num) / 10], const Color(0xFF1F63C6)),
            ]),
          ),
          if (negative.isNotEmpty || alerts.isNotEmpty)
            SectionCard(
              title: 'Needs attention',
              child: Column(children: [
                for (final r in negative.take(3))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(r['client_name'] as String),
                    subtitle: Text(r['text'] as String, maxLines: 2, overflow: TextOverflow.ellipsis),
                    trailing: Stars(r['rating'] as num),
                  ),
                for (final a in alerts.take(2))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text('“${a['keyword']}”'),
                    subtitle: Text(a['client_name'] as String),
                    trailing: StatusChip('failed', label: '#${a['previous_rank']} → #${a['current_rank']}'),
                  ),
              ]),
            ),
          if (me.isClient)
            SectionCard(
              title: 'Where your leads come from',
              child: BarList([
                ('Calls from Google', src['calls'] as num),
                ('Direction requests', src['directions'] as num),
                ('Website clicks', src['website_clicks'] as num),
                ('Social engagement', src['social_engagement'] as num),
              ]),
            )
          else
            SectionCard(
              title: 'Client performance',
              child: Column(children: [
                for (final c in perf)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(c['company_name'] as String),
                    subtitle: Text('${c['industry']} · ${c['city']} · ${compact(c['gmb_views'] as num)} views'),
                    trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                      Text('${c['leads']} leads', style: const TextStyle(fontWeight: FontWeight.w600)),
                      if ((c['pending_reviews'] as int) > 0) Text('${c['pending_reviews']} pending', style: Theme.of(context).textTheme.bodySmall),
                    ]),
                    onTap: me.sees('clients') ? () => openClient(context, c['id'] as int) : null,
                  ),
              ]),
            ),
        ];
      },
    );
  }
}
