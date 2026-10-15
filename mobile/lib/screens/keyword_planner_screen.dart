import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _competition = {'low': Color(0xFF2E9E5B), 'medium': Color(0xFFE08A1E), 'high': Color(0xFFE5484D)};

/// Keywords the business tracks, plus a search for new ideas with monthly searches and competition.
/// Each search uses one of the month's search credits.
class KeywordPlannerScreen extends StatefulWidget {
  const KeywordPlannerScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<KeywordPlannerScreen> createState() => _KeywordPlannerScreenState();
}

class _KeywordPlannerScreenState extends State<KeywordPlannerScreen> {
  final _city = TextEditingController(), _keyword = TextEditingController();
  List<Map<String, dynamic>> _tracked = [];
  Map<String, dynamic>? _credits;
  List<Map<String, dynamic>>? _results;
  bool _loading = true, _searching = false;
  String? _error;

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}/keyword-planner';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _city.dispose();
    _keyword.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await _api.get(_base) as Map<String, dynamic>;
      setState(() {
        _tracked = (d['tracked'] as List).cast<Map<String, dynamic>>();
        _credits = d['credits'] as Map<String, dynamic>;
        if (_city.text.isEmpty) _city.text = d['city'] as String? ?? '';
        _loading = false;
      });
    } on ApiException catch (e) {
      setState(() {
        _error = e.message;
        _loading = false;
      });
    }
  }

  Future<void> _search() async {
    if (_keyword.text.trim().length < 2) return;
    FocusScope.of(context).unfocus();
    setState(() => _searching = true);
    await runAction(context, (api) async {
      final r = await api.post('$_base/search', {'keyword': _keyword.text.trim(), 'city': _city.text.trim(), 'country': 'India'}) as Map<String, dynamic>;
      setState(() {
        _results = (r['results'] as List).cast<Map<String, dynamic>>();
        _credits = r['credits'] as Map<String, dynamic>;
      });
    });
    if (mounted) setState(() => _searching = false);
  }

  Future<void> _add(Map<String, dynamic> r) async {
    await runAction(context, (api) async {
      final k = await api.post('$_base/keywords', {'keyword': r['keyword'], 'location': _city.text.trim(), 'volume': r['searches']}) as Map<String, dynamic>;
      setState(() => _tracked = [..._tracked, k]);
    }, success: 'Added “${r['keyword']}”');
  }

  Future<void> _remove(Map<String, dynamic> k) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Remove keyword?'),
        content: Text('Stop tracking “${k['keyword']}”?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(d, true), child: const Text('Remove')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    if (await runAction(context, (api) => api.delete('$_base/keywords/${k['id']}'))) {
      setState(() => _tracked = _tracked.where((x) => x['id'] != k['id']).toList());
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final n = NumberFormat.decimalPattern('en_IN');
    final trackedNames = {for (final k in _tracked) (k['keyword'] as String).toLowerCase()};
    final section = t.labelMedium?.copyWith(fontWeight: FontWeight.w800, letterSpacing: .6, color: Theme.of(context).hintColor);
    return Scaffold(
      appBar: AppBar(title: const Text('Keyword Planner')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? EmptyState(_error!)
              : ListView(padding: const EdgeInsets.fromLTRB(12, 8, 12, 24), children: [
                  Text('ADDED KEYWORDS', style: section),
                  const SizedBox(height: 6),
                  if (_tracked.isEmpty) const EmptyState('No keywords yet — search below and tap ADD.'),
                  for (final (i, k) in _tracked.indexed)
                    Card(
                      child: ListTile(
                        leading: CircleAvatar(radius: 13, backgroundColor: const Color(0xFFE8457C), child: Text('${i + 1}', style: const TextStyle(color: Colors.white, fontSize: 12))),
                        title: Text(k['keyword'] as String),
                        subtitle: Text(k['location'] as String? ?? ''),
                        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                          Text(n.format(k['volume']), style: const TextStyle(fontWeight: FontWeight.w600)),
                          IconButton(tooltip: 'Remove', icon: const Icon(Icons.close, color: Color(0xFFE5484D)), onPressed: () => _remove(k)),
                        ]),
                      ),
                    ),
                  const SizedBox(height: 16),
                  Text('KEYWORD SEARCH', style: section),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                        const InputDecorator(
                          decoration: InputDecoration(labelText: 'Country', prefixIcon: Icon(Icons.flag_outlined), enabled: false),
                          child: Text('India'),
                        ),
                        const SizedBox(height: 10),
                        TextField(controller: _city, decoration: const InputDecoration(labelText: 'Locality / City', prefixIcon: Icon(Icons.place_outlined))),
                        const SizedBox(height: 10),
                        TextField(
                          key: const Key('kp-keyword'),
                          controller: _keyword,
                          textInputAction: TextInputAction.search,
                          onSubmitted: (_) => _search(),
                          decoration: const InputDecoration(labelText: 'Keyword', hintText: 'Enter keyword', prefixIcon: Icon(Icons.search)),
                        ),
                        const SizedBox(height: 12),
                        DecoratedBox(
                          decoration: BoxDecoration(
                              gradient: const LinearGradient(colors: [Color(0xFFB04DE8), Color(0xFFFF7A2F)]), borderRadius: BorderRadius.circular(10)),
                          child: FilledButton(
                            style: FilledButton.styleFrom(backgroundColor: Colors.transparent, shadowColor: Colors.transparent, minimumSize: const Size.fromHeight(46)),
                            onPressed: _searching ? null : _search,
                            child: _searching
                                ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : const Text('Search', style: TextStyle(color: Colors.white)),
                          ),
                        ),
                        if (_credits != null) ...[
                          const SizedBox(height: 12),
                          Row(children: [
                            const Icon(Icons.auto_awesome, size: 16, color: Color(0xFFB04DE8)),
                            const SizedBox(width: 6),
                            Expanded(child: Text('Search credits used', style: t.bodySmall)),
                            Text('${_credits!['used']} / ${_credits!['limit']}', key: const Key('kp-credits'), style: t.bodySmall?.copyWith(fontWeight: FontWeight.w700)),
                          ]),
                          const SizedBox(height: 4),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(99),
                            child: LinearProgressIndicator(value: (_credits!['used'] as int) / (_credits!['limit'] as int), minHeight: 5),
                          ),
                        ],
                      ]),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text('SEARCH RESULTS', style: section),
                  if (_results == null || _results!.isEmpty)
                    EmptyState(_results == null ? 'Search a keyword to see ideas.' : 'No search results found.')
                  else ...[
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Text('“Google” = real searches that showed your profile. Others are estimated monthly searches.', style: t.bodySmall),
                    ),
                    for (final (i, r) in _results!.indexed)
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
                          child: Row(children: [
                            Expanded(
                              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                Text('${i + 1}. ${r['keyword']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                                Text('Searches: ${n.format(r['searches'])}', style: t.bodySmall),
                              ]),
                            ),
                            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                              _Badge(r['source'] == 'google' ? 'GOOGLE' : '${r['competition'] ?? 'n/a'}'.toUpperCase(),
                                  r['source'] == 'google' ? const Color(0xFF3B6FE0) : _competition[r['competition']] ?? Colors.grey),
                              const SizedBox(height: 6),
                              trackedNames.contains((r['keyword'] as String).toLowerCase())
                                  ? const Text('ADDED', style: TextStyle(color: Color(0xFF2E9E5B), fontWeight: FontWeight.w700, fontSize: 12))
                                  : FilledButton(
                                      style: FilledButton.styleFrom(backgroundColor: const Color(0xFFE8457C), visualDensity: VisualDensity.compact),
                                      onPressed: () => _add(r),
                                      child: const Text('ADD'),
                                    ),
                            ]),
                          ]),
                        ),
                      ),
                  ],
                ]),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge(this.text, this.colour);
  final String text;
  final Color colour;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: colour.withValues(alpha: .12), borderRadius: BorderRadius.circular(99)),
        child: Text(text, style: TextStyle(color: colour, fontSize: 10, fontWeight: FontWeight.w700)),
      );
}
