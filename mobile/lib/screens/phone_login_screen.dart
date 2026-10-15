import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/session.dart';
import 'login_screen.dart';
import 'settings_screen.dart';

const _ink = Color(0xFF0B1A12);
const _headerTop = Color(0xFF0B1A12);
const _headerBottom = Color(0xFF123524);
const _gradient = LinearGradient(colors: [Color(0xFF0F7A45), Color(0xFF1FAE6B)]);

/// Mobile sign-in: phone number → one-time code → choose a profile. Email + password stays available for staff.
class PhoneLoginScreen extends StatefulWidget {
  const PhoneLoginScreen({super.key});

  @override
  State<PhoneLoginScreen> createState() => _PhoneLoginScreenState();
}

enum _Step { phone, code, profiles, email }

class _PhoneLoginScreenState extends State<PhoneLoginScreen> {
  _Step _step = _Step.phone;
  String _countryCode = '+91';
  final _phone = TextEditingController();
  final _code = TextEditingController();
  final _codeFocus = FocusNode();
  OtpSent? _sent;
  OtpVerified? _verified;
  String? _error;
  bool _busy = false;
  int _resendIn = 0;
  Timer? _timer;

  static const _countries = {'+91': 10, '+971': 9, '+1': 10, '+44': 10};

  bool get _phoneValid {
    final digits = _phone.text.replaceAll(RegExp(r'\D'), '');
    final len = _countries[_countryCode]!;
    if (digits.length != len) return false;
    return _countryCode != '+91' || RegExp(r'^[6-9]').hasMatch(digits);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _phone.dispose();
    _code.dispose();
    _codeFocus.dispose();
    super.dispose();
  }

  void _startTimer(int seconds) {
    _timer?.cancel();
    setState(() => _resendIn = seconds);
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) return t.cancel();
      setState(() => _resendIn = (_resendIn - 1).clamp(0, 999));
      if (_resendIn == 0) t.cancel();
    });
  }

  Future<void> _run(Future<void> Function(Session s) action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action(context.read<Session>());
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _requestCode() => _run((s) async {
        final sent = await s.requestOtp(_phone.text, countryCode: _countryCode);
        _code.clear();
        setState(() {
          _sent = sent;
          _step = _Step.code;
        });
        _startTimer(sent.resendIn);
        _codeFocus.requestFocus();
      });

  Future<void> _verify() => _run((s) async {
        final v = await s.verifyOtp(_sent!.phone, _code.text);
        setState(() {
          _verified = v;
          _step = _Step.profiles;
        });
        if (v.profiles.length == 1) await s.selectProfile(v.otpToken, v.profiles.single.userId);
      });

  Future<void> _open(LoginProfile p) => _run((s) => s.selectProfile(_verified!.otpToken, p.userId));

  void _back() => setState(() {
        _error = null;
        _step = _step == _Step.profiles ? _Step.code : _Step.phone;
      });

  @override
  Widget build(BuildContext context) {
    if (_step == _Step.email) return LoginScreen(onUsePhone: () => setState(() => _step = _Step.phone));
    return PopScope(
      canPop: _step == _Step.phone,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        backgroundColor: Colors.white,
        body: switch (_step) {
          _Step.profiles => _profiles(context),
          _ => _form(context),
        },
      ),
    );
  }

  // ---------- phone + code ----------

  Widget _form(BuildContext context) {
    final code = _step == _Step.code;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _Header(
        title: code ? 'Verify your\nmobile number' : 'Enter your\nphone number',
        subtitle: code ? 'Code sent to ${_sent!.masked}' : "We'll send a one-time verification code",
        onBack: code ? _back : null,
      ),
      Expanded(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 24, 20, 24),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: code ? _codeStep(context) : _phoneStep(context)),
            ),
          ),
        ),
      ),
    ]);
  }

  List<Widget> _phoneStep(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final valid = _phoneValid;
    return [
      Row(children: [
        const Icon(Icons.smartphone, size: 18),
        const SizedBox(width: 6),
        Text('Mobile number', style: t.labelLarge),
        const SizedBox(width: 12),
        Expanded(
          child: Align(
            alignment: Alignment.centerRight,
            child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: _ink, borderRadius: BorderRadius.circular(8)),
              child: Text('Example: 9876543210', maxLines: 1, overflow: TextOverflow.ellipsis, style: t.labelSmall?.copyWith(color: Colors.white)),
            ),
          ),
        ),
      ]),
      const SizedBox(height: 10),
      AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: valid ? const Color(0xFF1FAE6B) : Colors.blueGrey.shade200, width: valid ? 1.6 : 1.2),
        ),
        child: Row(children: [
          const SizedBox(width: 8),
          DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              value: _countryCode,
              items: [for (final c in _countries.keys) DropdownMenuItem(value: c, child: Text(c))],
              onChanged: (v) => setState(() => _countryCode = v!),
            ),
          ),
          Container(width: 1, height: 28, color: Colors.blueGrey.shade100),
          Expanded(
            child: TextField(
              key: const Key('phone'),
              controller: _phone,
              autofocus: true,
              keyboardType: TextInputType.phone,
              autofillHints: const [AutofillHints.telephoneNumberNational],
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(_countries[_countryCode])],
              style: t.titleMedium,
              decoration: InputDecoration(
                hintText: 'Enter ${_countries[_countryCode]}-digit number',
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 16),
              ),
              onChanged: (_) => setState(() => _error = null),
              onSubmitted: (_) => valid && !_busy ? _requestCode() : null,
            ),
          ),
          if (valid) const Padding(padding: EdgeInsets.only(right: 12), child: Icon(Icons.check_circle, color: Color(0xFF1FAE6B))),
        ]),
      ),
      if (_error != null) _ErrorText(_error!),
      const SizedBox(height: 20),
      GradientButton(label: _busy ? 'Sending…' : 'Get OTP', onPressed: valid && !_busy ? _requestCode : null),
      const SizedBox(height: 10),
      const _SafeNote(),
      const SizedBox(height: 28),
      const Divider(),
      const SizedBox(height: 8),
      TextButton(onPressed: () => setState(() => _step = _Step.email), child: const Text('Agency team? Sign in with email')),
      TextButton.icon(
        icon: const Icon(Icons.dns_outlined, size: 16),
        label: Text('Server: ${context.watch<Session>().api.baseUrl}', overflow: TextOverflow.ellipsis, style: t.bodySmall),
        onPressed: () => showServerDialog(context),
      ),
    ];
  }

  List<Widget> _codeStep(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final length = _sent!.length;
    final ready = _code.text.length == length;
    return [
      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.pin_outlined, size: 18),
        const SizedBox(width: 6),
        Text('Enter OTP', style: t.labelLarge),
      ]),
      const SizedBox(height: 12),
      OtpBoxes(
        controller: _code,
        focusNode: _codeFocus,
        length: length,
        onChanged: (v) {
          setState(() => _error = null);
          if (v.length == length && !_busy) _verify();
        },
      ),
      const SizedBox(height: 14),
      Center(
        child: _resendIn > 0
            ? Text('00:${_resendIn.toString().padLeft(2, '0')}', style: t.bodyMedium?.copyWith(color: Colors.blueGrey))
            : TextButton(onPressed: _busy ? null : _requestCode, child: const Text('Resend code')),
      ),
      if (_sent!.devCode != null)
        Center(
          child: ActionChip(
            avatar: const Icon(Icons.science_outlined, size: 16),
            label: Text('Demo server — code ${_sent!.devCode}'),
            onPressed: () {
              _code.text = _sent!.devCode!;
              _verify();
            },
          ),
        ),
      if (_error != null) Center(child: _ErrorText(_error!)),
      const SizedBox(height: 20),
      GradientButton(label: _busy ? 'Verifying…' : 'Verify OTP', onPressed: ready && !_busy ? _verify : null),
      const SizedBox(height: 10),
      const _SafeNote(),
      const SizedBox(height: 16),
      Text("Didn't get a code? Check the number, or ask your agency to add it to your account.",
          textAlign: TextAlign.center, style: t.bodySmall?.copyWith(color: Colors.blueGrey)),
    ];
  }

  // ---------- choose a profile ----------

  Widget _profiles(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final v = _verified!;
    final groups = <String, List<LoginProfile>>{};
    for (final p in v.profiles) {
      groups.putIfAbsent(p.group, () => []).add(p);
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        color: _headerTop,
        padding: EdgeInsets.fromLTRB(8, MediaQuery.paddingOf(context).top + 8, 16, 14),
        child: Row(children: [
          IconButton(onPressed: _back, icon: const Icon(Icons.arrow_back, color: Colors.white), tooltip: 'Back'),
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Select profile', style: t.titleLarge?.copyWith(color: Colors.white)),
            Text(v.phone, style: t.bodySmall?.copyWith(color: Colors.white70)),
          ]),
        ]),
      ),
      Expanded(
        child: v.profiles.length == 1 || (_busy && v.profiles.isEmpty)
            ? Center(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const CircularProgressIndicator(),
                  const SizedBox(height: 14),
                  Text('Almost ready', style: t.titleMedium),
                ]),
              )
            : v.profiles.isEmpty
                ? Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      const Icon(Icons.person_search_outlined, size: 48, color: Colors.blueGrey),
                      const SizedBox(height: 12),
                      Text('No account uses this number yet', style: t.titleMedium, textAlign: TextAlign.center),
                      const SizedBox(height: 6),
                      Text('Ask your Green Media account manager to add ${v.phone} to your profile, or sign in with email.',
                          style: t.bodyMedium, textAlign: TextAlign.center),
                      const SizedBox(height: 12),
                      TextButton(onPressed: () => setState(() => _step = _Step.email), child: const Text('Sign in with email')),
                    ]),
                  )
                : ListView(padding: const EdgeInsets.all(16), children: [
                    for (final g in groups.entries) ...[
                      _GroupHeader(label: g.key, profiles: g.value),
                      for (final p in g.value) _ProfileCard(profile: p, onTap: _busy ? null : () => _open(p)),
                      const SizedBox(height: 10),
                    ],
                    if (_error != null) _ErrorText(_error!),
                    const SizedBox(height: 8),
                    const _TrustCard(),
                  ]),
      ),
    ]);
  }
}

// ---------- pieces ----------

class _Header extends StatelessWidget {
  const _Header({required this.title, required this.subtitle, this.onBack});
  final String title, subtitle;
  final VoidCallback? onBack;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Container(
      decoration: const BoxDecoration(gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [_headerTop, _headerBottom])),
      padding: EdgeInsets.fromLTRB(20, MediaQuery.paddingOf(context).top + (onBack == null ? 40 : 4), 20, 26),
      child: Stack(clipBehavior: Clip.none, children: [
        Positioned(
          right: -60,
          top: -70,
          child: Container(width: 190, height: 190, decoration: BoxDecoration(shape: BoxShape.circle, color: Colors.white.withValues(alpha: .05))),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (onBack != null)
            IconButton(
              onPressed: onBack,
              tooltip: 'Back',
              style: IconButton.styleFrom(backgroundColor: Colors.white12),
              icon: const Icon(Icons.arrow_back, color: Colors.white, size: 20),
            ),
          if (onBack != null) const SizedBox(height: 12),
          Text(title, style: t.headlineSmall?.copyWith(color: Colors.white, fontWeight: FontWeight.w700, height: 1.2)),
          const SizedBox(height: 6),
          Text(subtitle, style: t.bodyMedium?.copyWith(color: Colors.white70)),
        ]),
      ]),
    );
  }
}

/// Full-width brand gradient button; faded when disabled.
class GradientButton extends StatelessWidget {
  const GradientButton({super.key, required this.label, required this.onPressed, this.icon = Icons.arrow_forward});
  final String label;
  final VoidCallback? onPressed;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    return Opacity(
      opacity: enabled ? 1 : .45,
      child: DecoratedBox(
        decoration: BoxDecoration(gradient: _gradient, borderRadius: BorderRadius.circular(12)),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: onPressed,
            child: SizedBox(
              height: 52,
              child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                Text(label, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
                const SizedBox(width: 8),
                Icon(icon, color: Colors.white, size: 20),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// N single-digit boxes backed by one hidden field (paste, SMS autofill and backspace all work).
class OtpBoxes extends StatelessWidget {
  const OtpBoxes({super.key, required this.controller, required this.focusNode, required this.length, required this.onChanged});
  final TextEditingController controller;
  final FocusNode focusNode;
  final int length;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: focusNode.requestFocus,
      child: Stack(alignment: Alignment.center, children: [
        Opacity(
          opacity: 0,
          child: SizedBox(
            height: 56,
            child: TextField(
              key: const Key('otp'),
              controller: controller,
              focusNode: focusNode,
              keyboardType: TextInputType.number,
              autofillHints: const [AutofillHints.oneTimeCode],
              inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(length)],
              onChanged: onChanged,
            ),
          ),
        ),
        ListenableBuilder(
          listenable: Listenable.merge([controller, focusNode]),
          builder: (context, _) {
            final text = controller.text;
            return Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              for (var i = 0; i < length; i++)
                Container(
                  width: 54,
                  height: 56,
                  margin: const EdgeInsets.symmetric(horizontal: 6),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: i < text.length || i == text.length ? Colors.white : const Color(0xFFEFF3F1),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: focusNode.hasFocus && i == text.length ? const Color(0xFF0F7A45) : Colors.blueGrey.shade200,
                      width: focusNode.hasFocus && i == text.length ? 1.8 : 1.2,
                    ),
                  ),
                  child: Text(i < text.length ? text[i] : '', style: Theme.of(context).textTheme.headlineSmall),
                ),
            ]);
          },
        ),
      ]),
    );
  }
}

class _SafeNote extends StatelessWidget {
  const _SafeNote();

  @override
  Widget build(BuildContext context) => Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.lock_outline, size: 14, color: Colors.blueGrey),
        const SizedBox(width: 4),
        Text('Your number is safe with us', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.blueGrey)),
      ]);
}

class _ErrorText extends StatelessWidget {
  const _ErrorText(this.message);
  final String message;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Text(message, style: TextStyle(color: Theme.of(context).colorScheme.error)),
      );
}

class _GroupHeader extends StatelessWidget {
  const _GroupHeader({required this.label, required this.profiles});
  final String label;
  final List<LoginProfile> profiles;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final needs = profiles.every((p) => p.needsGoogle);
    final agency = profiles.every((p) => p.kind == 'agency');
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 6, 4, 6),
      child: Row(children: [
        Icon(agency ? Icons.groups_2_outlined : (needs ? Icons.error : Icons.verified), size: 16,
            color: agency ? Colors.blueGrey : (needs ? Colors.orange.shade700 : Colors.blue.shade700)),
        const SizedBox(width: 6),
        Flexible(child: Text(label, style: t.bodyMedium, overflow: TextOverflow.ellipsis)),
        const SizedBox(width: 8),
        if (needs)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: Colors.orange.shade50, borderRadius: BorderRadius.circular(6), border: Border.all(color: Colors.orange.shade200)),
            child: Text('Needs Google', style: t.labelSmall?.copyWith(color: Colors.orange.shade800, fontWeight: FontWeight.w600)),
          )
        else
          Text('${profiles.length}', style: t.labelSmall?.copyWith(color: Colors.blueGrey)),
      ]),
    );
  }
}

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.profile, required this.onTap});
  final LoginProfile profile;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final tint = profile.kind == 'agency' ? Colors.indigo : (profile.needsGoogle ? Colors.green : Colors.purple);
    return Card(
      child: ListTile(
        onTap: onTap,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        leading: Container(
          width: 40,
          height: 40,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: tint.shade50, borderRadius: BorderRadius.circular(10)),
          child: Text(profile.title.isEmpty ? '?' : profile.title[0].toUpperCase(),
              style: t.titleMedium?.copyWith(color: tint.shade700, fontWeight: FontWeight.w700)),
        ),
        title: Text(profile.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
        subtitle: Text([profile.subtitle, if (profile.kind == 'agency') profile.roleLabel].where((s) => s.isNotEmpty).toSet().join(' · ')),
        trailing: const Icon(Icons.chevron_right),
      ),
    );
  }
}

class _TrustCard extends StatelessWidget {
  const _TrustCard();

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.blueGrey.shade700);
    Widget item(IconData i, Color c, String s) => Expanded(
          child: Column(children: [Icon(i, color: c), const SizedBox(height: 6), Text(s, textAlign: TextAlign.center, style: t)]),
        );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            item(Icons.location_on_outlined, Colors.green.shade700, 'Connects to Google Business Profile only'),
            item(Icons.mark_email_unread_outlined, Colors.red.shade400, "Can't read your emails"),
            item(Icons.verified_user_outlined, Colors.green.shade700, 'Approval before anything is published'),
          ]),
          const SizedBox(height: 10),
          Text('Profiles marked “Needs Google” can be connected from your account manager or the web app.', style: t, textAlign: TextAlign.center),
        ]),
      ),
    );
  }
}
