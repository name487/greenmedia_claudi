import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../state/session.dart';

const _navy = Color(0xFF0E1A3A);
const _flame = LinearGradient(colors: [Color(0xFFB04DE8), Color(0xFFFF7A2F)]);

/// Connect the business's Facebook Page or Instagram from the app. Pops `true` once connected.
///
/// 1. "Taking you to Facebook" → the API gives a Facebook login link, opened in the in-app browser.
/// 2. The owner logs in there; Facebook sends them to our API, which links the Page (or asks which Page).
/// 3. Back in the app we poll the attempt: connected → done; several Pages → pick one; otherwise the
///    "didn't finish connecting" screen explains what to fix and offers Connect again.
class MetaConnectScreen extends StatefulWidget {
  const MetaConnectScreen({super.key, required this.clientId, required this.platform});
  final int clientId;
  final String platform; // facebook | instagram

  /// Opens the login page; replaceable in tests.
  static Future<bool> Function(Uri url) openUrl = (url) => launchUrl(url, mode: LaunchMode.inAppBrowserView);

  @override
  State<MetaConnectScreen> createState() => _MetaConnectScreenState();
}

enum _Stage { starting, waiting, choose, failed }

class _MetaConnectScreenState extends State<MetaConnectScreen> with WidgetsBindingObserver {
  _Stage _stage = _Stage.starting;
  String? _attempt, _message, _reason;
  List<Map<String, dynamic>> _candidates = [];
  Timer? _poll, _grace;
  bool _busy = false, _dialogShown = false;

  bool get _fb => widget.platform == 'facebook';
  String get _label => _fb ? 'Facebook' : 'Instagram';
  String get _base => '/api/clients/${widget.clientId}/meta/connect';
  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    _grace?.cancel();
    super.dispose();
  }

  Future<void> _start() async {
    _poll?.cancel();
    _grace?.cancel();
    setState(() {
      _stage = _Stage.starting;
      _dialogShown = false;
    });
    try {
      final out = await _api.post(_base, {'platform': widget.platform}) as Map<String, dynamic>;
      _attempt = out['id'] as String;
      // a moment on "Taking you to Facebook" so the tip can be read
      await Future<void>.delayed(const Duration(milliseconds: 900));
      if (!mounted) return;
      var opened = false;
      try {
        opened = await MetaConnectScreen.openUrl(Uri.parse(out['auth_url'] as String));
      } catch (_) {
        opened = false;
      }
      if (!mounted) return;
      if (!opened) return _fail('error', 'Couldn’t open $_label on this phone. Check that a browser is installed and try again.');
      setState(() => _stage = _Stage.waiting);
      _poll = Timer.periodic(const Duration(seconds: 2), (_) => _check());
    } on ApiException catch (e) {
      if (mounted) _fail(e.status == 503 ? 'not_configured' : 'error', e.message);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Back from the browser: check now, and if the login still hasn't finished shortly after, it was abandoned.
    if (state == AppLifecycleState.resumed && _stage == _Stage.waiting) {
      _check();
      _grace?.cancel();
      _grace = Timer(const Duration(seconds: 5), () async {
        if (!mounted || _stage != _Stage.waiting || _attempt == null) return;
        try {
          _apply(await _api.post('$_base/$_attempt/cancel') as Map<String, dynamic>);
        } on ApiException catch (e) {
          _fail('error', e.message);
        }
      });
    }
  }

  Future<void> _check() async {
    if (_attempt == null || _stage != _Stage.waiting) return;
    try {
      _apply(await _api.get('$_base/$_attempt') as Map<String, dynamic>);
    } on ApiException {
      // keep waiting; a network blip shouldn't fail the connection
    }
  }

  void _apply(Map<String, dynamic> st) {
    if (!mounted) return;
    switch (st['status']) {
      case 'connected':
        _poll?.cancel();
        _grace?.cancel();
        Navigator.pop(context, true);
      case 'choose_page':
        _poll?.cancel();
        _grace?.cancel();
        setState(() {
          _stage = _Stage.choose;
          _candidates = (st['candidates'] as List).cast<Map<String, dynamic>>();
        });
      case 'failed':
        _fail(st['reason'] as String? ?? 'error', st['message'] as String? ?? '');
    }
  }

  void _fail(String reason, String message) {
    _poll?.cancel();
    _grace?.cancel();
    setState(() {
      _stage = _Stage.failed;
      _reason = reason;
      _message = message;
    });
    if (!_dialogShown && reason != 'not_configured') {
      _dialogShown = true;
      WidgetsBinding.instance.addPostFrameCallback((_) => _failureDialog());
    }
  }

  Future<void> _choose(String pageId) async {
    setState(() => _busy = true);
    try {
      _apply(await _api.post('$_base/$_attempt/choose', {'page_id': pageId}) as Map<String, dynamic>);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _cancel() async {
    if (_attempt != null && _stage == _Stage.waiting) {
      try {
        await _api.post('$_base/$_attempt/cancel');
      } on ApiException {
        // leaving anyway
      }
    }
    if (mounted) Navigator.pop(context, false);
  }

  List<String> get _checklist => [
        'Finish the $_label screen without pressing back',
        'Allow every permission it asks for',
        _fb ? 'Log in with the Facebook account that manages your business Page' : 'Use an Instagram Business or Creator account linked to your Facebook Page',
      ];

  List<String> get _steps => _fb
      ? [
          'Tap “Connect Facebook again”.',
          'Log in with the Facebook account that is an admin of your business Page.',
          'When asked, choose your business Page (and its Instagram, if shown).',
          'Keep every permission toggle on and tap Continue until the last screen.',
          'Come back to this app — it finishes by itself.',
        ]
      : [
          'In the Instagram app: Settings → Account type → switch to a Business or Creator account.',
          'Link it to your Facebook Page (Instagram: Edit profile → Page, or from the Page’s settings).',
          'Tap “Connect Instagram again” and log in with the Facebook account that manages that Page.',
          'Keep every permission toggle on and tap Continue until the last screen.',
          'Come back to this app — it finishes by itself.',
        ];

  Future<void> _failureDialog() async {
    if (!mounted) return;
    final retry = await showDialog<bool>(
      context: context,
      builder: (d) => Dialog(
        clipBehavior: Clip.antiAlias,
        insetPadding: const EdgeInsets.symmetric(horizontal: 24),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
            decoration: const BoxDecoration(gradient: _flame),
            padding: const EdgeInsets.fromLTRB(16, 6, 4, 6),
            child: Row(children: [
              Expanded(child: Text('$_label login failed', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
              IconButton(tooltip: 'Close', icon: const Icon(Icons.close, color: Colors.white), onPressed: () => Navigator.pop(d, false)),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                const Icon(Icons.warning_amber_rounded, color: Color(0xFFE5484D)),
                const SizedBox(width: 6),
                Expanded(child: Text('$_label login was not completed', style: const TextStyle(fontWeight: FontWeight.w700))),
              ]),
              const SizedBox(height: 6),
              Text(_message ?? '', style: Theme.of(d).textTheme.bodySmall),
              const SizedBox(height: 10),
              _HowToSolve(steps: _steps),
              const SizedBox(height: 10),
              _GradientButton(label: 'Try again', onPressed: () => Navigator.pop(d, true)),
              TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Not now')),
            ]),
          ),
        ]),
      ),
    );
    if (retry == true && mounted) _start();
  }

  void _stepByStep() => showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        isScrollControlled: true,
        builder: (s) => SafeArea(
          child: SingleChildScrollView(
            padding: EdgeInsets.zero,
            child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Connect $_label step by step', style: Theme.of(s).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 10),
              for (final (i, step) in _steps.indexed)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    CircleAvatar(radius: 12, backgroundColor: const Color(0xFFE8457C), child: Text('${i + 1}', style: const TextStyle(color: Colors.white, fontSize: 12))),
                    const SizedBox(width: 10),
                    Expanded(child: Text(step)),
                  ]),
                ),
            ]),
          ),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _stage != _Stage.waiting,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _cancel();
      },
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: _navy,
          foregroundColor: Colors.white,
          title: Text(_label),
          bottom: _stage == _Stage.waiting || _stage == _Stage.starting
              ? const PreferredSize(preferredSize: Size.fromHeight(3), child: LinearProgressIndicator(minHeight: 3))
              : null,
        ),
        body: SafeArea(
          child: switch (_stage) {
            _Stage.starting || _Stage.waiting => _intro(context),
            _Stage.choose => _choosePage(context),
            _Stage.failed => _failed(context),
          },
        ),
      ),
    );
  }

  Widget _platformIcon({bool failed = false, double size = 22}) => Stack(clipBehavior: Clip.none, children: [
        CircleAvatar(
          radius: size,
          backgroundColor: _fb ? const Color(0xFFE7F0FF) : const Color(0xFFFDE8F1),
          child: Icon(_fb ? Icons.facebook : Icons.camera_alt_outlined, color: _fb ? const Color(0xFF1877F2) : const Color(0xFFE1306C), size: size),
        ),
        if (failed)
          const Positioned(right: -2, bottom: -2, child: CircleAvatar(radius: 8, backgroundColor: Color(0xFFE5484D), child: Icon(Icons.close, size: 11, color: Colors.white))),
      ]);

  Widget _intro(BuildContext context) {
    final t = Theme.of(context).textTheme;
    // fills the screen, and scrolls instead of overflowing on small phones / large text
    return LayoutBuilder(
      builder: (context, box) => SingleChildScrollView(
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: box.maxHeight),
          child: IntrinsicHeight(child: _introColumn(t)),
        ),
      ),
    );
  }

  Widget _introColumn(TextTheme t) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 28, 16, 8),
      child: Column(children: [
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          const CircleAvatar(radius: 22, backgroundColor: _navy, child: Icon(Icons.auto_awesome, color: Colors.white)),
          const Padding(padding: EdgeInsets.symmetric(horizontal: 10), child: Icon(Icons.arrow_forward, size: 18)),
          _platformIcon(),
        ]),
        const SizedBox(height: 18),
        Text('Taking you to $_label', key: const Key('meta-intro'), style: t.titleLarge?.copyWith(fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        Text(_fb ? 'Log in with the account that manages your Page.' : 'Log in with the Instagram account for your business.', textAlign: TextAlign.center, style: t.bodyMedium),
        const SizedBox(height: 18),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(10)),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.lightbulb_outline, color: Color(0xFFF2B01E), size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text('On $_label’s screen, keep every permission toggle on and tap Continue to the end — otherwise the connection stops halfway.',
                  style: t.bodySmall),
            ),
          ]),
        ),
        const Spacer(),
        if (_stage == _Stage.waiting) Text('Waiting for $_label… come back here when you’re done.', style: t.bodySmall),
        const SizedBox(height: 16),
        const CircularProgressIndicator(),
        const Spacer(),
        TextButton(onPressed: _cancel, child: const Text('Cancel')),
      ]),
    );
  }

  Widget _choosePage(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Which Page is your business?', style: t.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 4),
      Text('Your Facebook account manages more than one Page. Posts will go to the one you pick${_fb ? '' : ' and its Instagram'}.', style: t.bodySmall),
      const SizedBox(height: 12),
      for (final c in _candidates)
        Card(
          child: ListTile(
            leading: const CircleAvatar(backgroundColor: Color(0xFF1877F2), child: Icon(Icons.flag_outlined, color: Colors.white)),
            title: Text(c['name'] as String, style: const TextStyle(fontWeight: FontWeight.w600)),
            subtitle: Text(c['instagram'] == null ? 'No Instagram linked' : 'Instagram @${c['instagram']}'),
            trailing: _busy ? null : const Icon(Icons.chevron_right),
            onTap: _busy ? null : () => _choose(c['page_id'] as String),
          ),
        ),
    ]);
  }

  Widget _failed(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final setup = _reason == 'not_configured';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Expanded(
        child: ListView(padding: const EdgeInsets.fromLTRB(16, 20, 16, 8), children: [
          Align(alignment: Alignment.centerLeft, child: _platformIcon(failed: true, size: 18)),
          const SizedBox(height: 14),
          Text('$_label didn’t finish connecting', key: const Key('meta-failed'), style: t.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text(_message ?? '', style: t.bodyMedium?.copyWith(color: Theme.of(context).hintColor)),
          if (!setup) ...[
            const SizedBox(height: 16),
            for (final c in _checklist)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 5),
                child: Row(children: [
                  const Icon(Icons.check_circle_outline, color: Color(0xFF2E9E5B), size: 20),
                  const SizedBox(width: 8),
                  Expanded(child: Text(c)),
                ]),
              ),
            const SizedBox(height: 10),
            _HowToSolve(steps: _steps),
          ],
        ]),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (!setup) _GradientButton(label: 'Connect $_label again', onPressed: _start),
          TextButton(onPressed: setup ? () => Navigator.pop(context, false) : _stepByStep, child: Text(setup ? 'Back' : 'Show me step by step')),
        ]),
      ),
    ]);
  }
}

class _HowToSolve extends StatelessWidget {
  const _HowToSolve({required this.steps});
  final List<String> steps;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).colorScheme.primary.withValues(alpha: .5)), borderRadius: BorderRadius.circular(8)),
        child: Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            dense: true,
            title: const Text('How to solve this'),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [for (final (i, s) in steps.indexed) Padding(padding: const EdgeInsets.symmetric(vertical: 3), child: Text('${i + 1}. $s'))],
          ),
        ),
      );
}

class _GradientButton extends StatelessWidget {
  const _GradientButton({required this.label, required this.onPressed});
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: BoxDecoration(gradient: _flame, borderRadius: BorderRadius.circular(10)),
        child: FilledButton(
          style: FilledButton.styleFrom(backgroundColor: Colors.transparent, shadowColor: Colors.transparent, minimumSize: const Size.fromHeight(48)),
          onPressed: onPressed,
          child: Text(label, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
        ),
      );
}
