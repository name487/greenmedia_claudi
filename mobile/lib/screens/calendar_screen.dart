import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api/models.dart';
import '../widgets/common.dart';
import 'content_screen.dart';

/// Social Hub on mobile: month grid with post dots, the selected day's posts, and expired-account alerts.
class CalendarScreen extends StatefulWidget {
  const CalendarScreen({super.key});

  @override
  State<CalendarScreen> createState() => _CalendarScreenState();
}

class _CalendarScreenState extends State<CalendarScreen> {
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);
  DateTime _day = DateUtils.dateOnly(DateTime.now());

  @override
  Widget build(BuildContext context) {
    return AsyncList<List<ContentItem>>(
      load: (api) async => [for (final c in await api.get('/api/content') as List) ContentItem.fromJson(c as Map<String, dynamic>)],
      builder: (context, items, reload) {
        final byDay = <DateTime, List<ContentItem>>{};
        for (final i in items) {
          if (i.scheduledAt != null) byDay.putIfAbsent(DateUtils.dateOnly(i.scheduledAt!), () => []).add(i);
        }
        final first = DateTime(_month.year, _month.month);
        final lead = first.weekday - 1; // Monday-first
        final days = DateUtils.getDaysInMonth(_month.year, _month.month);
        final cells = ((lead + days) / 7).ceil() * 7;
        final today = DateUtils.dateOnly(DateTime.now());
        final selected = byDay[_day] ?? [];
        final queue = items.where((i) => i.status != 'published').toList();

        return [
          SectionCard(
            title: DateFormat('MMMM y').format(_month),
            action: Row(mainAxisSize: MainAxisSize.min, children: [
              IconButton(tooltip: 'Previous month', icon: const Icon(Icons.chevron_left), onPressed: () => setState(() => _month = DateTime(_month.year, _month.month - 1))),
              IconButton(tooltip: 'Next month', icon: const Icon(Icons.chevron_right), onPressed: () => setState(() => _month = DateTime(_month.year, _month.month + 1))),
            ]),
            child: GridView.count(
              crossAxisCount: 7,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: .9,
              children: [
                for (final w in ['M', 'T', 'W', 'T', 'F', 'S', 'S']) Center(child: Text(w, style: Theme.of(context).textTheme.labelSmall)),
                for (var i = 0; i < cells; i++)
                  Builder(builder: (context) {
                    final d = DateTime(_month.year, _month.month, i - lead + 1);
                    final inMonth = d.month == _month.month;
                    final posts = byDay[d] ?? const [];
                    final isSel = d == _day;
                    return InkWell(
                      borderRadius: BorderRadius.circular(8),
                      onTap: () => setState(() => _day = d),
                      child: Container(
                        margin: const EdgeInsets.all(2),
                        decoration: BoxDecoration(
                          color: isSel ? Theme.of(context).colorScheme.primaryContainer : null,
                          border: d == today ? Border.all(color: Theme.of(context).colorScheme.primary, width: 1.5) : null,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                          Text('${d.day}', style: TextStyle(color: inMonth ? null : Theme.of(context).disabledColor)),
                          const SizedBox(height: 2),
                          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                            for (final _ in posts.take(3))
                              Container(width: 5, height: 5, margin: const EdgeInsets.symmetric(horizontal: 1), decoration: const BoxDecoration(color: Color(0xFF1F63C6), shape: BoxShape.circle)),
                          ]),
                        ]),
                      ),
                    );
                  }),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 8, 4, 4),
            child: Text(DateFormat('EEEE, d MMMM').format(_day), style: Theme.of(context).textTheme.titleSmall),
          ),
          if (selected.isEmpty) const EmptyState('Nothing scheduled this day.'),
          for (final c in selected) ContentTile(item: c, onChanged: reload),
          const SizedBox(height: 8),
          SectionCard(
            title: 'Publishing queue (${queue.length})',
            child: Column(children: [
              for (final c in queue.take(10))
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(c.topic),
                  subtitle: Text('${c.clientName} · ${fmtDateTime(c.scheduledAt)}'),
                  trailing: StatusChip(c.status),
                ),
            ]),
          ),
        ];
      },
    );
  }
}
