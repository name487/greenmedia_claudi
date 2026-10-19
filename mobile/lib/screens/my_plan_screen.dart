import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import 'ai_post/shared.dart';

const _purple = Color(0xFF6C2BD9);

String rupees(num paise) => '₹${NumberFormat.decimalPattern('en_IN').format(paise ~/ 100)}';

/// My Plan (business owners): plan status, the offer, billing details, mandates and payments; Start → compare plans →
/// Choose your plan → pay on Razorpay's page (or the practice checkout in demo mode).
class MyPlanScreen extends StatefulWidget {
  const MyPlanScreen({super.key, required this.clientId});
  final int clientId;

  /// Opens the payment page; replaceable in tests.
  static Future<bool> Function(Uri url) openUrl = (url) => launchUrl(url, mode: LaunchMode.externalApplication);

  @override
  State<MyPlanScreen> createState() => _MyPlanScreenState();
}

class _MyPlanScreenState extends State<MyPlanScreen> {
  Map<String, dynamic>? _d;
  String? _error;

  String get _base => '/api/clients/${widget.clientId}/plan';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await context.read<Session>().api.get(_base) as Map<String, dynamic>;
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

  Future<void> _start() async {
    final d = _d!;
    final go = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _CompareSheet(compare: d['compare'] as Map<String, dynamic>),
    );
    if (go != true || !mounted) return;
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => ChoosePlanScreen(clientId: widget.clientId, data: d)));
    if (mounted) _load();
  }

  Future<void> _billing() async {
    final saved = await Navigator.push<bool>(
        context, MaterialPageRoute(builder: (_) => BillingDetailsScreen(clientId: widget.clientId, billing: _d!['billing'] as Map<String, dynamic>)));
    if (saved == true && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Billing details saved')));
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    return Scaffold(
      appBar: navyBar('My Plan', subtitle: context.read<Session>().me!.clientName),
      body: d == null
          ? Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
                Padding(padding: const EdgeInsets.all(12), child: _StatusCard(status: d['status'] as Map<String, dynamic>)),
                if (d['can_buy'] == true) _OfferBanner(offer: d['offer'] as Map<String, dynamic>, active: (d['status'] as Map)['state'] == 'active', onStart: _start),
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 14, 12, 0),
                  child: GradientButton(key: const Key('billing-details'), label: 'Billing Details', icon: Icons.arrow_forward,
                      onPressed: d['can_buy'] == true ? _billing : null),
                ),
                const SizedBox(height: 18),
                const Center(child: Text('No Active Mandates', key: Key('mandates'), style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
                const Padding(
                  padding: EdgeInsets.fromLTRB(24, 4, 24, 0),
                  child: Text('Nothing is debited automatically — every payment is one you make yourself.', textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.black54, fontSize: 12.5)),
                ),
                const Padding(padding: EdgeInsets.fromLTRB(12, 22, 12, 8), child: Text('Payments', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
                if ((d['payments'] as List).isEmpty)
                  const _NoPayments()
                else
                  for (final p in (d['payments'] as List).cast<Map<String, dynamic>>()) _PaymentTile(p: p),
              ]),
            ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.status});
  final Map<String, dynamic> status;

  @override
  Widget build(BuildContext context) {
    final state = status['state'] as String;
    final (label, colour) = switch (state) {
      'active' => ('Active', green),
      'expired' => ('Expired', red),
      _ => ('Not Activated', const Color(0xFFB79A6B)),
    };
    final plan = (status['plan'] as Map?)?['name'] as String? ?? 'Pro';
    final until = status['valid_until'] as String?;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        gradient: const LinearGradient(colors: [Color(0xFFF1FBF4), Color(0xFFE9F6FF)]),
        border: Border.all(color: const Color(0xFFDDEBE2)),
      ),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Your $plan Plan is', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Container(
              key: const Key('plan-state'),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
              decoration: BoxDecoration(color: colour, borderRadius: BorderRadius.circular(99)),
              child: Text(label, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
            ),
            const SizedBox(height: 12),
            Row(children: [
              const Icon(Icons.calendar_month_outlined, size: 18),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  until == null ? '-' : '${state == 'expired' ? 'Ended' : 'Valid till'} ${DateFormat('d MMM yyyy').format(DateTime.parse(until))}',
                  key: const Key('plan-until'),
                ),
              ),
            ]),
            if (state == 'active')
              Padding(
                padding: const EdgeInsets.only(left: 24, top: 2),
                child: Text('${status['days_left']} days left', style: const TextStyle(color: Colors.black54, fontSize: 12)),
              ),
          ]),
        ),
        const SizedBox(
          width: 86,
          height: 86,
          child: Stack(children: [
            Positioned(left: 6, top: 10, child: _AppBadge(Icons.storefront, Color(0xFF4285F4))),
            Positioned(right: 0, top: 0, child: _AppBadge(Icons.facebook, Color(0xFF1877F2))),
            Positioned(left: 0, bottom: 4, child: _AppBadge(Icons.camera_alt, Color(0xFFE1306C))),
            Positioned(right: 8, bottom: 0, child: _AppBadge(Icons.trending_up, green)),
          ]),
        ),
      ]),
    );
  }
}

class _AppBadge extends StatelessWidget {
  const _AppBadge(this.icon, this.colour);
  final IconData icon;
  final Color colour;

  @override
  Widget build(BuildContext context) => CircleAvatar(radius: 17, backgroundColor: Colors.white, child: Icon(icon, color: colour, size: 20));
}

class _OfferBanner extends StatelessWidget {
  const _OfferBanner({required this.offer, required this.active, required this.onStart});
  final Map<String, dynamic> offer;
  final bool active;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) => Column(children: [
        Container(
          color: const Color(0xFFE53935),
          padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
          child: Row(children: [
            const Icon(Icons.warning_amber_rounded, color: Color(0xFFFFD54F)),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(active ? 'Grow even faster' : offer['headline'] as String, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
                Text(active ? 'Extend or upgrade your plan' : offer['sub'] as String, style: const TextStyle(color: Colors.white70, fontSize: 12)),
              ]),
            ),
            OutlinedButton(
              key: const Key('plan-start'),
              style: OutlinedButton.styleFrom(foregroundColor: Colors.white, side: const BorderSide(color: Colors.white70)),
              onPressed: onStart,
              child: Text(active ? 'View plans' : 'Start @ ${rupees(offer['start_amount'] as num)}/-'),
            ),
          ]),
        ),
        Container(
          width: double.infinity,
          color: Colors.white,
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text.rich(
            TextSpan(children: [
              TextSpan(text: rupees(offer['was_amount'] as num), style: const TextStyle(decoration: TextDecoration.lineThrough, color: Colors.black45)),
              const WidgetSpan(
                  alignment: PlaceholderAlignment.middle,
                  child: Padding(padding: EdgeInsets.symmetric(horizontal: 6), child: Icon(Icons.arrow_forward, size: 14))),
              TextSpan(text: rupees(offer['start_amount'] as num), style: const TextStyle(fontWeight: FontWeight.w700)),
              TextSpan(text: ' ${offer['line']}  ·  Special Offer'),
            ]),
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 12.5),
          ),
        ),
      ]);
}

class _NoPayments extends StatelessWidget {
  const _NoPayments();

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.symmetric(horizontal: 12),
        padding: const EdgeInsets.symmetric(vertical: 30, horizontal: 20),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(14), border: Border.all(color: const Color(0xFFE3E8EF))),
        child: const Column(children: [
          CircleAvatar(radius: 30, backgroundColor: Color(0xFFEAF0FB), child: Icon(Icons.receipt_long_outlined, color: Color(0xFF4169E1), size: 30)),
          SizedBox(height: 12),
          Text('No payments yet', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          SizedBox(height: 6),
          Text('Every plan payment you make shows up here, with its date and status.', textAlign: TextAlign.center,
              style: TextStyle(color: Colors.black54)),
        ]),
      );
}

class _PaymentTile extends StatelessWidget {
  const _PaymentTile({required this.p});
  final Map<String, dynamic> p;

  @override
  Widget build(BuildContext context) {
    final paid = p['status'] == 'paid';
    final when = DateTime.parse((p['paid_at'] ?? p['created_at']) as String).toLocal();
    final period = p['period_end'] == null
        ? ''
        : '  ·  ${DateFormat('d MMM yy').format(DateTime.parse(p['period_start'] as String))} – ${DateFormat('d MMM yy').format(DateTime.parse(p['period_end'] as String))}';
    return Card(
      key: Key('payment-${p['id']}'),
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      child: ListTile(
        leading: CircleAvatar(backgroundColor: (paid ? green : red).withValues(alpha: .12), child: Icon(paid ? Icons.check : Icons.close, color: paid ? green : red)),
        title: Text('${p['plan_name']} · ${rupees(p['amount'] as num)}${p['demo'] == true ? ' (practice)' : ''}'),
        subtitle: Text('${DateFormat('d MMM yyyy').format(when)}$period${(p['coupon'] as String).isEmpty ? '' : '  ·  ${p['coupon']}'}'),
        trailing: Text(paid ? 'Paid' : (p['status'] as String)[0].toUpperCase() + (p['status'] as String).substring(1),
            style: TextStyle(color: paid ? green : red, fontWeight: FontWeight.w600)),
      ),
    );
  }
}

/// "Compare plans": features by plan, then Go Premium.
class _CompareSheet extends StatelessWidget {
  const _CompareSheet({required this.compare});
  final Map<String, dynamic> compare;

  @override
  Widget build(BuildContext context) {
    final cols = (compare['columns'] as List).cast<Map<String, dynamic>>();
    const heads = [Color(0xFF1F63C6), Color(0xFFFF7A2F), Color(0xFF2E9E5B)];
    Widget cell(String v, {bool first = false}) {
      final yes = v == 'yes', no = v == 'no';
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 7),
        child: yes
            ? const Icon(Icons.check, size: 16, color: green)
            : no
                ? const Icon(Icons.close, size: 16, color: red)
                : Text(v, textAlign: first ? TextAlign.left : TextAlign.center,
                    style: TextStyle(fontSize: 11.5, color: first ? Colors.black87 : const Color(0xFFD9480F), fontWeight: first ? FontWeight.w400 : FontWeight.w600)),
      );
    }

    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * .85),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Flexible(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: const BoxDecoration(color: navy, borderRadius: BorderRadius.vertical(top: Radius.circular(12))),
                  child: const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Green Media AI Marketing', style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800)),
                    Text('Compare plans. Choose the power that grows your business.', style: TextStyle(color: Colors.white70, fontSize: 12)),
                  ]),
                ),
                Table(
                  key: const Key('compare-table'),
                  columnWidths: const {0: FlexColumnWidth(1.3)},
                  defaultVerticalAlignment: TableCellVerticalAlignment.middle,
                  border: const TableBorder(horizontalInside: BorderSide(color: Color(0xFFEDEFF3))),
                  children: [
                    TableRow(children: [
                      Container(color: navy, padding: const EdgeInsets.all(8), child: const Text('FEATURES', style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700))),
                      for (final (i, c) in cols.indexed)
                        Container(
                          color: heads[i % heads.length],
                          padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
                          child: Column(children: [
                            if (c['badge'] != null)
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 4),
                                color: const Color(0xFFFFD54F),
                                child: Text((c['badge'] as String).toUpperCase(), style: const TextStyle(fontSize: 8, fontWeight: FontWeight.w800)),
                              ),
                            Text((c['name'] as String).toUpperCase(), textAlign: TextAlign.center,
                                style: const TextStyle(color: Colors.white, fontSize: 10.5, fontWeight: FontWeight.w700)),
                            Text(c['price'] as String, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontSize: 10.5)),
                          ]),
                        ),
                    ]),
                    for (final s in (compare['sections'] as List).cast<Map<String, dynamic>>()) ...[
                      TableRow(decoration: const BoxDecoration(color: Color(0xFFFFF1E6)), children: [
                        Padding(padding: const EdgeInsets.all(6), child: Text((s['title'] as String).toUpperCase(),
                            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: Color(0xFFD9480F)))),
                        for (var i = 0; i < cols.length; i++) const SizedBox.shrink(),
                      ]),
                      for (final r in (s['rows'] as List).cast<List>())
                        TableRow(children: [cell(r[0] as String, first: true), for (final v in r.skip(1)) cell(v as String)]),
                    ],
                  ],
                ),
                Padding(padding: const EdgeInsets.all(8), child: Text(compare['footnote'] as String, style: const TextStyle(fontSize: 11, color: Colors.black45))),
              ]),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(40, 8, 40, 12),
            child: GradientButton(key: const Key('go-premium'), label: 'Go Premium', onPressed: () => Navigator.pop(context, true)),
          ),
        ]),
      ),
    );
  }
}

/// "Choose your plan": the plans, a coupon, the total, and Continue → the payment page.
class ChoosePlanScreen extends StatefulWidget {
  const ChoosePlanScreen({super.key, required this.clientId, required this.data});
  final int clientId;
  final Map<String, dynamic> data;

  @override
  State<ChoosePlanScreen> createState() => _ChoosePlanScreenState();
}

class _ChoosePlanScreenState extends State<ChoosePlanScreen> with WidgetsBindingObserver {
  late String _plan = widget.data['default_plan'] as String;
  final _coupon = TextEditingController();
  Map<String, dynamic>? _quote;
  String? _couponError;
  bool _couponOpen = false, _busy = false;
  int? _paymentId;

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}/plan';
  List<Map<String, dynamic>> get _plans => (widget.data['plans'] as List).cast<Map<String, dynamic>>();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _coupon.dispose();
    super.dispose();
  }

  // Back from the payment page: ask whether it went through
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _paymentId != null) _check();
  }

  int get _total => (_quote?['plan'] == _plan ? _quote!['amount'] : _plans.firstWhere((p) => p['key'] == _plan)['amount']) as int;

  Future<void> _apply() async {
    final code = _coupon.text.trim();
    if (code.isEmpty) return;
    try {
      final q = await _api.post('$_base/quote', {'plan': _plan, 'coupon': code}) as Map<String, dynamic>;
      setState(() {
        _quote = q;
        _couponError = null;
      });
    } on ApiException catch (e) {
      setState(() {
        _quote = null;
        _couponError = e.message;
      });
    }
  }

  Future<void> _select(String key) async {
    setState(() => _plan = key);
    if (_quote != null) await _apply();
  }

  Future<void> _continue() async {
    setState(() => _busy = true);
    try {
      final out = await _api.post('$_base/checkout', {'plan': _plan, 'coupon': _quote?['coupon'] ?? ''}) as Map<String, dynamic>;
      _paymentId = out['id'] as int;
      final opened = await MyPlanScreen.openUrl(Uri.parse(out['url'] as String));
      if (!opened && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: const Text('Couldn’t open the payment page'), backgroundColor: Colors.red.shade700));
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _check() async {
    final id = _paymentId;
    if (id == null) return;
    try {
      final st = await _api.get('$_base/payments/$id') as Map<String, dynamic>;
      if (!mounted) return;
      if (st['status'] == 'paid') {
        _paymentId = null;
        final until = (st['plan_status'] as Map)['valid_until'] as String;
        await showDialog<void>(
          context: context,
          builder: (d) => AlertDialog(
            icon: const Icon(Icons.verified, color: green, size: 44),
            title: const Text('Plan activated'),
            content: Text('${st['plan_name']} is active till ${DateFormat('d MMM yyyy').format(DateTime.parse(until))}.'),
            actions: [FilledButton(key: const Key('plan-done'), onPressed: () => Navigator.pop(d), child: const Text('Done'))],
          ),
        );
        if (mounted) Navigator.pop(context, true);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Payment not received yet — finish it on the payment page, then come back.')));
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final demo = widget.data['payments_mode'] == 'demo';
    return Scaffold(
      appBar: navyBar('My Plan', subtitle: context.read<Session>().me!.clientName),
      body: ListView(padding: const EdgeInsets.fromLTRB(14, 16, 14, 16), children: [
        const Text('Choose your plan', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        Text('For ${context.read<Session>().me!.clientName ?? 'your business'}. Pay once, nothing renews automatically.',
            style: const TextStyle(color: Colors.black54)),
        const SizedBox(height: 14),
        for (final p in _plans)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: InkWell(
              key: Key('plan-${p['key']}'),
              borderRadius: BorderRadius.circular(14),
              onTap: () => _select(p['key'] as String),
              child: Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: _plan == p['key'] ? _purple : const Color(0xFFE3E8EF), width: _plan == p['key'] ? 2 : 1),
                ),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        const Icon(Icons.receipt_outlined, size: 18),
                        const SizedBox(width: 8),
                        Text(p['name'] as String, style: const TextStyle(fontWeight: FontWeight.w700)),
                      ]),
                      if ((p['tag'] as String).isNotEmpty)
                        Padding(padding: const EdgeInsets.only(top: 6), child: Text(p['tag'] as String, style: const TextStyle(fontSize: 12, color: Colors.black54))),
                      const SizedBox(height: 6),
                      Text.rich(TextSpan(children: [
                        TextSpan(text: rupees(p['amount'] as num), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                        TextSpan(text: '  ${p['per']}', style: const TextStyle(fontSize: 12, color: Colors.black54)),
                      ])),
                      Text(p['note'] as String, style: const TextStyle(fontSize: 11.5, color: Colors.black54)),
                    ]),
                  ),
                  Icon(_plan == p['key'] ? Icons.check_circle : Icons.radio_button_unchecked, color: _plan == p['key'] ? _purple : Colors.black26),
                ]),
              ),
            ),
          ),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: const Color(0xFFE3E8EF))),
          child: Row(children: [
            const Icon(Icons.lock_outline, color: Colors.black45),
            const SizedBox(width: 10),
            Expanded(
              child: Text(demo ? 'Practice mode: a test checkout page, no money moves.' : 'Secure payments by Razorpay. One-time charge. Nothing is debited automatically later.',
                  key: const Key('payments-note'), style: const TextStyle(fontSize: 12, color: Colors.black54)),
            ),
          ]),
        ),
      ]),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 10),
          decoration: const BoxDecoration(color: Colors.white, border: Border(top: BorderSide(color: Color(0xFFE3E8EF)))),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (!_couponOpen)
              GestureDetector(
                key: const Key('coupon-open'),
                onTap: () => setState(() => _couponOpen = true),
                child: const Text('Have a coupon code?', style: TextStyle(color: _purple, fontWeight: FontWeight.w600)),
              )
            else
              Row(children: [
                Expanded(
                  child: TextField(
                    key: const Key('coupon'),
                    controller: _coupon,
                    textCapitalization: TextCapitalization.characters,
                    decoration: InputDecoration(isDense: true, hintText: 'Coupon code', errorText: _couponError,
                        helperText: _quote?['message'] as String?, helperStyle: const TextStyle(color: green)),
                  ),
                ),
                TextButton(key: const Key('coupon-apply'), onPressed: _apply, child: const Text('Apply')),
              ]),
            const SizedBox(height: 8),
            Row(children: [
              Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(rupees(_total), key: const Key('plan-total'), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                const Text('Total', style: TextStyle(fontSize: 12, color: Colors.black54)),
              ]),
              const SizedBox(width: 12),
              if (_paymentId != null)
                TextButton(key: const Key('plan-check'), onPressed: _check, child: const Text('I’ve paid')),
              Expanded(
                child: FilledButton(
                  key: const Key('plan-continue'),
                  style: FilledButton.styleFrom(backgroundColor: _purple, minimumSize: const Size.fromHeight(46)),
                  onPressed: _busy ? null : _continue,
                  child: _busy
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('Continue'),
                ),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}

/// VAT/GSTIN, billing address, "shipping same as billing", shipping address.
class BillingDetailsScreen extends StatefulWidget {
  const BillingDetailsScreen({super.key, required this.clientId, required this.billing});
  final int clientId;
  final Map<String, dynamic> billing;

  @override
  State<BillingDetailsScreen> createState() => _BillingDetailsScreenState();
}

class _BillingDetailsScreenState extends State<BillingDetailsScreen> {
  late final _gstin = TextEditingController(text: widget.billing['gstin'] as String? ?? '');
  late final _bill = TextEditingController(text: widget.billing['billing_address'] as String? ?? '');
  late final _ship = TextEditingController(text: widget.billing['shipping_address'] as String? ?? '');
  late bool _same = widget.billing['shipping_same'] as bool? ?? true;
  bool _busy = false;
  String? _gstinError;

  @override
  void dispose() {
    _gstin.dispose();
    _bill.dispose();
    _ship.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _gstinError = null;
    });
    try {
      await context.read<Session>().api.put('/api/clients/${widget.clientId}/plan/billing',
          {'gstin': _gstin.text.trim(), 'billing_address': _bill.text, 'shipping_same': _same, 'shipping_address': _same ? '' : _ship.text});
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _gstinError = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    InputDecoration box(String hint) => InputDecoration(hintText: hint, border: const OutlineInputBorder(), suffixIcon: const Icon(Icons.edit_outlined, size: 18));
    return Scaffold(
      appBar: navyBar('My Plan', subtitle: context.read<Session>().me!.clientName),
      body: ListView(padding: const EdgeInsets.all(14), children: [
        const Text('Billing Details', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('VAT/GSTIN'),
              const SizedBox(height: 6),
              TextField(key: const Key('gstin'), controller: _gstin, textCapitalization: TextCapitalization.characters, maxLength: 15,
                  decoration: box('27ABCDE1234F1Z5').copyWith(errorText: _gstinError, errorMaxLines: 3)),
              const SizedBox(height: 10),
              const Text('Billing Address'),
              const SizedBox(height: 6),
              TextField(key: const Key('billing-address'), controller: _bill, maxLines: 3, decoration: box('Shop / street, area, city, PIN')),
              CheckboxListTile(
                key: const Key('shipping-same'),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                value: _same,
                onChanged: (v) => setState(() => _same = v ?? true),
                title: const Text('Shipping address Same as Billing Address'),
              ),
              const Text('Shipping Address'),
              const SizedBox(height: 6),
              TextField(key: const Key('shipping-address'), controller: _same ? _bill : _ship, enabled: !_same, maxLines: 3, decoration: box('Where we send anything physical')),
            ]),
          ),
        ),
      ]),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 6, 14, 10),
          child: GradientButton(key: const Key('billing-save'), label: 'Save', icon: Icons.arrow_forward, busy: _busy, onPressed: _save),
        ),
      ),
    );
  }
}
