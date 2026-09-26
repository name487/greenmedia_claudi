import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const taskStatuses = [('todo', 'To do'), ('in_progress', 'In progress'), ('review', 'Review'), ('done', 'Done')];

class TasksScreen extends StatefulWidget {
  const TasksScreen({super.key});

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  bool _mine = false;
  final _key = GlobalKey<AsyncListState<(List<TaskItem>, List<dynamic>)>>();

  Future<(List<TaskItem>, List<dynamic>)> _load(ApiClient api) async {
    final tasks = [for (final t in await api.get('/api/tasks', {'mine': _mine ? 'true' : null}) as List) TaskItem.fromJson(t as Map<String, dynamic>)];
    final audit = await api.get('/api/audit', {'limit': 20}) as List;
    return (tasks, audit);
  }

  Future<void> _newTask() async {
    final created = await showModalBottomSheet<bool>(context: context, isScrollControlled: true, builder: (_) => const _NewTaskSheet());
    if (created == true) _key.currentState?.reload();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton(tooltip: 'New task', onPressed: _newTask, child: const Icon(Icons.add)),
      body: AsyncList<(List<TaskItem>, List<dynamic>)>(
        key: _key,
        load: _load,
        builder: (context, data, reload) {
          final (tasks, audit) = data;
          return [
            SwitchListTile(
              title: const Text('Only my tasks'),
              value: _mine,
              onChanged: (v) {
                _mine = v;
                reload();
              },
            ),
            for (final (status, label) in taskStatuses) ...[
              Padding(padding: const EdgeInsets.fromLTRB(4, 12, 4, 4), child: Text('$label (${tasks.where((t) => t.status == status).length})', style: Theme.of(context).textTheme.titleSmall)),
              for (final t in tasks.where((t) => t.status == status))
                Card(
                  child: ListTile(
                    title: Text(t.title),
                    subtitle: Text('${t.clientName ?? ''} · ${t.assigneeName ?? ''} · due ${fmtDate(t.dueDate)}'),
                    trailing: PopupMenuButton<String>(
                      tooltip: 'Move',
                      child: StatusChip(t.priority),
                      onSelected: (s) async {
                        if (await runAction(context, (api) => api.patch('/api/tasks/${t.id}', {'status': s}))) reload();
                      },
                      itemBuilder: (_) => [for (final (s, l) in taskStatuses) PopupMenuItem(value: s, enabled: s != t.status, child: Text('Move to $l'))],
                    ),
                  ),
                ),
            ],
            SectionCard(
              title: 'Audit trail',
              child: Column(children: [
                for (final a in audit.cast<Map<String, dynamic>>())
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: Text('${a['user_name']} ${a['action']}'),
                    subtitle: Text('${a['client_name'] ?? ''} · ${fmtDateTime(parseDate(a['created_at']))}'),
                  ),
              ]),
            ),
            const SizedBox(height: 72),
          ];
        },
      ),
    );
  }
}

class _NewTaskSheet extends StatefulWidget {
  const _NewTaskSheet();

  @override
  State<_NewTaskSheet> createState() => _NewTaskSheetState();
}

class _NewTaskSheetState extends State<_NewTaskSheet> {
  final _title = TextEditingController();
  List<ClientBrief>? _clients;
  List<dynamic>? _staff;
  int? _clientId, _assignee;
  String _priority = 'medium';

  @override
  void initState() {
    super.initState();
    final s = context.read<Session>();
    _assignee = s.me!.id;
    Future.wait([loadClients(s.api), s.api.get('/api/auth/users')]).then((r) {
      if (!mounted) return;
      setState(() {
        _clients = r[0] as List<ClientBrief>;
        _staff = r[1] as List;
        _clientId = _clients!.isEmpty ? null : _clients!.first.id;
      });
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.viewInsetsOf(context).bottom),
      child: _clients == null
          ? const SizedBox(height: 120, child: Center(child: CircularProgressIndicator()))
          : Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text('New task', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              TextField(controller: _title, autofocus: true, decoration: const InputDecoration(labelText: 'What needs doing?')),
              const SizedBox(height: 12),
              ClientPicker(clients: _clients!, value: _clientId, allowAll: false, onChanged: (v) => setState(() => _clientId = v)),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: _assignee,
                decoration: const InputDecoration(labelText: 'Assign to', isDense: true),
                items: [for (final u in _staff!.cast<Map<String, dynamic>>()) DropdownMenuItem(value: u['id'] as int, child: Text('${u['name']} · ${u['role_label']}'))],
                onChanged: (v) => setState(() => _assignee = v),
              ),
              const SizedBox(height: 12),
              SegmentedButton<String>(
                segments: const [ButtonSegment(value: 'low', label: Text('Low')), ButtonSegment(value: 'medium', label: Text('Medium')), ButtonSegment(value: 'high', label: Text('High'))],
                selected: {_priority},
                onSelectionChanged: (v) => setState(() => _priority = v.first),
              ),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: () async {
                  final nav = Navigator.of(context);
                  final ok = await runAction(
                    context,
                    (api) => api.post('/api/tasks', {'title': _title.text.trim(), 'client_id': _clientId, 'assigned_to': _assignee, 'priority': _priority}),
                    success: 'Task created',
                  );
                  if (ok) nav.pop(true);
                },
                child: const Text('Create task'),
              ),
            ]),
    );
  }
}
