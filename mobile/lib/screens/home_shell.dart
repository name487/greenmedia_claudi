import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/session.dart';
import 'analytics_screen.dart';
import 'calendar_screen.dart';
import 'clients_screen.dart';
import 'content_screen.dart';
import 'dashboard_screen.dart';
import 'reports_screen.dart';
import 'reviews_screen.dart';
import 'seo_screen.dart';
import 'settings_screen.dart';
import 'tasks_screen.dart';

class Destination {
  const Destination(this.section, this.label, this.icon, this.builder);
  final String section, label;
  final IconData icon;
  final WidgetBuilder builder;
}

final destinations = <Destination>[
  Destination('dashboard', 'Dashboard', Icons.space_dashboard_outlined, (_) => const DashboardScreen()),
  Destination('reviews', 'Reviews', Icons.star_outline_rounded, (_) => const ReviewsScreen()),
  Destination('content', 'Content', Icons.edit_note_rounded, (_) => const ContentScreen()),
  Destination('social', 'Calendar', Icons.calendar_month_outlined, (_) => const CalendarScreen()),
  Destination('clients', 'Clients', Icons.groups_outlined, (_) => const ClientsScreen()),
  Destination('analytics', 'Analytics', Icons.insights_outlined, (_) => const AnalyticsScreen()),
  Destination('seo', 'SEO', Icons.travel_explore_outlined, (_) => const SeoScreen()),
  Destination('reports', 'Reports', Icons.description_outlined, (_) => const ReportsScreen()),
  Destination('tasks', 'Tasks', Icons.task_alt_outlined, (_) => const TasksScreen()),
];

/// Bottom navigation with the role's first four sections; everything else lives under "More".
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final me = context.watch<Session>().me!;
    final allowed = destinations.where((d) => me.sees(d.section)).toList();
    final tabs = allowed.take(4).toList();
    final more = allowed.skip(4).toList();

    return Scaffold(
      body: IndexedStack(index: _index, children: [for (final t in tabs) _Page(title: t.label, child: t.builder(context))]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) {
          if (i == tabs.length) {
            _openMore(context, more);
          } else {
            setState(() => _index = i);
          }
        },
        destinations: [
          for (final t in tabs) NavigationDestination(icon: Icon(t.icon), label: t.label),
          const NavigationDestination(icon: Icon(Icons.menu_rounded), label: 'More'),
        ],
      ),
    );
  }

  void _openMore(BuildContext context, List<Destination> more) {
    final session = context.read<Session>();
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: CircleAvatar(child: Text(session.me!.name[0])),
            title: Text(session.me!.name),
            subtitle: Text(session.me!.clientName ?? session.me!.roleLabel),
          ),
          const Divider(),
          for (final d in more)
            ListTile(
              leading: Icon(d.icon),
              title: Text(d.label),
              onTap: () {
                Navigator.pop(sheet);
                Navigator.push(context, MaterialPageRoute<void>(builder: (c) => _Page(title: d.label, child: d.builder(c))));
              },
            ),
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('Settings'),
            onTap: () {
              Navigator.pop(sheet);
              Navigator.push(context, MaterialPageRoute<void>(builder: (_) => const _Page(title: 'Settings', child: SettingsScreen())));
            },
          ),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Sign out'),
            onTap: () {
              Navigator.pop(sheet);
              session.logout();
            },
          ),
        ]),
      ),
    );
  }
}

class _Page extends StatelessWidget {
  const _Page({required this.title, required this.child});
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: Text(title)), body: SafeArea(top: false, child: child));
}
