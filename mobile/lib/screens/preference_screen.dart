
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import 'ai_post/items_screen.dart' show AddItemScreen;
import 'ai_post/shared.dart';
import 'meta_connect_screen.dart';
import 'owner_settings_screen.dart' show LegalScreen;

const _blue = Color(0xFF1F63C6);

/// Preference (business owners → Settings): one page in four parts — Socials, Selling, Branding and Advance Settings —
/// with a progress bar for the six things that make posts look like the business. Each field saves on its own.
class PreferenceScreen extends StatefulWidget {
  const PreferenceScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<PreferenceScreen> createState() => _PreferenceScreenState();
}

class _PreferenceScreenState extends State<PreferenceScreen> {
  Map<String, dynamic>? _d;
  String? _error;
  bool _advanced = false;
  int _section = 0;
  final _scroll = ScrollController();
  final _anchors = List.generate(4, (_) => GlobalKey());
  static const _tabs = ['Socials', 'Selling', 'Branding', 'Advance Settings'];

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}/preference';
  Map<String, dynamic> get _v => _d!['values'] as Map<String, dynamic>;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_track);
    _load();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await _api.get(_base) as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _d = d;
          _error = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  /// Save one or more fields; the page shows what the server kept.
  Future<bool> _save(Map<String, dynamic> changes) async {
    try {
      final d = await _api.patch(_base, changes) as Map<String, dynamic>;
      if (mounted) setState(() => _d = d);
      return true;
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
      return false;
    }
  }

  Future<void> _photo(String slot, {bool remove = false}) async {
    try {
      Map<String, dynamic> d;
      if (remove) {
        d = await _api.delete('$_base/photos/$slot') as Map<String, dynamic>;
      } else {
        final p = await AddItemScreen.pickPhoto();
        if (p == null) return;
        d = await _api.upload('$_base/photos/$slot', {}, field: 'image', bytes: p.$1, filename: p.$2) as Map<String, dynamic>;
      }
      if (mounted) setState(() => _d = d);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    }
  }

  Future<void> _push(Widget page) async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => page));
    if (mounted) _load();
  }

  void _jump(int i) {
    if (i == 3 && !_advanced) setState(() => _advanced = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final ctx = _anchors[i].currentContext;
      if (ctx != null) Scrollable.ensureVisible(ctx, duration: const Duration(milliseconds: 300));
    });
    setState(() => _section = i);
  }

  // which part is at the top of the list
  void _track() {
    var current = 0;
    for (var i = 0; i < _anchors.length; i++) {
      final box = _anchors[i].currentContext?.findRenderObject() as RenderBox?;
      if (box != null && box.attached && box.localToGlobal(Offset.zero).dy < 220) current = i;
    }
    if (current != _section) setState(() => _section = current);
  }

  void _next() {
    final key = ((_d!['progress'] as Map)['next'] as Map?)?['key'];
    switch (key) {
      case 'google' || 'social':
        _jump(0);
      case 'product':
        _push(AddItemScreen(clientId: widget.clientId));
      case 'logo':
        _photo('logo');
      default:
        _jump(2);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    return Scaffold(
      appBar: navyBar('Preference', subtitle: context.read<Session>().me!.clientName),
      body: d == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : Column(children: [
              _ProgressBar(progress: d['progress'] as Map<String, dynamic>, onTap: _next),
              _TabsRow(tabs: _tabs, active: _section, onTap: _jump),
              Expanded(
                // every section built up front, so the tabs can scroll to any of them
                child: SingleChildScrollView(
                  controller: _scroll,
                  key: const Key('pref-list'),
                  padding: const EdgeInsets.only(bottom: 30),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  _anchor(0, _socials(d)),
                  _anchor(1, _selling(d)),
                  const _Divider('Below details will be used in Posters'),
                  _anchor(2, _branding(d)),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 18, 12, 0),
                    child: OutlinedButton.icon(
                      key: const Key('pref-advanced'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: const Color(0xFFB04DE8),
                        side: const BorderSide(color: Color(0xFFFF7A2F)),
                        minimumSize: const Size.fromHeight(46),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                      onPressed: () => setState(() => _advanced = !_advanced),
                      icon: Icon(_advanced ? Icons.expand_less : Icons.expand_more),
                      label: Text(_advanced ? 'Hide Advance Settings' : 'Advance Settings'),
                    ),
                  ),
                  if (_advanced) _anchor(3, _advance(d)) else SizedBox(key: _anchors[3]),
                  ]),
                ),
              ),
            ]),
    );
  }

  Widget _anchor(int i, Widget child) => KeyedSubtree(key: _anchors[i], child: child);

  // ---------- Socials ----------

  Widget _socials(Map<String, dynamic> d) {
    const names = {'google': 'Google', 'facebook': 'Facebook', 'instagram': 'Instagram'};
    const icons = {'google': (Icons.g_mobiledata, Color(0xFFEA4335)), 'facebook': (Icons.facebook, Color(0xFF1877F2)),
      'instagram': (Icons.camera_alt_outlined, Color(0xFFE1306C))};
    return _Block(children: [
      const Text('Stay active on Social Media', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
      const Text('Connect profiles to automate marketing', style: TextStyle(color: Colors.black54)),
      const SizedBox(height: 12),
      for (final s in (d['socials'] as List).cast<Map<String, dynamic>>())
        Card(
          key: Key('social-${s['platform']}'),
          margin: const EdgeInsets.only(bottom: 10),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                CircleAvatar(backgroundColor: icons[s['platform']]!.$2, child: Icon(icons[s['platform']]!.$1, color: Colors.white)),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(names[s['platform']]!, style: const TextStyle(fontWeight: FontWeight.w700)),
                    if (s['connected'] == true)
                      const Row(children: [
                        Icon(Icons.circle, size: 8, color: green),
                        SizedBox(width: 4),
                        Text('Connected', style: TextStyle(fontSize: 12, color: green)),
                      ])
                    else
                      const Text('Not connected', style: TextStyle(fontSize: 12, color: Colors.black45)),
                  ]),
                ),
                if (s['connected'] != true && s['platform'] != 'google')
                  TextButton(
                    key: Key('connect-${s['platform']}'),
                    style: TextButton.styleFrom(foregroundColor: red),
                    onPressed: () => _push(MetaConnectScreen(clientId: widget.clientId, platform: s['platform'] as String)),
                    child: const Text('Connect  ›'),
                  ),
              ]),
              if ((s['account'] as String).isNotEmpty) ...[
                const Divider(height: 18),
                Text(s['account'] as String, style: const TextStyle(fontSize: 13)),
              ] else if (s['platform'] == 'google' && s['connected'] != true)
                const Padding(
                    padding: EdgeInsets.only(top: 8),
                    child: Text('Ask your account manager to connect your Google Business Profile.', style: TextStyle(fontSize: 12, color: Colors.black54))),
            ]),
          ),
        ),
    ]);
  }

  // ---------- Selling ----------

  Widget _selling(Map<String, dynamic> d) {
    final products = (d['products'] as List).cast<Map<String, dynamic>>();
    return _Block(children: [
      const Text('Top Selling Items', style: TextStyle(fontWeight: FontWeight.w600)),
      const SizedBox(height: 10),
      if (products.isNotEmpty)
        SizedBox(
          height: 92,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: products.length,
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemBuilder: (_, i) => SizedBox(
              width: 76,
              child: Column(children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Container(
                    width: 64,
                    height: 64,
                    color: const Color(0xFFEFF2F6),
                    child: products[i]['image_url'] == null
                        ? const Icon(Icons.shopping_bag_outlined)
                        : Image.network(products[i]['image_url'] as String, fit: BoxFit.cover, errorBuilder: (_, _, _) => const Icon(Icons.image_outlined)),
                  ),
                ),
                const SizedBox(height: 4),
                Text(products[i]['name'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11.5)),
              ]),
            ),
          ),
        ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        key: const Key('pref-add-product'),
        style: OutlinedButton.styleFrom(foregroundColor: const Color(0xFFB04DE8), side: const BorderSide(color: Color(0xFFFF7A2F)),
            minimumSize: const Size.fromHeight(44), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10))),
        onPressed: () => _push(AddItemScreen(clientId: widget.clientId)),
        icon: const Icon(Icons.add_circle_outline),
        label: const Text('Add Product'),
      ),
    ]);
  }

  // ---------- Branding ----------

  Widget _branding(Map<String, dynamic> d) {
    final photos = (d['photos'] as Map).cast<String, dynamic>();
    final labels = (d['labels'] as Map).cast<String, dynamic>();
    final choices = (d['choices'] as Map).cast<String, dynamic>();
    Widget text(String k, IconData icon, {int lines = 1, String? hint}) =>
        _FieldCard(key: Key('field-$k'), label: labels[k] as String, value: _v[k] as String? ?? '', icon: icon, maxLines: lines,
            hint: hint ?? 'Add ${labels[k]}', onSave: (v) => _save({k: v}));
    return Column(children: [
      _Block(children: [
        const Center(child: Text('This is how your poster will look like')),
        const SizedBox(height: 10),
        _PosterPreview(values: _v, logo: (photos['logo'] as Map)['url'] as String?),
      ]),
      text('brand_name', Icons.sell_outlined),
      _PhotoSlot(slot: 'logo', photo: photos['logo'] as Map, onPick: () => _photo('logo'), onRemove: () => _photo('logo', remove: true)),
      text('phone_on_poster', Icons.call_outlined),
      text('address_on_poster', Icons.place_outlined, lines: 2),
      text('additional_info', Icons.info_outline),
      _PhotoSlot(slot: 'founder', photo: photos['founder'] as Map, onPick: () => _photo('founder'), onRemove: () => _photo('founder', remove: true)),
      text('founder_name', Icons.person_outline),
      _Choice(k: 'founder_gender', label: 'Founder Gender', value: _v['founder_gender'] as String, options: (choices['founder_gender'] as List).cast(),
          hint: 'Select Founder Gender', onSave: (v) => _save({'founder_gender': v})),
      _Block(children: [
        SwitchListTile(
          key: const Key('field-founder_in_promos'),
          contentPadding: EdgeInsets.zero,
          value: _v['founder_in_promos'] as bool,
          onChanged: (v) => _save({'founder_in_promos': v}),
          title: const Text('Use Image In Promotional Post'),
          subtitle: const Text('Put the founder photo on promotional creatives'),
        ),
      ]),
      text('different', Icons.workspace_premium_outlined, lines: 3),
      text('why_visit', Icons.star_border, lines: 3),
      text('low_standards', Icons.trending_down, lines: 3),
      text('solutions_low_standards', Icons.check_circle_outline, lines: 3),
      text('solutions_malpractices', Icons.shield_outlined, lines: 3),
      text('common_mistakes', Icons.info_outline, lines: 3),
      text('guidelines', Icons.info_outline, lines: 3),
      text('landmark', Icons.near_me_outlined, lines: 2),
      for (final s in ['interior_1', 'interior_2', 'interior_3', 'interior_4', 'interior_5', 'team_1', 'team_2', 'team_3', 'team_4', 'team_5'])
        _PhotoSlot(slot: s, photo: photos[s] as Map, onPick: () => _photo(s), onRemove: () => _photo(s, remove: true)),
      _Hashtags(values: _v, onSave: _save),
    ]);
  }

  // ---------- Advance Settings ----------

  Widget _advance(Map<String, dynamic> d) {
    final labels = (d['labels'] as Map).cast<String, dynamic>();
    final choices = (d['choices'] as Map).cast<String, dynamic>();
    Widget choice(String k, String label, String hint) => _Choice(
        k: k, label: label, value: _v[k] as String, options: (choices[k] as List).cast(), hint: hint, onSave: (v) => _save({k: v}));
    Widget text(String k, IconData icon, {int lines = 1}) =>
        _FieldCard(key: Key('field-$k'), label: labels[k] as String, value: _v[k] as String? ?? '', icon: icon, maxLines: lines,
            hint: 'Add ${labels[k]}', onSave: (v) => _save({k: v}));
    Widget toggles(String title, String field, Map<String, String> names, Map<String, IconData>? icons) => _Block(children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
          for (final e in names.entries)
            SwitchListTile(
              key: Key('$field-${e.key}'),
              contentPadding: EdgeInsets.zero,
              dense: true,
              secondary: icons == null ? null : Icon(icons[e.key]),
              title: Text(e.value),
              value: ((_v[field] as Map)[e.key] as bool?) ?? true,
              onChanged: (v) => _save({field: {e.key: v}}),
            ),
        ]);
    final maps = d['maps_uri'] as String? ?? '';
    return Column(children: [
      _ColorField(value: _v['brand_color'] as String? ?? '', onSave: (v) => _save({'brand_color': v})),
      text('tagline', Icons.edit_note),
      text('description', Icons.description_outlined, lines: 4),
      text('website', Icons.language),
      text('tone', Icons.record_voice_over_outlined),
      choice('target_gender', 'Target Gender', 'Select Target Gender'),
      choice('target_age', 'Target Age Group', 'Select Age Group'),
      choice('region', 'Region', 'Select Region'),
      choice('model_ethnicity', 'Model Ethnicity', 'Select Model Ethnicity'),
      choice('audience', 'Audience', 'Select Audience'),
      choice('cta', 'CTA', 'Select CTA'),
      toggles('Publish Post on:-', 'publish', const {'gmb': 'Google', 'facebook': 'Facebook', 'instagram': 'Instagram'},
          const {'gmb': Icons.g_mobiledata, 'facebook': Icons.facebook, 'instagram': Icons.camera_alt_outlined}),
      toggles('Religious Posts:-', 'religious',
          const {'hindu': 'Hindu', 'muslim': 'Muslim', 'christian': 'Christian', 'sikh': 'Sikh', 'jain': 'Jain', 'buddhist': 'Buddhist'}, null),
      Center(
        child: TextButton.icon(
          key: const Key('pref-ai-terms'),
          onPressed: () => _push(const LegalScreen(doc: 'ai')),
          icon: const Icon(Icons.info_outline),
          label: const Text('Terms of AI usage'),
        ),
      ),
      if (maps.isNotEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
          child: OutlinedButton.icon(
            key: const Key('pref-google-profile'),
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(46), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
            onPressed: () => launchUrl(Uri.parse(maps), mode: LaunchMode.externalApplication),
            icon: const Icon(Icons.open_in_new),
            label: const Text('Open my Google Profile'),
          ),
        ),
    ]);
  }
}

// ---------- pieces ----------

class _ProgressBar extends StatelessWidget {
  const _ProgressBar({required this.progress, required this.onTap});
  final Map<String, dynamic> progress;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final done = progress['done'] as int, total = progress['total'] as int;
    final next = progress['next'] as Map?;
    return InkWell(
      key: const Key('pref-progress'),
      onTap: next == null ? null : onTap,
      child: Container(
        color: Colors.white,
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        child: Column(children: [
          Row(children: [
            Expanded(child: Text(next == null ? 'Profile complete' : next['label'] as String, style: const TextStyle(fontWeight: FontWeight.w600))),
            Text('$done/$total', key: const Key('pref-progress-count'), style: const TextStyle(color: red, fontWeight: FontWeight.w700)),
          ]),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(value: done / total, minHeight: 8, color: next == null ? green : red, backgroundColor: const Color(0xFFFBDADB)),
          ),
        ]),
      ),
    );
  }
}

class _TabsRow extends StatelessWidget {
  const _TabsRow({required this.tabs, required this.active, required this.onTap});
  final List<String> tabs;
  final int active;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) => Container(
        color: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 6),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final (i, t) in tabs.indexed)
              TextButton(
                key: Key('pref-tab-$i'),
                onPressed: () => onTap(i),
                child: Text(t,
                    style: TextStyle(
                        color: i == active ? _blue : Colors.black54,
                        decoration: i == active ? TextDecoration.underline : null,
                        decorationColor: _blue,
                        fontWeight: i == active ? FontWeight.w600 : FontWeight.w400)),
              ),
          ]),
        ),
      );
}

class _Block extends StatelessWidget {
  const _Block({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 10),
        // a Material, not a coloured box, so switch and radio tiles show their ink
        child: Material(
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: children),
          ),
        ),
      );
}

class _Divider extends StatelessWidget {
  const _Divider(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 18, horizontal: 16),
        child: Row(children: [
          const Expanded(child: Divider(color: red)),
          Flexible(flex: 4, child: Padding(padding: const EdgeInsets.symmetric(horizontal: 10), child: Text(text, textAlign: TextAlign.center))),
          const Expanded(child: Divider(color: red)),
        ]),
      );
}

/// One text field: shown as a value with a pencil; tap to edit, Save sends just this field.
class _FieldCard extends StatefulWidget {
  const _FieldCard({super.key, required this.label, required this.value, required this.icon, required this.onSave, this.maxLines = 1, this.hint = ''});
  final String label, value, hint;
  final IconData icon;
  final int maxLines;
  final Future<bool> Function(String) onSave;

  @override
  State<_FieldCard> createState() => _FieldCardState();
}

class _FieldCardState extends State<_FieldCard> {
  late final _c = TextEditingController(text: widget.value);
  bool _editing = false, _busy = false;

  @override
  void didUpdateWidget(_FieldCard old) {
    super.didUpdateWidget(old);
    if (!_editing && old.value != widget.value) _c.text = widget.value;
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    final ok = await widget.onSave(_c.text.trim());
    if (mounted) setState(() { _busy = false; _editing = !ok; });
  }

  @override
  Widget build(BuildContext context) => _Block(children: [
        Row(children: [
          Expanded(child: Text(widget.label)),
          IconButton(
            key: const Key('edit'),
            visualDensity: VisualDensity.compact,
            tooltip: _editing ? 'Cancel' : 'Edit',
            icon: Icon(_editing ? Icons.close : Icons.edit_outlined, size: 20, color: _editing ? _blue : Colors.black87),
            onPressed: () => setState(() {
              _editing = !_editing;
              if (!_editing) _c.text = widget.value;
            }),
          ),
        ]),
        const SizedBox(height: 4),
        TextField(
          key: const Key('input'),
          controller: _c,
          readOnly: !_editing,
          onTap: _editing ? null : () => setState(() => _editing = true),
          minLines: 1,
          maxLines: widget.maxLines,
          decoration: InputDecoration(
            hintText: widget.hint,
            isDense: true,
            filled: !_editing,
            fillColor: const Color(0xFFF6F8FA),
            suffixIcon: Icon(widget.icon, size: 20),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
          ),
        ),
        if (_editing) ...[
          const SizedBox(height: 10),
          FilledButton(
            key: const Key('save'),
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFF3B82F6), minimumSize: const Size.fromHeight(44)),
            onPressed: _busy ? null : _save,
            child: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : const Text('Save'),
          ),
        ],
      ]);
}

class _Choice extends StatelessWidget {
  const _Choice({required this.k, required this.label, required this.value, required this.options, required this.hint, required this.onSave});
  final String k, label, value, hint;
  final List<String> options;
  final Future<bool> Function(String) onSave;

  @override
  Widget build(BuildContext context) => _Block(children: [
        Text(label),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          key: Key('field-$k'),
          initialValue: options.contains(value) ? value : null,
          hint: Text(hint),
          isExpanded: true,
          decoration: InputDecoration(isDense: true, border: OutlineInputBorder(borderRadius: BorderRadius.circular(10))),
          items: [for (final o in options) DropdownMenuItem(value: o, child: Text(o))],
          onChanged: (v) {
            if (v != null && v != value) onSave(v);
          },
        ),
      ]);
}

class _PhotoSlot extends StatelessWidget {
  const _PhotoSlot({required this.slot, required this.photo, required this.onPick, required this.onRemove});
  final String slot;
  final Map photo;
  final VoidCallback onPick, onRemove;

  @override
  Widget build(BuildContext context) {
    final url = photo['url'] as String?;
    return _Block(children: [
      Text(photo['label'] as String),
      const SizedBox(height: 8),
      InkWell(
        key: Key('photo-$slot'),
        onTap: onPick,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          height: 96,
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(10), border: Border.all(color: Colors.black26)),
          clipBehavior: Clip.antiAlias,
          child: url == null
              ? const Center(child: Row(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.add, color: red, size: 18), SizedBox(width: 4), Text('Add Image')]))
              : Stack(fit: StackFit.expand, children: [
                  Image.network(url, fit: BoxFit.cover, errorBuilder: (_, _, _) => const Icon(Icons.image_outlined)),
                  Positioned(
                    right: 4,
                    top: 4,
                    child: IconButton.filledTonal(
                        key: Key('photo-remove-$slot'), tooltip: 'Remove', visualDensity: VisualDensity.compact, onPressed: onRemove, icon: const Icon(Icons.close, size: 18)),
                  ),
                ]),
        ),
      ),
    ]);
  }
}

/// Custom hashtags as chips (Space, Comma or Add), Save, and how to use them.
class _Hashtags extends StatefulWidget {
  const _Hashtags({required this.values, required this.onSave});
  final Map<String, dynamic> values;
  final Future<bool> Function(Map<String, dynamic>) onSave;

  @override
  State<_Hashtags> createState() => _HashtagsState();
}

class _HashtagsState extends State<_Hashtags> {
  late List<String> _tags = (widget.values['hashtags'] as List).cast<String>().toList();
  final _c = TextEditingController();
  bool _dirty = false;

  @override
  void didUpdateWidget(_Hashtags old) {
    super.didUpdateWidget(old);
    if (!_dirty) _tags = (widget.values['hashtags'] as List).cast<String>().toList();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  void _add(String raw) {
    final parts = raw.split(RegExp(r'[\s,]+')).map((s) => s.replaceAll('#', '').trim()).where((s) => s.isNotEmpty);
    setState(() {
      for (final p in parts) {
        final tag = '#$p';
        if (_tags.length < 10 && !_tags.any((t) => t.toLowerCase() == tag.toLowerCase())) _tags.add(tag);
      }
      _c.clear();
      _dirty = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final mode = widget.values['hashtag_mode'] as String;
    return _Block(children: [
      const Text('Hashtag', style: TextStyle(fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      const Text('Custom Hashtags'),
      const Text.rich(TextSpan(style: TextStyle(fontSize: 12, color: Colors.black54), children: [
        TextSpan(text: 'Type a hashtag, then tap '),
        TextSpan(text: 'Space', style: TextStyle(color: _blue, fontWeight: FontWeight.w600)),
        TextSpan(text: ', '),
        TextSpan(text: 'Comma', style: TextStyle(color: _blue, fontWeight: FontWeight.w600)),
        TextSpan(text: ' or '),
        TextSpan(text: 'Add', style: TextStyle(color: _blue, fontWeight: FontWeight.w600)),
        TextSpan(text: ' to add it. Up to 10 allowed.'),
      ])),
      const SizedBox(height: 8),
      Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(color: const Color(0xFFF6F8FA), borderRadius: BorderRadius.circular(10), border: Border.all(color: Colors.black12)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (_tags.isNotEmpty)
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final t in _tags)
                InputChip(
                  key: Key('tag-$t'),
                  label: Text(t),
                  onDeleted: () => setState(() {
                    _tags.remove(t);
                    _dirty = true;
                  }),
                ),
            ]),
          TextField(
            key: const Key('hashtag-input'),
            controller: _c,
            decoration: InputDecoration(
              hintText: '#mumbai #besthotel #navimumbai',
              border: InputBorder.none,
              suffixIcon: TextButton(key: const Key('hashtag-add'), onPressed: () => _add(_c.text), child: const Text('+ Add')),
            ),
            onChanged: (v) {
              if (v.endsWith(' ') || v.endsWith(',')) _add(v);
            },
            onSubmitted: _add,
          ),
        ]),
      ),
      Row(children: [
        Text('${_tags.length}/10 hashtags added', key: const Key('hashtag-count'), style: const TextStyle(fontSize: 12, color: Colors.black54)),
        const Spacer(),
        FilledButton.icon(
          key: const Key('hashtag-save'),
          style: FilledButton.styleFrom(backgroundColor: const Color(0xFF3B82F6), visualDensity: VisualDensity.compact),
          onPressed: _dirty
              ? () async {
                  if (await widget.onSave({'hashtags': _tags}) && mounted) setState(() => _dirty = false);
                }
              : null,
          icon: const Icon(Icons.save_outlined, size: 16),
          label: const Text('SAVE'),
        ),
      ]),
      const SizedBox(height: 12),
      const Text('How should we use your hashtags?'),
      RadioGroup<String>(
        groupValue: mode,
        onChanged: (v) {
          if (v != null) widget.onSave({'hashtag_mode': v});
        },
        child: const Column(children: [
          RadioListTile<String>(
            key: Key('hashtag-exact'),
            contentPadding: EdgeInsets.zero,
            value: 'exact',
            title: Text('Use Exact Hashtag'),
            subtitle: Text('Post only the hashtags you entered above — nothing else is added.'),
          ),
          RadioListTile<String>(
            key: Key('hashtag-additional'),
            contentPadding: EdgeInsets.zero,
            value: 'additional',
            title: Text('Use Additional Tags'),
            subtitle: Text('Add your hashtags on top of auto-generated ones for wider reach.'),
          ),
        ]),
      ),
    ]);
  }
}

class _ColorField extends StatelessWidget {
  const _ColorField({required this.value, required this.onSave});
  final String value;
  final Future<bool> Function(String) onSave;

  static const _palette = ['#0E1A3A', '#0F7A45', '#1F63C6', '#6C2BD9', '#E8457C', '#DC2626', '#FF7A2F', '#B45309', '#111827'];

  Color _c(String hex) => Color(int.parse('FF${hex.substring(1)}', radix: 16));

  @override
  Widget build(BuildContext context) => _Block(children: [
        const Text('Brand Color'),
        const SizedBox(height: 10),
        Wrap(spacing: 10, runSpacing: 10, children: [
          for (final hex in _palette)
            InkWell(
              key: Key('color-$hex'),
              customBorder: const CircleBorder(),
              onTap: () => onSave(hex),
              child: Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: _c(hex),
                  shape: BoxShape.circle,
                  border: Border.all(color: value.toUpperCase() == hex ? Colors.black : Colors.white, width: 3),
                  boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 2)],
                ),
                child: value.toUpperCase() == hex ? const Icon(Icons.check, color: Colors.white, size: 18) : null,
              ),
            ),
          if (value.isNotEmpty) TextButton(key: const Key('color-clear'), onPressed: () => onSave(''), child: const Text('Clear')),
        ]),
        const SizedBox(height: 6),
        Text(value.isEmpty ? 'Posters use the template colours' : 'Posters use $value', style: const TextStyle(fontSize: 12, color: Colors.black54)),
      ]);
}

/// A sample poster with the business's footer, updated as fields are saved.
class _PosterPreview extends StatelessWidget {
  const _PosterPreview({required this.values, required this.logo});
  final Map<String, dynamic> values;
  final String? logo;

  @override
  Widget build(BuildContext context) {
    final colour = (values['brand_color'] as String? ?? '').isEmpty ? null : Color(int.parse('FF${(values['brand_color'] as String).substring(1)}', radix: 16));
    return AspectRatio(
      key: const Key('poster-preview'),
      aspectRatio: 1,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          gradient: RadialGradient(colors: [const Color(0xFF3A2A12), colour ?? Colors.black], radius: 1.1),
        ),
        padding: const EdgeInsets.all(14),
        child: Stack(children: [
          Align(
            alignment: Alignment.topRight,
            child: CircleAvatar(
              radius: 24,
              backgroundColor: Colors.white,
              backgroundImage: logo == null ? null : NetworkImage(logo!),
              onBackgroundImageError: logo == null ? null : (_, _) {},
              child: logo == null ? const Text('Your\nLogo', textAlign: TextAlign.center, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: Colors.black)) : null,
            ),
          ),
          const Align(
            alignment: Alignment(0, -0.35),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('Happy', style: TextStyle(color: Color(0xFFF5D27A), fontSize: 30, fontStyle: FontStyle.italic)),
              Text('NEW YEAR', style: TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w900, letterSpacing: 1)),
              Text('2027', style: TextStyle(color: Color(0xFFF5D27A), fontSize: 44, fontWeight: FontWeight.w900)),
              Text('Wishing you a year full of new opportunities', style: TextStyle(color: Colors.white70, fontSize: 10)),
            ]),
          ),
          Align(
            alignment: Alignment.bottomCenter,
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(values['brand_name'] as String? ?? '', key: const Key('poster-name'), textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                const Icon(Icons.place, color: Colors.white, size: 14),
                const SizedBox(width: 4),
                Expanded(child: Text(values['address_on_poster'] as String? ?? '', maxLines: 3, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white, fontSize: 10.5))),
                const SizedBox(width: 8),
                const Icon(Icons.call, color: Colors.white, size: 14),
                const SizedBox(width: 4),
                Text(values['phone_on_poster'] as String? ?? '', style: const TextStyle(color: Colors.white, fontSize: 10.5)),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }
}
