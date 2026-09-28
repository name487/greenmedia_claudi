import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import 'settings_screen.dart';

const demoUsers = [
  ('Admin', 'admin@greenmedia.in'),
  ('Account Manager', 'priya@greenmedia.in'),
  ('SEO', 'rohit@greenmedia.in'),
  ('Content', 'sneha@greenmedia.in'),
  ('Designer', 'kabir@greenmedia.in'),
  ('Client', 'anjali@smiledental.in'),
];

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<Session>().login(_email.text, _password.text);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      backgroundColor: const Color(0xFF0B1A12),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: AutofillGroup(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Row(children: [
                        Container(
                          width: 40,
                          height: 40,
                          decoration: BoxDecoration(color: const Color(0xFF0F7A45), borderRadius: BorderRadius.circular(10)),
                          child: const Icon(Icons.eco, color: Colors.white),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text('Green Media', style: t.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
                            Text('AI Command Center', style: t.bodySmall),
                          ]),
                        ),
                      ]),
                      const SizedBox(height: 24),
                      TextField(
                        controller: _email,
                        decoration: const InputDecoration(labelText: 'Email'),
                        keyboardType: TextInputType.emailAddress,
                        autofillHints: const [AutofillHints.username],
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _password,
                        decoration: const InputDecoration(labelText: 'Password'),
                        obscureText: true,
                        autofillHints: const [AutofillHints.password],
                        onSubmitted: (_) => _submit(),
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 12),
                        Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                      ],
                      const SizedBox(height: 16),
                      FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Signing in…' : 'Sign in')),
                      const SizedBox(height: 20),
                      Text('Demo accounts (password demo1234):', style: t.bodySmall),
                      const SizedBox(height: 6),
                      Wrap(spacing: 6, runSpacing: 6, children: [
                        for (final (role, email) in demoUsers)
                          ActionChip(
                            label: Text(role),
                            onPressed: () => setState(() {
                              _email.text = email;
                              _password.text = 'demo1234';
                            }),
                          ),
                      ]),
                      const SizedBox(height: 8),
                      TextButton.icon(
                        icon: const Icon(Icons.dns_outlined, size: 18),
                        label: Text('Server: ${context.watch<Session>().api.baseUrl}', overflow: TextOverflow.ellipsis),
                        onPressed: () => showServerDialog(context),
                      ),
                    ]),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
