import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';
import 'ai_post/shared.dart';
import 'keyword_planner_screen.dart';
import 'my_plan_screen.dart';
import 'phone_login_screen.dart' show ProfileCard, ProfileGroupHeader, ProfileTrustCard;

const _appVersion = '1.0.0';

/// Settings (business owners): business card, My Plan, Tools (Preference, Configure QR Standee, My QRs, Keyword
/// Planner), Account (Change Profile, Logout, Delete Account), Privacy and Legal.
class OwnerSettingsScreen extends StatefulWidget {
  const OwnerSettingsScreen({super.key, required this.clientId});
  final int clientId;

  /// Opens a link outside the app (downloads); replaceable in tests.
  static Future<bool> Function(Uri url) openUrl = (url) => launchUrl(url, mode: LaunchMode.externalApplication);

  @override
  State<OwnerSettingsScreen> createState() => _OwnerSettingsScreenState();
}

class _OwnerSettingsScreenState extends State<OwnerSettingsScreen> {
  Map<String, dynamic>? _d;
  String? _error;

  Session get _session => context.read<Session>();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await _session.api.get('/api/clients/${widget.clientId}/settings') as Map<String, dynamic>;
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

  Future<void> _open(Widget page) async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => page));
    if (mounted) _load();
  }

  Future<void> _analytics(bool on) async {
    try {
      await _session.api.put('/api/auth/prefs', {'analytics': on});
      await _session.refreshMe();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Log out?'),
        content: const Text('You can sign in again with your mobile number.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          FilledButton(key: const Key('logout-confirm'), onPressed: () => Navigator.pop(d, true), child: const Text('Logout')),
        ],
      ),
    );
    if (ok == true && mounted) {
      Navigator.of(context).popUntil((r) => r.isFirst);
      await _session.logout();
    }
  }

  Future<void> _delete() async {
    final text = await showDialog<String>(context: context, builder: (_) => const _DeleteDialog());
    if (text == null || !mounted) return;
    try {
      await _session.api.post('/api/auth/delete-account', {'confirm': text});
      if (!mounted) return;
      Navigator.of(context).popUntil((r) => r.isFirst);
      await _session.logout();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    final me = context.watch<Session>().me;
    if (me == null) return const SizedBox.shrink(); // signed out (Logout / Delete Account) while this page closes
    return Scaffold(
      appBar: navyBar('Settings', subtitle: me.clientName),
      body: d == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : ListView(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
              children: [
                _BusinessCard(client: d['client'] as Map<String, dynamic>),
                const SizedBox(height: 10),
                _PlanCard(
                  plan: d['plan'] as Map<String, dynamic>,
                  onManage: () => _open(MyPlanScreen(clientId: widget.clientId)),
                ),
                const _Heading('TOOLS'),
                _Group([
                  _Row(
                    key: const Key('set-preference'),
                    icon: Icons.settings_outlined,
                    tint: const Color(0xFF6C2BD9),
                    title: 'Preference',
                    subtitle: 'Brand details & Google connection',
                    onTap: () => _open(PreferenceScreen(clientId: widget.clientId)),
                  ),
                  _Row(
                    key: const Key('set-standee'),
                    icon: Icons.qr_code_scanner,
                    tint: const Color(0xFF1F63C6),
                    title: 'Configure QR Standee',
                    onTap: () => _open(ConfigureStandeeScreen(clientId: widget.clientId)),
                  ),
                  _Row(
                    key: const Key('set-qrs'),
                    icon: Icons.qr_code_2,
                    tint: const Color(0xFFB04DE8),
                    title: 'My QRs',
                    onTap: () => _open(MyQrsScreen(clientId: widget.clientId)),
                  ),
                  _Row(
                    key: const Key('set-planner'),
                    icon: Icons.key_outlined,
                    tint: const Color(0xFFE08A1E),
                    title: 'Keyword Planner',
                    badge: 'Beta',
                    onTap: () => _open(KeywordPlannerScreen(clientId: widget.clientId)),
                  ),
                ]),
                const _Heading('ACCOUNT'),
                _Group([
                  _Row(
                    key: const Key('set-profile'),
                    icon: Icons.person_outline,
                    tint: green,
                    title: 'Change Profile',
                    subtitle: 'Switch to a different business',
                    onTap: () => _open(const ChangeProfileScreen()),
                  ),
                  _Row(key: const Key('set-logout'), icon: Icons.logout, tint: red, title: 'Logout', danger: true, onTap: _logout),
                  _Row(
                    key: const Key('set-delete'),
                    icon: Icons.delete_outline,
                    tint: red,
                    title: 'Delete Account',
                    danger: true,
                    subtitle: 'Permanently delete your account and data',
                    onTap: _delete,
                  ),
                ]),
                const _Heading('PRIVACY'),
                _Group([
                  SwitchListTile(
                    key: const Key('set-analytics'),
                    value: me.analytics,
                    onChanged: _analytics,
                    secondary: const _Icon(Icons.show_chart, Color(0xFF1F63C6)),
                    title: const Text('Analytics & Personalisation'),
                    subtitle: const Text('Share anonymous app usage to help us improve. Off unless you turn it on.'),
                  ),
                ]),
                const _Heading('LEGAL'),
                _Group([
                  _Row(
                    key: const Key('set-privacy'),
                    icon: Icons.lock_outline,
                    tint: Colors.blueGrey,
                    title: 'Privacy Policy',
                    onTap: () => _open(const LegalScreen(doc: 'privacy')),
                  ),
                  _Row(
                    key: const Key('set-terms'),
                    icon: Icons.description_outlined,
                    tint: Colors.blueGrey,
                    title: 'Terms of Service',
                    onTap: () => _open(const LegalScreen(doc: 'terms')),
                  ),
                  _Row(
                    key: const Key('set-refund'),
                    icon: Icons.currency_rupee,
                    tint: const Color(0xFFE08A1E),
                    title: 'Refund Request',
                    onTap: () => _open(RefundScreen(clientId: widget.clientId)),
                  ),
                ]),
                const SizedBox(height: 16),
                Center(
                  child: Text(
                    '${d['company']} · ${(d['client'] as Map)['code']} · v$_appVersion',
                    key: const Key('set-footer'),
                    style: const TextStyle(color: Colors.black38, fontSize: 12),
                  ),
                ),
              ],
            ),
    );
  }
}

/// Type DELETE to confirm; owns its text field (it outlives the dialog's closing animation).
class _DeleteDialog extends StatefulWidget {
  const _DeleteDialog();

  @override
  State<_DeleteDialog> createState() => _DeleteDialogState();
}

class _DeleteDialogState extends State<_DeleteDialog> {
  final _c = TextEditingController();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    icon: const Icon(Icons.delete_forever, color: red, size: 36),
    title: const Text('Delete your account?'),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Your login stops working right away. Your business’s data — posts, replies, photos and reports — is deleted '
          'within 30 days. This can’t be undone.',
        ),
        const SizedBox(height: 12),
        TextField(
          key: const Key('delete-confirm-text'),
          controller: _c,
          onChanged: (_) => setState(() {}),
          decoration: const InputDecoration(labelText: 'Type DELETE to confirm', border: OutlineInputBorder()),
        ),
      ],
    ),
    actions: [
      TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
      FilledButton(
        key: const Key('delete-confirm'),
        style: FilledButton.styleFrom(backgroundColor: red),
        onPressed: _c.text.trim().toUpperCase() == 'DELETE' ? () => Navigator.pop(context, _c.text) : null,
        child: const Text('Delete Account'),
      ),
    ],
  );
}

class _BusinessCard extends StatelessWidget {
  const _BusinessCard({required this.client});
  final Map<String, dynamic> client;

  @override
  Widget build(BuildContext context) {
    final name = client['company_name'] as String;
    return Card(
      margin: EdgeInsets.zero,
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        leading: CircleAvatar(
          radius: 24,
          backgroundColor: navy,
          child: Text(name[0].toUpperCase(), style: const TextStyle(color: Colors.white, fontSize: 20)),
        ),
        title: Text(name, style: const TextStyle(fontWeight: FontWeight.w700)),
        subtitle: Text([client['phone'], client['code']].where((s) => '${s ?? ''}'.isNotEmpty).join(' · ')),
      ),
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.plan, required this.onManage});
  final Map<String, dynamic> plan;
  final VoidCallback onManage;

  @override
  Widget build(BuildContext context) {
    final active = plan['state'] == 'active';
    final until = plan['valid_until'] as String?;
    return Container(
      key: const Key('set-plan'),
      padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE8457C), width: 1.5),
      ),
      child: Row(
        children: [
          const Icon(Icons.diamond_outlined, color: Color(0xFF1F9BE0), size: 30),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('My Plan', style: TextStyle(fontWeight: FontWeight.w700)),
                Text(
                  active
                      ? '${(plan['plan'] as Map?)?['name'] ?? 'Pro'} · till ${DateFormat('d MMM yyyy').format(DateTime.parse(until!))}'
                      : 'Upgrade to Pro',
                  style: const TextStyle(fontSize: 12.5, color: Colors.black54),
                ),
              ],
            ),
          ),
          FilledButton(
            key: const Key('plan-manage'),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFFE8457C),
              shape: const StadiumBorder(),
              visualDensity: VisualDensity.compact,
            ),
            onPressed: onManage,
            child: const Text('Manage'),
          ),
        ],
      ),
    );
  }
}

class _Heading extends StatelessWidget {
  const _Heading(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(4, 18, 4, 8),
    child: Text(
      text,
      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: .6, color: Colors.black54),
    ),
  );
}

class _Group extends StatelessWidget {
  const _Group(this.children);
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    clipBehavior: Clip.antiAlias,
    child: Column(
      children: [
        for (final (i, c) in children.indexed) ...[if (i > 0) const Divider(height: 1, indent: 60), c],
      ],
    ),
  );
}

class _Icon extends StatelessWidget {
  const _Icon(this.icon, this.tint);
  final IconData icon;
  final Color tint;

  @override
  Widget build(BuildContext context) => Container(
    width: 36,
    height: 36,
    decoration: BoxDecoration(color: tint.withValues(alpha: .1), borderRadius: BorderRadius.circular(10)),
    child: Icon(icon, size: 20, color: tint),
  );
}

class _Row extends StatelessWidget {
  const _Row({
    super.key,
    required this.icon,
    required this.tint,
    required this.title,
    this.subtitle,
    this.badge,
    this.danger = false,
    required this.onTap,
  });
  final IconData icon;
  final Color tint;
  final String title;
  final String? subtitle, badge;
  final bool danger;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => ListTile(
    onTap: onTap,
    leading: _Icon(icon, tint),
    title: Text(
      title,
      style: TextStyle(color: danger ? red : null, fontWeight: FontWeight.w500),
    ),
    subtitle: subtitle == null ? null : Text(subtitle!, style: const TextStyle(fontSize: 12)),
    trailing: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (badge != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(99),
              border: Border.all(color: Colors.black26),
            ),
            child: Text(badge!, style: const TextStyle(fontSize: 11, color: Colors.black54)),
          ),
        Icon(Icons.chevron_right, color: danger ? red : Colors.black38),
      ],
    ),
  );
}

// ---------- Preference ----------

class PreferenceScreen extends StatefulWidget {
  const PreferenceScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<PreferenceScreen> createState() => _PreferenceScreenState();
}

class _PreferenceScreenState extends State<PreferenceScreen> {
  Map<String, dynamic>? _d;
  final _website = TextEditingController(), _phone = TextEditingController(), _tone = TextEditingController(), _cta = TextEditingController();
  final _phrases = TextEditingController(), _avoid = TextEditingController();
  bool _busy = false;

  String get _url => '/api/clients/${widget.clientId}/preference';

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get(_url).then((d) {
      if (!mounted) return;
      final m = d as Map<String, dynamic>;
      _website.text = m['website'] as String? ?? '';
      _phone.text = m['phone'] as String? ?? '';
      _tone.text = m['tone'] as String? ?? '';
      _cta.text = m['cta_style'] as String? ?? '';
      _phrases.text = (m['preferred_phrases'] as List).join(', ');
      _avoid.text = (m['prohibited_claims'] as List).join(', ');
      setState(() => _d = m);
    });
  }

  @override
  void dispose() {
    for (final c in [_website, _phone, _tone, _cta, _phrases, _avoid]) {
      c.dispose();
    }
    super.dispose();
  }

  List<String> _list(TextEditingController c) => c.text.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.put(_url, {
        'website': _website.text,
        'phone': _phone.text,
        'tone': _tone.text,
        'cta_style': _cta.text,
        'preferred_phrases': _list(_phrases),
        'prohibited_claims': _list(_avoid),
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Preferences saved')));
      Navigator.pop(context);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    InputDecoration dec(String label, [String? hint]) => InputDecoration(labelText: label, hintText: hint, border: const OutlineInputBorder());
    return Scaffold(
      appBar: navyBar('Preference', subtitle: context.read<Session>().me!.clientName),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(14),
              children: [
                Card(
                  child: ListTile(
                    leading: Icon(Icons.storefront, color: (d['google'] as Map)['connected'] == true ? green : Colors.orange),
                    title: Text(d['company_name'] as String, style: const TextStyle(fontWeight: FontWeight.w700)),
                    subtitle: Text(
                      (d['google'] as Map)['connected'] == true
                          ? 'Google Business Profile connected${((d['google'] as Map)['address'] as String).isEmpty ? '' : ' · ${(d['google'] as Map)['address']}'}'
                          : 'Google Business Profile not connected — ask your account manager',
                    ),
                  ),
                ),
                const SizedBox(height: 14),
                const Text('Business details', style: TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                TextField(
                  key: const Key('pref-website'),
                  controller: _website,
                  keyboardType: TextInputType.url,
                  decoration: dec('Website', 'yourbusiness.in'),
                ),
                const SizedBox(height: 10),
                TextField(key: const Key('pref-phone'), controller: _phone, keyboardType: TextInputType.phone, decoration: dec('Business phone')),
                const SizedBox(height: 18),
                const Text('Brand voice', style: TextStyle(fontWeight: FontWeight.w700)),
                const Text('Used for AI replies, posts and captions', style: TextStyle(fontSize: 12, color: Colors.black54)),
                const SizedBox(height: 10),
                TextField(key: const Key('pref-tone'), controller: _tone, decoration: dec('Tone', 'Warm, friendly and professional')),
                const SizedBox(height: 10),
                TextField(key: const Key('pref-cta'), controller: _cta, decoration: dec('Call to action', 'Book a visit')),
                const SizedBox(height: 10),
                TextField(controller: _phrases, decoration: dec('Phrases to use', 'Comma separated')),
                const SizedBox(height: 10),
                TextField(controller: _avoid, decoration: dec('Never claim', 'e.g. painless, guaranteed results')),
              ],
            ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 10),
          child: GradientButton(key: const Key('pref-save'), label: 'Save', busy: _busy, onPressed: d == null ? null : _save),
        ),
      ),
    );
  }
}

// ---------- My QRs ----------

class MyQrsScreen extends StatefulWidget {
  const MyQrsScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<MyQrsScreen> createState() => _MyQrsScreenState();
}

class _MyQrsScreenState extends State<MyQrsScreen> {
  Map<String, dynamic>? _d;
  bool _busy = false;

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}/qrs';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await _api.get(_base) as Map<String, dynamic>;
    if (mounted) setState(() => _d = d);
  }

  Future<void> _generate() async {
    setState(() => _busy = true);
    try {
      final q = await _api.post(_base, {}) as Map<String, dynamic>;
      await _load();
      if (!mounted) return;
      setState(() => _busy = false);
      await _show(q);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _download(Map<String, dynamic> q) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final link = await _api.post('$_base/${q['id']}/link') as Map<String, dynamic>;
      final ok = await OwnerSettingsScreen.openUrl(Uri.parse(link['url'] as String));
      messenger.hideCurrentSnackBar();
      messenger.showSnackBar(
        SnackBar(
          content: Text(ok ? 'QR standee downloaded — ${link['filename']}' : 'Couldn’t open the download'),
          backgroundColor: ok ? green : Colors.red.shade700,
        ),
      );
    } on ApiException catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _show(Map<String, dynamic> q) => showDialog<void>(
    context: context,
    builder: (d) => AlertDialog(
      title: Column(
        children: [
          const Text('QR Code'),
          Text(q['code'] as String, style: const TextStyle(fontSize: 12, color: Colors.black45)),
        ],
      ),
      content: SizedBox(
        width: 240,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                border: Border.all(color: const Color(0xFFE3E8EF)),
                borderRadius: BorderRadius.circular(12),
              ),
              child: QrImageView(key: const Key('qr-image'), data: q['url'] as String, size: 200),
            ),
            const SizedBox(height: 8),
            const Text(
              'Customers scan it to open your Google review form',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(d), child: const Text('Close')),
        FilledButton.icon(
          key: const Key('qr-download'),
          onPressed: () {
            Navigator.pop(d);
            _download(q);
          },
          icon: const Icon(Icons.download),
          label: const Text('Download'),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final d = _d;
    final items = ((d?['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final f = DateFormat('dd/MM/yyyy HH:mm');
    return Scaffold(
      appBar: navyBar('My QRs', subtitle: context.read<Session>().me!.clientName),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(12),
              children: [
                GradientButton(key: const Key('qr-generate'), label: 'Generate QR', busy: _busy, onPressed: _generate),
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 16, 4, 8),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'YOUR QRS',
                          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Colors.black54),
                        ),
                      ),
                      Text(
                        '${d['used']} / ${d['limit']}',
                        key: const Key('qr-count'),
                        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                      ),
                    ],
                  ),
                ),
                if (items.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(30),
                    child: Text(
                      'No QR codes yet. Generate one to print for your counter, table or standee — every scan is counted.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.black54),
                    ),
                  ),
                for (final q in items)
                  Card(
                    key: Key('qr-${q['id']}'),
                    child: InkWell(
                      onTap: () => _show(q),
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    '${q['code']}${q['kind'] == 'standee' ? '  ·  Standee' : ''}${(q['label'] as String).isEmpty ? '' : '  ·  ${q['label']}'}',
                                    style: const TextStyle(fontWeight: FontWeight.w600),
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                  decoration: BoxDecoration(color: green.withValues(alpha: .12), borderRadius: BorderRadius.circular(99)),
                                  child: Text(
                                    '${q['scans']} SCAN${q['scans'] == 1 ? '' : 'S'}',
                                    style: const TextStyle(color: green, fontSize: 10.5, fontWeight: FontWeight.w700),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 6),
                            Text('Created: ${f.format(DateTime.parse(q['created_at'] as String).toLocal())}', style: const TextStyle(fontSize: 12.5)),
                            Text(
                              'Last scan: ${q['last_scan_at'] == null ? '—' : f.format(DateTime.parse(q['last_scan_at'] as String).toLocal())}',
                              style: const TextStyle(fontSize: 12.5),
                            ),
                            Align(
                              alignment: Alignment.centerRight,
                              child: FilledButton(
                                key: Key('qr-download-${q['id']}'),
                                style: FilledButton.styleFrom(
                                  backgroundColor: const Color(0xFFE8457C),
                                  shape: const StadiumBorder(),
                                  visualDensity: VisualDensity.compact,
                                ),
                                onPressed: () => _download(q),
                                child: const Text('DOWNLOAD'),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}

// ---------- Configure QR Standee ----------

class ConfigureStandeeScreen extends StatefulWidget {
  const ConfigureStandeeScreen({super.key, required this.clientId});
  final int clientId;

  /// The camera view; replaceable in tests (no camera there).
  static Widget Function(void Function(String code) onCode) scanner = (onCode) => MobileScanner(
    onDetect: (capture) {
      final v = capture.barcodes.firstOrNull?.rawValue;
      if (v != null && v.isNotEmpty) onCode(v);
    },
  );

  @override
  State<ConfigureStandeeScreen> createState() => _ConfigureStandeeScreenState();
}

class _ConfigureStandeeScreenState extends State<ConfigureStandeeScreen> {
  final _code = TextEditingController();
  bool _busy = false, _claimed = false;

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _claim(String code) async {
    if (_busy || _claimed || code.trim().isEmpty) return; // the camera keeps reporting the same code
    setState(() => _busy = true);
    try {
      final q = await context.read<Session>().api.post('/api/clients/${widget.clientId}/qrs/claim', {'code': code.trim()}) as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _busy = false;
        _claimed = true;
      });
      await showDialog<void>(
        context: context,
        builder: (d) => AlertDialog(
          icon: const Icon(Icons.verified, color: green, size: 44),
          title: const Text('Standee set up'),
          content: Text('Standee ${q['code']} now opens your Google review form. Find it in My QRs with its scan count.'),
          actions: [FilledButton(key: const Key('standee-done'), onPressed: () => Navigator.pop(d), child: const Text('Done'))],
        ),
      );
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: Colors.black,
    appBar: AppBar(backgroundColor: Colors.black, foregroundColor: Colors.white, title: const Text('Configure QR'), centerTitle: true),
    body: Column(
      children: [
        Expanded(
          child: Stack(
            alignment: Alignment.center,
            children: [
              Positioned.fill(child: ConfigureStandeeScreen.scanner(_claim)),
              IgnorePointer(
                child: Container(
                  width: 240,
                  height: 240,
                  decoration: BoxDecoration(
                    border: Border.all(color: const Color(0xFF4169E1), width: 3),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  alignment: Alignment.topCenter,
                  child: Container(
                    margin: const EdgeInsets.only(top: 10),
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(color: Colors.black54, borderRadius: BorderRadius.circular(99)),
                    child: const Text('Align QR code within the frame', style: TextStyle(color: Colors.white, fontSize: 12)),
                  ),
                ),
              ),
              if (_busy) const CircularProgressIndicator(),
            ],
          ),
        ),
        Container(
          color: Colors.white,
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
          child: SafeArea(
            top: false,
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('standee-code'),
                    controller: _code,
                    decoration: const InputDecoration(
                      isDense: true,
                      labelText: 'Or type the code printed under the QR',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(key: const Key('standee-claim'), onPressed: _busy ? null : () => _claim(_code.text), child: const Text('Set up')),
              ],
            ),
          ),
        ),
      ],
    ),
  );
}

// ---------- Change Profile ----------

class ChangeProfileScreen extends StatefulWidget {
  const ChangeProfileScreen({super.key});

  @override
  State<ChangeProfileScreen> createState() => _ChangeProfileScreenState();
}

class _ChangeProfileScreenState extends State<ChangeProfileScreen> {
  List<LoginProfile>? _profiles;
  int? _current;

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/auth/profiles').then((d) {
      final m = d as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          _profiles = [for (final p in m['profiles'] as List) LoginProfile.fromJson(p as Map<String, dynamic>)];
          _current = m['current'] as int;
        });
      }
    });
  }

  Future<void> _switch(LoginProfile p) async {
    if (p.userId == _current) return Navigator.pop(context);
    final session = context.read<Session>();
    final nav = Navigator.of(context);
    try {
      await session.switchProfile(p.userId);
      nav.popUntil((r) => r.isFirst);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final ps = _profiles;
    final groups = <String, List<LoginProfile>>{};
    for (final p in ps ?? const <LoginProfile>[]) {
      groups.putIfAbsent(p.group, () => []).add(p);
    }
    return Scaffold(
      appBar: navyBar('Select profile', subtitle: context.read<Session>().me!.clientName),
      body: ps == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(12),
              children: [
                for (final g in groups.entries) ...[
                  ProfileGroupHeader(label: g.key, profiles: g.value),
                  for (final p in g.value)
                    Stack(
                      children: [
                        ProfileCard(key: Key('profile-${p.userId}'), profile: p, onTap: () => _switch(p)),
                        if (p.userId == _current)
                          const Positioned(
                            right: 40,
                            top: 8,
                            child: Chip(
                              label: Text('Current', style: TextStyle(fontSize: 11)),
                              visualDensity: VisualDensity.compact,
                            ),
                          ),
                      ],
                    ),
                  const SizedBox(height: 8),
                ],
                const SizedBox(height: 8),
                const ProfileTrustCard(),
              ],
            ),
    );
  }
}

// ---------- Legal ----------

class LegalScreen extends StatelessWidget {
  const LegalScreen({super.key, required this.doc});
  final String doc;

  @override
  Widget build(BuildContext context) {
    final api = context.read<Session>().api;
    return Scaffold(
      appBar: navyBar(doc == 'privacy' ? 'Privacy' : 'Terms of Service', subtitle: 'Your payment is 100% safe & encrypted'),
      body: FutureBuilder(
        future: api.get('/api/legal/$doc'),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text('${snap.error}'));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final d = snap.data as Map<String, dynamic>;
          return ListView(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 30),
            children: [
              Center(
                child: Text(
                  d['title'] as String,
                  key: const Key('legal-title'),
                  style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                'Last updated: ${DateFormat('MMMM d, yyyy').format(DateTime.parse(d['updated'] as String))}',
                style: const TextStyle(fontSize: 12.5),
              ),
              const SizedBox(height: 12),
              Text(d['intro'] as String, style: const TextStyle(height: 1.5)),
              if ((d['notice'] as String).isNotEmpty)
                Container(
                  margin: const EdgeInsets.only(top: 14),
                  padding: const EdgeInsets.all(12),
                  decoration: const BoxDecoration(
                    color: Color(0xFFFFF8E1),
                    border: Border(left: BorderSide(color: Color(0xFFFFB300), width: 3)),
                  ),
                  child: Text(d['notice'] as String, style: const TextStyle(color: Color(0xFFB45309), fontSize: 12.5)),
                ),
              for (final s in (d['sections'] as List).cast<Map<String, dynamic>>()) ...[
                const SizedBox(height: 18),
                Text(s['heading'] as String, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                for (final p in (s['paragraphs'] as List).cast<String>())
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(p, style: const TextStyle(height: 1.5)),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

// ---------- Refund Request ----------

class RefundScreen extends StatefulWidget {
  const RefundScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<RefundScreen> createState() => _RefundScreenState();
}

class _RefundScreenState extends State<RefundScreen> {
  Map<String, dynamic>? _d;
  String? _open;

  String get _base => '/api/clients/${widget.clientId}/refunds';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<Session>().api.get(_base) as Map<String, dynamic>;
    if (mounted) setState(() => _d = d);
  }

  Future<void> _request(Map<String, dynamic> plan) async {
    final pays = (_d!['payments'] as List).cast<Map<String, dynamic>>().where((p) => p['plan'] == plan['key']).toList();
    final ok = pays.where((p) => p['refundable'] == true).toList();
    if (ok.isEmpty) {
      final why = pays.isEmpty ? 'You haven’t bought this plan.' : (pays.first['why_not'] as String);
      await showDialog<void>(
        context: context,
        builder: (d) => AlertDialog(
          title: const Text('Refund not available'),
          content: Text(why),
          actions: [TextButton(onPressed: () => Navigator.pop(d), child: const Text('OK'))],
        ),
      );
      return;
    }
    final pay = ok.first;
    final text = await showDialog<String>(
      context: context,
      builder: (_) => _RefundDialog(payment: pay),
    );
    if (text == null || !mounted) return;
    try {
      await context.read<Session>().api.post(_base, {'payment_id': pay['id'], 'reason': text});
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Refund requested — we’ll email you within 2 working days'), backgroundColor: green));
      _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    return Scaffold(
      appBar: navyBar('Refund', subtitle: 'Your payment is 100% safe & encrypted'),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(12),
              children: [
                if ((d['requests'] as List).isNotEmpty)
                  Card(
                    color: const Color(0xFFFFF8E1),
                    child: ListTile(
                      key: const Key('refund-open'),
                      leading: const Icon(Icons.hourglass_top, color: Color(0xFFE08A1E)),
                      title: Text('${(d['requests'] as List).length} refund request${(d['requests'] as List).length == 1 ? '' : 's'}'),
                      subtitle: Text('Latest: ${((d['requests'] as List).first as Map)['status']}'),
                    ),
                  ),
                Card(
                  child: Column(
                    children: [
                      for (final p in ((d['policy'] as Map)['plans'] as List).cast<Map<String, dynamic>>())
                        ExpansionTile(
                          key: Key('refund-plan-${p['key']}'),
                          initiallyExpanded: _open == p['key'],
                          onExpansionChanged: (v) => setState(() => _open = v ? p['key'] as String : null),
                          title: Text(
                            p['title'] as String,
                            style: const TextStyle(color: Color(0xFF1F63C6), fontSize: 14, fontWeight: FontWeight.w600),
                          ),
                          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                          expandedCrossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _kv('Duration', p['duration'] as String),
                            _kv('Type', p['type'] as String),
                            _kv('Support', p['support'] as String),
                            const SizedBox(height: 6),
                            const Text('Refund Policy:', style: TextStyle(fontWeight: FontWeight.w700)),
                            for (final line in (p['policy'] as List).cast<String>()) _bullet(line),
                            const SizedBox(height: 8),
                            const Text('Services Included', style: TextStyle(fontWeight: FontWeight.w700)),
                            for (final line in (p['included'] as List).cast<String>()) _bullet(line),
                            if (p['refundable'] == true) ...[
                              const SizedBox(height: 14),
                              SizedBox(
                                width: double.infinity,
                                child: FilledButton(
                                  key: Key('refund-request-${p['key']}'),
                                  style: FilledButton.styleFrom(backgroundColor: const Color(0xFFDC2626), minimumSize: const Size.fromHeight(46)),
                                  onPressed: () => _request(p),
                                  child: const Text('Request Refund'),
                                ),
                              ),
                            ],
                          ],
                        ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }

  Widget _kv(String k, String v) => Padding(
    padding: const EdgeInsets.only(top: 6),
    child: Text.rich(
      TextSpan(
        children: [
          TextSpan(
            text: '$k: ',
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
          TextSpan(text: v),
        ],
      ),
    ),
  );

  Widget _bullet(String s) => Padding(
    padding: const EdgeInsets.only(top: 4, left: 4),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('•  '),
        Expanded(child: Text(s, style: const TextStyle(height: 1.4))),
      ],
    ),
  );
}

class _RefundDialog extends StatefulWidget {
  const _RefundDialog({required this.payment});
  final Map<String, dynamic> payment;

  @override
  State<_RefundDialog> createState() => _RefundDialogState();
}

class _RefundDialogState extends State<_RefundDialog> {
  final _reason = TextEditingController();

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pay = widget.payment;
    return AlertDialog(
      title: const Text('Request a refund'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${pay['plan_name']} · ${rupees(pay['amount'] as num)} · paid ${DateFormat('d MMM yyyy').format(DateTime.parse(pay['paid_at'] as String).toLocal())}',
          ),
          const SizedBox(height: 10),
          TextField(
            key: const Key('refund-reason'),
            controller: _reason,
            maxLines: 3,
            decoration: const InputDecoration(labelText: 'Why? (optional)', border: OutlineInputBorder()),
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          key: const Key('refund-send'),
          style: FilledButton.styleFrom(backgroundColor: red),
          onPressed: () => Navigator.pop(context, _reason.text),
          child: const Text('Request Refund'),
        ),
      ],
    );
  }
}
