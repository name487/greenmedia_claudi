import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/models.dart';
import '../state/session.dart';
import 'analytics_screen.dart';
import 'business_score_screen.dart';
import 'calendar_screen.dart';
import 'clients_screen.dart';
import 'ai_post/ai_post_screen.dart';
import 'content_screen.dart';
import 'dashboard_screen.dart';
import 'google_media_screen.dart';
import 'google_post_screen.dart';
import 'owner_report_screen.dart';
import 'owner_reviews_screen.dart';
import 'reports_screen.dart';
import 'reviews_screen.dart';
import 'seo_screen.dart';
import 'settings_screen.dart';
import 'tasks_screen.dart';

class Destination {
  const Destination(this.section, this.label, this.icon, this.builder, {this.ownerLabel, this.needs, this.ownerOnly = false});
  final String section, label;
  final String? ownerLabel; // wording for business owners (client role)
  final String? needs; // the role section that unlocks it, when it isn't [section]
  final bool ownerOnly;
  final IconData icon;
  final WidgetBuilder builder;
}

final destinations = <Destination>[
  // A business owner's home is their own Business Score; the agency sees the multi-client dashboard.
  Destination('dashboard', 'Home', Icons.space_dashboard_outlined, (c) {
    final me = c.read<Session>().me!;
    return me.isClient ? BusinessScoreScreen(clientId: me.clientId!) : const DashboardScreen();
  }),
  // Owners get Dhanda-style Review Replies (post / edit / delete, keywords, settings); staff keep the review queue.
  Destination('reviews', 'Reviews', Icons.star_outline_rounded, (c) {
    final me = c.read<Session>().me!;
    return me.isClient ? OwnerReviewsScreen(clientId: me.clientId!) : const ReviewsScreen();
  }, ownerLabel: 'Replies'),
  // Owners get Dhanda-style AI Post (viral videos, posters from their products, approve & schedule).
  Destination('content', 'Content', Icons.edit_note_rounded, (c) {
    final me = c.read<Session>().me!;
    return me.isClient ? AiPostScreen(clientId: me.clientId!) : const ContentScreen();
  }, ownerLabel: 'AI Post'),
  Destination('google_post', 'Google Post', Icons.article_outlined, (c) => GooglePostScreen(clientId: c.read<Session>().me!.clientId!),
      needs: 'content', ownerOnly: true),
  Destination('google_media', 'Google Media', Icons.photo_library_outlined, (c) => GoogleMediaScreen(clientId: c.read<Session>().me!.clientId!),
      needs: 'content', ownerOnly: true),
  Destination('social', 'Calendar', Icons.calendar_month_outlined, (_) => const CalendarScreen()),
  Destination('clients', 'Clients', Icons.groups_outlined, (_) => const ClientsScreen()),
  Destination('analytics', 'Analytics', Icons.insights_outlined, (_) => const AnalyticsScreen()),
  Destination('seo', 'SEO', Icons.travel_explore_outlined, (_) => const SeoScreen()),
  // Owners get Dhanda-style Report (Performance Summary, Growth Action / Performance Report, PDF); staff keep the reports list.
  Destination('reports', 'Reports', Icons.description_outlined, (c) {
    final me = c.read<Session>().me!;
    return me.isClient ? OwnerReportScreen(clientId: me.clientId!) : const ReportsScreen();
  }, ownerLabel: 'Report'),
  Destination('tasks', 'Tasks', Icons.task_alt_outlined, (_) => const TasksScreen()),
];

/// Owner tabs that draw their own top bar
const _ownBar = {'dashboard', 'reviews', 'content', 'google_post', 'google_media', 'reports'};

/// Business owners get Dhanda's five tabs; the rest (Analytics, Reports, Settings) opens from their avatar on Home.
int _tabCount(Me me) => me.isClient ? 5 : 4;

List<Destination> _allowed(Me me) => destinations.where((d) => me.sees(d.needs ?? d.section) && (!d.ownerOnly || me.isClient)).toList();

String label(Destination d, Me me) => me.isClient ? d.ownerLabel ?? d.label : d.label;

/// Bottom navigation with the role's first four sections; everything else lives under "More".
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;
  // One primary scroll controller per tab: the tabs stay alive side by side in the IndexedStack, and sharing the
  // route's controller breaks keyboard scrolling ("too many elements") and scroll-to-top.
  final _scrollers = <String, ScrollController>{};

  @override
  void dispose() {
    for (final c in _scrollers.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final me = context.watch<Session>().me!;
    final tabs = _allowed(me).take(_tabCount(me)).toList();

    return Scaffold(
      body: IndexedStack(index: _index, children: [
        for (final t in tabs)
          PrimaryScrollController(
            controller: _scrollers.putIfAbsent(t.section, ScrollController.new),
            // The owner's home and Review Replies draw their own top bar
            child: me.isClient && _ownBar.contains(t.section)
                ? t.builder(context)
                : _Page(title: label(t, me), child: t.builder(context)),
          ),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) {
          if (i == tabs.length) {
            showMoreMenu(context);
          } else {
            setState(() => _index = i);
          }
        },
        destinations: [
          for (final t in tabs) NavigationDestination(icon: Icon(t.icon), label: label(t, me)),
          if (!me.isClient) const NavigationDestination(icon: Icon(Icons.menu_rounded), label: 'More'),
        ],
      ),
    );
  }
}

/// Everything that isn't a tab, plus Settings and Sign out ("More" for staff; the avatar on an owner's Home).
void showMoreMenu(BuildContext context) {
  final session = context.read<Session>();
  final more = _allowed(session.me!).skip(_tabCount(session.me!)).toList();
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
            title: Text(label(d, session.me!)),
            onTap: () {
              Navigator.pop(sheet);
              Navigator.push(context, MaterialPageRoute<void>(builder: (c) =>
                  session.me!.isClient && _ownBar.contains(d.section) ? d.builder(c) : _Page(title: label(d, session.me!), child: d.builder(c))));
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

class _Page extends StatelessWidget {
  const _Page({required this.title, required this.child});
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(appBar: AppBar(title: Text(title)), body: SafeArea(top: false, child: child));
}
