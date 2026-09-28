import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/session.dart';
import '../widgets/common.dart';

Future<void> showServerDialog(BuildContext context) async {
  final session = context.read<Session>();
  final ctrl = TextEditingController(text: session.api.baseUrl);
  final url = await showDialog<String>(
    context: context,
    builder: (d) => AlertDialog(
      title: const Text('API server'),
      content: TextField(controller: ctrl, keyboardType: TextInputType.url, decoration: const InputDecoration(hintText: 'https://api.yourdomain.com')),
      actions: [
        TextButton(onPressed: () => Navigator.pop(d), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(d, defaultApiUrl()), child: const Text('Reset')),
        FilledButton(onPressed: () => Navigator.pop(d, ctrl.text), child: const Text('Save')),
      ],
    ),
  );
  ctrl.dispose();
  if (url != null && url.trim().isNotEmpty) await session.setBaseUrl(url);
}

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = context.watch<Session>();
    final me = session.me!;
    return AsyncList<Map<String, dynamic>>(
      load: (api) async => await api.get('/api/health') as Map<String, dynamic>,
      builder: (context, health, _) => [
        Card(
          child: ListTile(
            leading: CircleAvatar(child: Text(me.name[0])),
            title: Text(me.name),
            subtitle: Text('${me.email}\n${me.clientName ?? me.roleLabel}'),
            isThreeLine: true,
          ),
        ),
        Card(
          child: Column(children: [
            ListTile(
              leading: const Icon(Icons.dns_outlined),
              title: const Text('API server'),
              subtitle: Text(session.api.baseUrl),
              trailing: const Icon(Icons.edit_outlined),
              onTap: () => showServerDialog(context),
            ),
            ListTile(
              leading: const Icon(Icons.auto_awesome_outlined),
              title: const Text('AI'),
              subtitle: Text(health['ai'] == true ? '${health['provider']} · ${health['model']}' : 'Offline templates (no AI key on the server)'),
              trailing: StatusChip(health['ai'] == true ? 'connected' : 'draft', label: health['ai'] == true ? 'On' : 'Off'),
            ),
          ]),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(onPressed: session.logout, icon: const Icon(Icons.logout), label: const Text('Sign out')),
      ],
    );
  }
}
