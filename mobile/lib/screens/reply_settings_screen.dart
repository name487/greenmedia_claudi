import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../data/languages.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _navy = Color(0xFF0E1A3A);
const _lengthLabels = {'ultra': 'Ultra', 'short': 'Short', 'medium': 'Medium', 'long': 'Long'};

// The sample shown while editing (the server's own samples are the same text).
const _sampleLines = {
  ('positive', 'en'): [
    'Thank you so much for your kind words! 😊', 'We\'re really glad you liked your experience at {c}.',
    'We always try to give every customer our very best.', 'Your feedback means a lot to our whole team.', 'Looking forward to seeing you again soon!',
  ],
  ('negative', 'en'): [
    'We\'re really sorry to hear about your experience.', 'This isn\'t the standard we hold ourselves to at {c}.',
    'We\'d like to make it right — please call us so we can look into it personally.', 'Your feedback helps us improve, and we\'ve shared it with the team.',
    'We hope to welcome you back and do better.',
  ],
  ('positive', 'hi'): [
    'आपके सुंदर शब्दों के लिए बहुत-बहुत धन्यवाद! 😊', 'हमें ख़ुशी है कि {c} में आपका अनुभव अच्छा रहा।', 'हम हर ग्राहक को सबसे अच्छी सेवा देने की कोशिश करते हैं।',
    'आपकी राय हमारी पूरी टीम के लिए बहुत मायने रखती है।', 'जल्द ही फिर मिलेंगे!',
  ],
  ('negative', 'hi'): [
    'आपके अनुभव के बारे में जानकर हमें सचमुच खेद है।', '{c} में हम ऐसी सेवा नहीं देना चाहते।', 'कृपया हमें कॉल करें, ताकि हम ख़ुद इस पर ध्यान दे सकें।',
    'आपकी राय से हमें सुधार करने में मदद मिलती है।', 'हम आपको फिर से बेहतर सेवा देना चाहेंगे।',
  ],
};
const _count = {'ultra': 1, 'short': 2, 'medium': 3, 'long': 5};

/// How AI review replies are written, per star category: length and language. Saved to the business's brand voice.
class ReplySettingsScreen extends StatefulWidget {
  const ReplySettingsScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<ReplySettingsScreen> createState() => _ReplySettingsScreenState();
}

class _ReplySettingsScreenState extends State<ReplySettingsScreen> {
  Map<String, dynamic>? _data;
  late Map<String, Map<String, dynamic>> _settings;
  String _cat = 'positive';
  final Set<String> _extraLangs = {};
  bool _saving = false;
  String? _error;

  String get _path => '/api/clients/${widget.clientId}/reply-settings';
  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _take(Map<String, dynamic> d) {
    _data = d;
    _settings = {
      for (final e in (d['settings'] as Map<String, dynamic>).entries) e.key: Map<String, dynamic>.from(e.value as Map),
    };
    for (final s in _settings.values) {
      final code = s['language'] as String? ?? '';
      if (code.isNotEmpty && code != 'en' && code != 'hi') _extraLangs.add(code);
    }
  }

  Future<void> _load() async {
    try {
      final d = await _api.get(_path) as Map<String, dynamic>;
      setState(() => _take(d));
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    final ok = await runAction(context, (api) async {
      final d = await api.put(_path, _settings) as Map<String, dynamic>;
      setState(() => _take(d));
    }, success: 'Reply settings saved');
    if (mounted) setState(() => _saving = false);
    if (ok && mounted) Navigator.pop(context, true);
  }

  Map<String, dynamic> get _cur => _settings[_cat]!;

  void _setLanguage(String code) => setState(() {
        _cur['language'] = code;
        _cur['language_name'] = code.isEmpty ? '' : languageName(code);
        if (code.isNotEmpty && code != 'en' && code != 'hi') _extraLangs.add(code);
      });

  String _sample() {
    final lang = (_cur['language'] as String? ?? '').isEmpty ? 'en' : _cur['language'] as String;
    final lines = _sampleLines[(_cat, lang)] ?? _sampleLines[(_cat, 'en')]!;
    final company = (_data!['account'] as Map)['name'] as String;
    return lines.take(_count[_cur['length']] ?? 2).join(' ').replaceAll('{c}', company);
  }

  String _sampleNote() {
    final code = _cur['language'] as String? ?? '';
    if (code.isEmpty) return 'Replies are written in the same language as the review.';
    if (code != 'en' && code != 'hi') return 'Shown in English — AI replies will be written in ${languageName(code)}.';
    return '';
  }

  Future<void> _pickLanguage() async {
    final code = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _LanguageSheet(selected: _cur['language'] as String? ?? ''),
    );
    if (code != null) _setLanguage(code);
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final section = t.labelMedium?.copyWith(fontWeight: FontWeight.w800, letterSpacing: .6, color: Theme.of(context).hintColor);
    return Scaffold(
      appBar: AppBar(
        backgroundColor: _navy,
        foregroundColor: Colors.white,
        title: const Text('Reply Settings'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 10),
            child: OutlinedButton(
              key: const Key('reply-settings-save'),
              style: OutlinedButton.styleFrom(foregroundColor: Colors.white, side: const BorderSide(color: Colors.white54), visualDensity: VisualDensity.compact),
              onPressed: _data == null || _saving ? null : _save,
              child: _saving ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Save'),
            ),
          ),
        ],
      ),
      body: _error != null
          ? EmptyState(_error!)
          : _data == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 32), children: [
                  Text('ACCOUNT', style: section),
                  const SizedBox(height: 8),
                  _account(context),
                  const SizedBox(height: 20),
                  Text('SELECT REPLY CATEGORY', style: section),
                  const SizedBox(height: 8),
                  SegmentedButton<String>(
                    showSelectedIcon: false,
                    segments: const [ButtonSegment(value: 'positive', label: Text('3-5 Stars')), ButtonSegment(value: 'negative', label: Text('1-2 Stars'))],
                    selected: {_cat},
                    onSelectionChanged: (s) => setState(() => _cat = s.first),
                  ),
                  const SizedBox(height: 20),
                  Text('SAMPLE REPLY', style: section),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: .5),
                      border: const Border(left: BorderSide(color: Color(0xFFE5484D), width: 3)),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(_sample(), key: const Key('sample-reply')),
                  ),
                  if (_sampleNote().isNotEmpty)
                    Padding(padding: const EdgeInsets.only(top: 6), child: Text(_sampleNote(), style: t.bodySmall?.copyWith(color: Theme.of(context).hintColor))),
                  const SizedBox(height: 20),
                  Text('REPLY SETTINGS', style: section),
                  const SizedBox(height: 10),
                  Text('Reply Length', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  Text('How long AI replies should be for ${_cat == 'positive' ? '3-5' : '1-2'} star reviews', style: t.bodySmall),
                  _lengthSlider(context),
                  const SizedBox(height: 12),
                  Text('Reply Language', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, runSpacing: 8, children: [
                    for (final code in ['', 'en', 'hi', ..._extraLangs]) _languageChip(context, code),
                  ]),
                  const SizedBox(height: 10),
                  InkWell(
                    key: const Key('search-language'),
                    onTap: _pickLanguage,
                    borderRadius: BorderRadius.circular(10),
                    child: InputDecorator(
                      decoration: const InputDecoration(hintText: 'Search Language', suffixIcon: Icon(Icons.search)),
                      child: Text('Search Language', style: t.bodyMedium?.copyWith(color: Theme.of(context).hintColor)),
                    ),
                  ),
                ]),
    );
  }

  Widget _account(BuildContext context) {
    final a = _data!['account'] as Map<String, dynamic>;
    final name = a['name'] as String;
    final initials = name.split(' ').where((w) => w.isNotEmpty).take(2).map((w) => w[0].toUpperCase()).join();
    return Row(children: [
      CircleAvatar(backgroundColor: const Color(0xFF1F63C6), child: Text(initials, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700))),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
          if ((a['email'] as String? ?? '').isNotEmpty) Text(a['email'] as String, style: Theme.of(context).textTheme.bodySmall),
        ]),
      ),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: const Color(0xFFFDE8EC), borderRadius: BorderRadius.circular(99)),
        child: Text('${a['replies_24h']} ${a['replies_24h'] == 1 ? 'reply' : 'replies'} in 24 hours', style: const TextStyle(color: Color(0xFFD0364F), fontSize: 11)),
      ),
    ]);
  }

  Widget _lengthSlider(BuildContext context) {
    final lengths = (_data!['lengths'] as List).cast<String>();
    final i = lengths.indexOf(_cur['length'] as String).clamp(0, lengths.length - 1);
    return Column(children: [
      Slider(
        key: const Key('reply-length'),
        value: i.toDouble(),
        min: 0,
        max: (lengths.length - 1).toDouble(),
        divisions: lengths.length - 1,
        label: _lengthLabels[lengths[i]],
        onChanged: (v) => setState(() => _cur['length'] = lengths[v.round()]),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          for (final (k, l) in lengths.indexed)
            Text(_lengthLabels[l] ?? l,
                style: TextStyle(fontSize: 12, fontWeight: k == i ? FontWeight.w700 : FontWeight.w400, color: k == i ? null : Theme.of(context).hintColor)),
        ]),
      ),
    ]);
  }

  Widget _languageChip(BuildContext context, String code) {
    final selected = (_cur['language'] as String? ?? '') == code;
    final scheme = Theme.of(context).colorScheme;
    return InkWell(
      key: Key('lang-${code.isEmpty ? 'auto' : code}'),
      borderRadius: BorderRadius.circular(8),
      onTap: () => _setLanguage(code),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
        decoration: BoxDecoration(
          border: Border.all(color: selected ? scheme.onSurface : Theme.of(context).dividerColor, width: selected ? 1.5 : 1),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(code.isEmpty ? 'Same as review' : languageName(code)),
          const SizedBox(width: 8),
          Icon(selected ? Icons.check_circle : Icons.radio_button_unchecked, size: 18, color: selected ? scheme.onSurface : Theme.of(context).hintColor),
        ]),
      ),
    );
  }
}

class _LanguageSheet extends StatefulWidget {
  const _LanguageSheet({required this.selected});
  final String selected;

  @override
  State<_LanguageSheet> createState() => _LanguageSheetState();
}

class _LanguageSheetState extends State<_LanguageSheet> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final q = _q.trim().toLowerCase();
    final rows = q.isEmpty ? languages : languages.where((l) => l.$2.toLowerCase().contains(q) || l.$3.toLowerCase().contains(q) || l.$1 == q).toList();
    return SizedBox(
      height: MediaQuery.of(context).size.height * .8,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
          child: Row(children: [
            Expanded(child: Text('Select Language', style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700))),
            IconButton(tooltip: 'Close', icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: TextField(
            key: const Key('language-search'),
            autofocus: false,
            onChanged: (v) => setState(() => _q = v),
            decoration: const InputDecoration(hintText: 'Search Language', prefixIcon: Icon(Icons.search), isDense: true),
          ),
        ),
        Expanded(
          child: rows.isEmpty
              ? const EmptyState('No language found')
              : ListView.builder(
                  itemCount: rows.length,
                  itemBuilder: (_, i) {
                    final (code, name, native) = rows[i];
                    return ListTile(
                      dense: true,
                      title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
                      subtitle: Text(native),
                      selected: code == widget.selected,
                      trailing: code == widget.selected ? const Icon(Icons.check) : null,
                      onTap: () => Navigator.pop(context, code),
                    );
                  },
                ),
        ),
      ]),
    );
  }
}
