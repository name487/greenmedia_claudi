import 'package:flutter/material.dart';

import '../api/models.dart';
import '../widgets/common.dart';
import 'client_detail_screen.dart';

class ClientsScreen extends StatefulWidget {
  const ClientsScreen({super.key});

  @override
  State<ClientsScreen> createState() => _ClientsScreenState();
}

class _ClientsScreenState extends State<ClientsScreen> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    return AsyncList<List<ClientBrief>>(
      load: loadClients,
      builder: (context, clients, _) {
        final q = _q.toLowerCase();
        final rows = clients.where((c) => '${c.companyName} ${c.city} ${c.industry}'.toLowerCase().contains(q)).toList();
        return [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: TextField(
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search clients, cities, industries', isDense: true),
              onChanged: (v) => setState(() => _q = v),
            ),
          ),
          Text('${rows.length} of ${clients.length} clients', style: Theme.of(context).textTheme.bodySmall),
          for (final c in rows)
            Card(
              child: ListTile(
                title: Text(c.companyName),
                subtitle: Row(children: [
                  Flexible(child: Text('${c.industry} · ${c.city} · ', overflow: TextOverflow.ellipsis)),
                  Stars(c.rating, size: 12),
                  Text(' ${c.rating}'),
                ]),
                trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                  StatusChip(c.status),
                  if (c.pendingReviews > 0) Text('${c.pendingReviews} reviews', style: Theme.of(context).textTheme.bodySmall),
                ]),
                onTap: () => openClient(context, c.id),
              ),
            ),
        ];
      },
    );
  }
}
