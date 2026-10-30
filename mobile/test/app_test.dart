import 'dart:convert';
import 'dart:io';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greenmedia/api/api_client.dart';
import 'package:greenmedia/api/models.dart';
import 'package:greenmedia/main.dart';
import 'package:greenmedia/screens/ai_post/items_screen.dart';
import 'package:greenmedia/screens/google_media_screen.dart';
import 'package:greenmedia/screens/google_post_screen.dart';
import 'package:greenmedia/screens/meta_connect_screen.dart';
import 'package:greenmedia/screens/my_plan_screen.dart';
import 'package:greenmedia/screens/owner_settings_screen.dart';
import 'package:greenmedia/screens/owner_report_screen.dart';
import 'package:greenmedia/screens/owner_reviews_screen.dart';
import 'package:greenmedia/screens/phone_login_screen.dart' show OtpBoxes;
import 'package:greenmedia/screens/reviews_screen.dart';
import 'package:greenmedia/state/session.dart';
import 'package:greenmedia/widgets/common.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';
import 'package:http/testing.dart';
import 'package:provider/provider.dart';

// Fixtures are real responses captured from the FastAPI backend, so these tests also guard the API contract.
Object fixture(String name) => jsonDecode(File('test/fixtures/$name.json').readAsStringSync()) as Object;

class MemoryStore implements SessionStore {
  String? token, url;
  @override
  Future<String?> readToken() async => token;
  @override
  Future<void> writeToken(String? t) async => token = t;
  @override
  Future<String?> readBaseUrl() async => url;
  @override
  Future<void> writeBaseUrl(String u) async => url = u;
}

/// Request bodies the fake backend received, by route name.
final sentBodies = <String, Object?>{};

/// Which Google Post list the fake backend returns.
var googlePostsFixture = 'google_posts_client';

/// The fake backend has no Google Media yet.
var googleMediaEmpty = false;

/// The fake monthly report has no score history.
var reportNoScore = false;

/// The fake plan has been paid for.
var planPaid = false;

/// The fake backend uses Razorpay test keys (rzp_test_…).
var planRazorpayTest = false;

/// The person's Analytics & Personalisation choice on the fake backend.
var analyticsOn = false;

/// The fake Preference as saved so far (null: as captured).
Map<String, dynamic>? prefState;

/// Fake backend: `who` is decided by the login email.
MockClient fakeApi(List<String> calls) {
  var who = 'admin', videoPolls = 0;
  return MockClient((req) async {
    calls.add('${req.method} ${req.url.path}');
    http.Response json(Object body, [int status = 200]) =>
        http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});
    switch (req.url.path) {
      case '/api/auth/otp/request':
        final digits = ((jsonDecode(req.body) as Map)['phone'] as String).replaceAll(RegExp(r'\D'), '');
        final phone = '+91$digits';
        // 9111111111: the SMS gateway refuses; 9222222222: a real SMS went out (no demo code in the answer)
        if (digits == '9111111111') return json({'detail': "Couldn't send the SMS: MSG91: Invalid template"}, 502);
        if (digits == '9222222222') {
          return json({...(fixture('otp_request') as Map)..remove('dev_code'), 'phone': phone, 'masked': '+919222••••22'});
        }
        return json({...fixture('otp_request') as Map, 'phone': phone, 'masked': '${phone.substring(0, phone.length - 6)}••••${phone.substring(phone.length - 2)}'});
      case '/api/auth/otp/verify':
        final b = jsonDecode(req.body) as Map;
        if (b['code'] != '123456') return json({'detail': 'Incorrect code — 4 attempts left'}, 400);
        return json(fixture(b['phone'] == '+919000000001' ? 'otp_verify_admin' : 'otp_verify_owner'));
      case '/api/auth/otp/select':
        final b = jsonDecode(req.body) as Map;
        who = b['otp_token'] == 'otp-token-admin' ? 'admin' : 'client';
        return json(fixture('login_$who'));
      case '/api/dashboard':
        return json(fixture('dashboard_$who'));
      case '/api/reviews':
        // the owner's Review Replies screen asks for one business
        return json(fixture(who == 'client' && req.url.queryParameters.containsKey('client_id') ? 'reviews_owner_all' : 'reviews_$who'));
      case '/api/reviews/summary':
        return json(fixture('reviews_summary_client'));
      case '/api/clients/1/reply-settings':
        if (req.method == 'PUT') {
          final saved = fixture('reply_settings_client') as Map<String, dynamic>;
          return json({...saved, 'settings': jsonDecode(req.body)});
        }
        return json(fixture('reply_settings_client'));
      case '/api/clients':
        return json(fixture('clients_admin'));
      case '/api/content':
        return json(fixture('content_admin'));
      case '/api/clients/1/score':
        return json(fixture('score_client'));
      case '/api/clients/1/score/report-link':
        return json({'url': 'http://api.test/api/clients/1/score/report?t=x', 'expires_at': '2026-10-15T10:00:00Z'});
      case '/api/clients/1/performance':
        final p = fixture('performance_client') as Map<String, dynamic>;
        return json({...p, 'days': int.parse(req.url.queryParameters['days'] ?? '30')});
      case '/api/clients/1/calendar':
        return json(fixture('calendar_client'));
      case '/api/clients/1/keyword-planner':
        return json(fixture('keyword_planner_client'));
      case '/api/clients/1/keyword-planner/search':
        return json(fixture('keyword_search_client'));
      case '/api/clients/1/keyword-planner/keywords':
        final b = jsonDecode(req.body) as Map;
        return json({'id': 999, 'keyword': b['keyword'], 'location': b['location'], 'volume': b['volume']}, 201);
    }
    if (req.method == 'DELETE' && req.url.path.startsWith('/api/clients/1/keyword-planner/keywords/')) return http.Response('', 204);
    final post = RegExp(r'^/api/reviews/(\d+)/post$').firstMatch(req.url.path);
    if (post != null) {
      final id = int.parse(post.group(1)!);
      final item = ((fixture('reviews_owner_all') as Map)['items'] as List).cast<Map<String, dynamic>>().firstWhere((r) => r['id'] == id);
      final wasPublished = item['reply_status'] == 'published';
      return json({...item, 'reply': (jsonDecode(req.body) as Map)['reply'], 'reply_status': 'published', 'posted': true,
        'message': wasPublished ? 'Reply updated successfully' : 'Reply posted'});
    }
    if (req.method == 'DELETE' && RegExp(r'^/api/reviews/\d+/reply$').hasMatch(req.url.path)) return json({'reply_status': 'new'});
    // Settings (fixtures captured from the real API)
    switch ((req.method, req.url.path)) {
      case ('GET', '/api/auth/me'):
        final u = (fixture('login_$who') as Map)['user'] as Map<String, dynamic>;
        return json({...u, 'prefs': {'analytics': analyticsOn}});
      case ('PUT', '/api/auth/prefs'):
        analyticsOn = (jsonDecode(req.body) as Map)['analytics'] == true;
        return json({'prefs': {'analytics': analyticsOn}});
      case ('GET', '/api/auth/profiles'):
        return json(fixture('profiles_client'));
      case ('POST', '/api/auth/switch'):
        sentBodies['switch'] = jsonDecode(req.body);
        return json(fixture('switch_client'));
      case ('POST', '/api/auth/delete-account'):
        sentBodies['delete-account'] = jsonDecode(req.body);
        return json({'deleted': true});
      case ('GET', '/api/clients/1/settings'):
        return json(fixture('settings_client'));
      case ('GET', '/api/clients/1/preference'):
        return json(prefState ??= fixture('preference_client') as Map<String, dynamic>);
      case ('PATCH', '/api/clients/1/preference'):
        final b = jsonDecode(req.body) as Map<String, dynamic>;
        ((sentBodies['preference'] ??= <Map<String, dynamic>>[]) as List).add(b);
        final st = prefState ??= fixture('preference_client') as Map<String, dynamic>;
        final values = st['values'] as Map<String, dynamic>;
        for (final e in b.entries) {
          values[e.key] = e.value is Map ? {...values[e.key] as Map, ...e.value as Map} : e.value;
        }
        return json(st);
      case ('POST', '/api/clients/1/preference/photos/logo'):
        sentBodies['pref-photo'] = latin1.decode(req.bodyBytes, allowInvalid: true);
        return json(prefState = fixture('preference_logo') as Map<String, dynamic>);
      case ('DELETE', '/api/clients/1/preference/photos/logo'):
        sentBodies['pref-photo'] = 'deleted';
        return json(prefState = fixture('preference_client') as Map<String, dynamic>);
      case ('GET', '/api/legal/ai'):
        return json(fixture('legal_ai'));
      case ('GET', '/api/clients/1/qrs'):
        return json(fixture('qrs_client'));
      case ('POST', '/api/clients/1/qrs'):
        return json(fixture('qr_created'), 201);
      case ('POST', '/api/clients/1/qrs/claim'):
        sentBodies['claim'] = jsonDecode(req.body);
        return json(fixture('qr_claimed'));
      case ('GET', '/api/clients/1/refunds'):
        return json(fixture('refunds_client'));
      case ('POST', '/api/clients/1/refunds'):
        sentBodies['refund'] = jsonDecode(req.body);
        return json({'id': 1, 'payment_id': (jsonDecode(req.body) as Map)['payment_id'], 'status': 'open'}, 201);
      case ('GET', '/api/legal/privacy'):
        return json(fixture('legal_privacy'));
      case ('GET', '/api/legal/terms'):
        return json(fixture('legal_terms'));
    }
    if (req.method == 'POST' && RegExp(r'^/api/clients/1/qrs/\d+/link$').hasMatch(req.url.path)) return json(fixture('qr_link'));
    // My Plan (fixtures captured from the real API)
    switch ((req.method, req.url.path)) {
      case ('GET', '/api/clients/1/plan'):
        final plan = fixture(planPaid ? 'plan_client_active' : 'plan_client') as Map<String, dynamic>;
        return json(planRazorpayTest ? {...plan, 'payments_mode': 'live', 'payments_test': true} : plan);
      case ('PUT', '/api/clients/1/plan/billing'):
        sentBodies['plan-billing'] = jsonDecode(req.body);
        return json(fixture('plan_billing'));
      case ('POST', '/api/clients/1/plan/quote'):
        final b = jsonDecode(req.body) as Map;
        if ((b['coupon'] as String).toUpperCase() != 'WELCOME10') return json({'detail': "That coupon code isn't valid"}, 422);
        return json(fixture('plan_quote_coupon'));
      case ('POST', '/api/clients/1/plan/checkout'):
        sentBodies['plan-checkout'] = jsonDecode(req.body);
        return json(fixture('plan_checkout'), 201);
      case ('GET', '/api/clients/1/plan/payments/1'):
        planPaid = true;  // Razorpay (here: the practice page) confirmed it
        return json(fixture('plan_payment_paid'));
    }
    // Monthly report (fixtures captured from the real API)
    if (req.url.path == '/api/clients/1/monthly-report') {
      sentBodies['report-month'] = req.url.queryParameters['month'];
      final r = fixture('monthly_report_client') as Map<String, dynamic>;
      if (reportNoScore) {
        for (final t in (r['trends'] as List).cast<Map<String, dynamic>>().where((t) => t['key'] == 'score')) {
          for (final p in (t['points'] as List).cast<Map<String, dynamic>>()) {
            p['value'] = null;
          }
        }
      }
      return json(r);
    }
    if (req.url.path == '/api/clients/1/monthly-report/link') return json(fixture('monthly_report_link'));
    // Google Media (fixtures captured from the real API)
    if (req.url.path == '/api/google-media/categories') return json(fixture('google_media_categories'));
    if (req.url.path == '/api/clients/1/google-media') {
      if (req.method == 'POST') {
        ((sentBodies['gm-upload'] ??= <String>[]) as List<String>).add(latin1.decode(req.bodyBytes, allowInvalid: true));
        return json(fixture('google_media_added'), 201);
      }
      return json(fixture(googleMediaEmpty ? 'google_media_empty' : 'google_media_${req.url.queryParameters['tab'] ?? 'scheduled'}'));
    }
    final gmAct = RegExp(r'^/api/clients/1/google-media/(\d+)(/approve|/retry)?$').firstMatch(req.url.path);
    if (gmAct != null) {
      if (req.method == 'DELETE') return http.Response('', 204);
      final item = (fixture('google_media_added') as Map<String, dynamic>);
      return json({...item, 'id': int.parse(gmAct.group(1)!), 'status': 'scheduled', 'needs_approval': false});
    }
    // Google Post (fixtures captured from the real API)
    switch ((req.method, req.url.path)) {
      case ('GET', '/api/clients/1/google-posts'):
        return json(fixture(googlePostsFixture));
      case ('PUT', '/api/clients/1/google-posts/settings'):
        sentBodies['gp-settings'] = jsonDecode(req.body);
        return json(fixture('google_posts_auto'));
      case ('POST', '/api/clients/1/google-posts/generate'):
        return json(fixture('google_post_generated'), 201);
    }
    final gpEdit = RegExp(r'^/api/clients/1/google-posts/(\d+)$').firstMatch(req.url.path);
    if (req.method == 'PATCH' && gpEdit != null) {
      sentBodies['gp-edit'] = jsonDecode(req.body);
      return json({...fixture('google_post_generated') as Map, 'id': int.parse(gpEdit.group(1)!), 'text': (jsonDecode(req.body) as Map)['text']});
    }
    // AI Post (fixtures captured from the real API)
    const ai = '/api/clients/1/ai-posts';
    final videoId = (fixture('ai_post_video') as Map)['id'];
    switch ((req.method, req.url.path)) {
      case ('GET', '/api/video-templates'):
        return json(fixture('video_templates'));
      case ('GET', '/api/clients/1/items'):
        return json(fixture('items_client'));
      case ('POST', '/api/clients/1/items'):
        return json(((fixture('items_client') as Map)['items'] as List).first as Object, 201);
      case ('GET', '$ai/overview'):
        return json(fixture('ai_posts_overview'));
      case ('GET', ai):
        final tab = req.url.queryParameters['tab'];
        if (tab == 'pending' || tab == 'approved') return json(fixture('ai_posts_$tab'));
        return json({'tab': tab, 'period': req.url.queryParameters['period'], 'items': []});
      case ('GET', '$ai/free-slot'):
        return json(fixture('ai_post_free_slot'));
      case ('POST', '$ai/video'):
        return json(fixture('ai_post_video_generating'), 201);
      case ('POST', '$ai/poster'):
        return json(fixture('ai_post_poster'), 201);
    }
    final aiPost = RegExp('^$ai/(\\d+)(/approve|/reject)?\$').firstMatch(req.url.path);
    if (aiPost != null) {
      final id = int.parse(aiPost.group(1)!);
      if (aiPost.group(2) == '/approve') sentBodies['approve'] = jsonDecode(req.body);
      if (aiPost.group(2) == '/approve') return json({...fixture('ai_post_approved') as Map, 'id': id});
      if (aiPost.group(2) == '/reject') return json({...fixture('ai_post_poster') as Map, 'id': id, 'status': 'rejected', 'group': 'rejected'});
      // the video is still rendering on the first poll
      if (id == videoId) return json(fixture(videoPolls++ == 0 ? 'ai_post_video_generating' : 'ai_post_video'));
      return json(fixture('ai_post_poster'));
    }
    // Connect Facebook / Instagram from the app
    const accounts = [{'platform': 'facebook', 'is_live': true}, {'platform': 'instagram', 'is_live': true}];
    switch ((req.method, req.url.path)) {
      case ('POST', '/api/clients/1/meta/connect'):
        return json({'id': 'att1', 'auth_url': 'https://www.facebook.com/dialog/oauth?state=x'}, 201);
      case ('GET', '/api/clients/1/meta/connect/att1'):
        return json({'id': 'att1', 'status': 'choose_page', 'reason': '', 'message': '', 'accounts': [], 'candidates': [
          {'page_id': 'P1', 'name': 'Smile Dental Studio', 'instagram': 'smiledental.pune'},
          {'page_id': 'P2', 'name': 'Smile Dental Kids', 'instagram': null},
        ]});
      case ('POST', '/api/clients/1/meta/connect/att1/choose'):
        return json({'id': 'att1', 'status': 'connected', 'reason': '', 'message': '', 'candidates': [], 'accounts': accounts});
      case ('POST', '/api/clients/1/meta/connect/att1/cancel'):
        return json({'id': 'att1', 'status': 'failed', 'reason': 'cancelled', 'message': 'The Facebook screen closed before the connection was saved.',
          'candidates': [], 'accounts': []});
    }
    return json({'detail': 'not found'}, 404);
  });
}

Future<Session> pumpApp(WidgetTester tester, List<String> calls) async {
  final session = Session(store: MemoryStore(), api: ApiClient(baseUrl: 'http://api.test', httpClient: fakeApi(calls)));
  await session.restore();
  await tester.binding.setSurfaceSize(const Size(420, 900));
  await tester.pumpWidget(GreenMediaApp(session: session));
  await tester.pumpAndSettle();
  return session;
}

Future<void> requestCode(WidgetTester tester, String phone) async {
  await tester.enterText(find.byKey(const Key('phone')), phone);
  await tester.pump();
  await tester.tap(find.text('Get OTP'));
  await tester.pumpAndSettle();
}

/// Everyone signs in with their mobile number: the demo owner (two businesses, opens Smile Dental) or the agency admin.
Future<void> signIn(WidgetTester tester, String who) async {
  final owner = who.startsWith('anjali');
  await requestCode(tester, owner ? '9876543210' : '9000000001');
  await tester.enterText(find.byKey(const Key('otp')), '123456');
  await tester.pumpAndSettle();
  if (owner) {
    await tester.tap(find.text('Smile Dental Studio'));
    await tester.pumpAndSettle();
  }
}

void main() {
  group('phone OTP sign-in', () {
    testWidgets('Get OTP is enabled only for a valid mobile number', (tester) async {
      await pumpApp(tester, []);
      expect(find.text('Enter your\nphone number'), findsOneWidget);
      Opacity button() => tester.widget<Opacity>(find.ancestor(of: find.text('Get OTP'), matching: find.byType(Opacity)).first);
      expect(button().opacity, lessThan(1));
      await tester.enterText(find.byKey(const Key('phone')), '5876543210'); // Indian mobiles start 6-9
      await tester.pump();
      expect(button().opacity, lessThan(1));
      await tester.enterText(find.byKey(const Key('phone')), '98765abc43210'); // letters are filtered out
      await tester.pump();
      expect(button().opacity, 1);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
    });

    testWidgets('owner of two businesses: code → choose profile → home', (tester) async {
      final calls = <String>[];
      final session = await pumpApp(tester, calls);
      await requestCode(tester, '9876543210');
      expect(find.text('Verify your\nmobile number'), findsOneWidget);
      expect(find.text('Code sent to +919876••••10'), findsOneWidget);
      expect(find.text('00:30'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('otp')), '999999');
      await tester.pumpAndSettle();
      expect(find.textContaining('Incorrect code'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('otp')), '123456'); // verifies automatically when complete
      await tester.pumpAndSettle();
      expect(find.text('Select profile'), findsOneWidget);
      expect(find.text('Smile Dental Studio'), findsOneWidget);
      expect(find.text('GlowUp Salon & Spa'), findsOneWidget);
      expect(find.text('Needs Google'), findsOneWidget);

      await tester.tap(find.text('Smile Dental Studio'));
      await tester.pumpAndSettle();
      expect(session.signedIn, isTrue);
      expect(session.me!.isClient, isTrue);
      expect(calls, containsAllInOrder(['POST /api/auth/otp/request', 'POST /api/auth/otp/verify', 'POST /api/auth/otp/select', 'GET /api/clients/1/score']));
    });

    testWidgets('the number screen has no email sign-in or server line', (tester) async {
      await pumpApp(tester, []);
      expect(find.textContaining('Sign in with email'), findsNothing);
      expect(find.textContaining('Server:'), findsNothing);
    });

    testWidgets('a single profile opens straight away; demo code chip fills the code', (tester) async {
      final session = await pumpApp(tester, []);
      await requestCode(tester, '9000000001');
      await tester.tap(find.text('Demo server — code 123456'));
      await tester.pumpAndSettle();
      expect(session.signedIn, isTrue);
      expect(session.me!.role, 'admin');
    });

    testWidgets('code sent by SMS: no demo chip; a refused SMS shows why', (tester) async {
      await pumpApp(tester, []);
      await requestCode(tester, '9111111111');
      expect(find.text("Couldn't send the SMS: MSG91: Invalid template"), findsOneWidget);
      expect(find.text('Enter your\nphone number'), findsOneWidget);
      await requestCode(tester, '9222222222');
      expect(find.text('Code sent to +919222••••22'), findsOneWidget);
      expect(find.textContaining('Demo server'), findsNothing);
      expect(tester.widget<TextField>(find.byKey(const Key('otp'))).autofillHints, contains(AutofillHints.oneTimeCode));
    });

    testWidgets('six code boxes fit a small phone', (tester) async {
      await pumpApp(tester, []);
      await tester.binding.setSurfaceSize(const Size(320, 640));
      await tester.pumpAndSettle();
      await requestCode(tester, '9876543210');
      expect(tester.takeException(), isNull); // no overflow
      final boxes = find.descendant(of: find.byType(OtpBoxes), matching: find.byType(Container));
      expect(boxes, findsNWidgets(6));
      expect(tester.getTopRight(boxes.last).dx, lessThanOrEqualTo(320));
      await tester.binding.setSurfaceSize(const Size(420, 900));
    });

    testWidgets('back from the code step returns to the number', (tester) async {
      await pumpApp(tester, []);
      await requestCode(tester, '9876543210');
      await tester.tap(find.byTooltip('Back'));
      await tester.pumpAndSettle();
      expect(find.text('Enter your\nphone number'), findsOneWidget);
    });
  });

  testWidgets('admin signs in and sees the agency dashboard', (tester) async {
    final calls = <String>[];
    final session = await pumpApp(tester, calls);
    await signIn(tester, 'admin@greenmedia.in');
    expect(session.me!.role, 'admin');
    expect(calls, containsAllInOrder(['POST /api/auth/otp/verify', 'GET /api/dashboard']));
    expect(find.textContaining('Good '), findsOneWidget);
    expect(find.text('Active clients'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Client performance'), 300, scrollable: find.byType(Scrollable).first);
    expect(find.text('Client performance'), findsOneWidget);
    // Staff bottom navigation
    for (final tab in ['Home', 'Reviews', 'Content', 'Calendar', 'More']) {
      expect(find.descendant(of: find.byType(NavigationBar), matching: find.text(tab)), findsOneWidget);
    }
  });

  testWidgets('client-portal user gets a client-only experience', (tester) async {
    final calls = <String>[];
    await pumpApp(tester, calls);
    await signIn(tester, 'anjali@smiledental.in');
    expect(find.text('Active clients'), findsNothing);
    expect(calls, contains('GET /api/clients/1/score'));
    expect(calls, isNot(contains('GET /api/dashboard')));
    final nav = find.byType(NavigationBar);
    expect(find.descendant(of: nav, matching: find.text('Calendar')), findsNothing);
    // owners get Dhanda's five tabs; Analytics, Reports and Settings open from their avatar on Home
    for (final tab in ['Home', 'Replies', 'AI Post', 'Google Post', 'Google Media']) {
      expect(find.descendant(of: nav, matching: find.text(tab)), findsOneWidget);
    }
    expect(find.descendant(of: nav, matching: find.text('More')), findsNothing);
    await tester.tap(find.byKey(const Key('owner-menu')));
    await tester.pumpAndSettle();
    for (final item in ['Analytics', 'Report', 'Settings', 'Sign out']) {
      expect(find.text(item), findsOneWidget);
    }
  });

  group('owner home', () {
    final score = fixture('score_client') as Map<String, dynamic>;

    // scroll until visible, then bring it to the top so the floating Growth Action pill doesn't cover it
    Future<void> scrollTo(WidgetTester tester, Finder f) async {
      await tester.scrollUntilVisible(f, 300, scrollable: find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first);
      await tester.ensureVisible(f);
      await tester.pumpAndSettle();
    }

    testWidgets('top bar, score carousel and Growth Action come from the API', (tester) async {
      final calls = <String>[];
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      expect(find.text('Smile Dental Studio'), findsWidgets);
      expect(find.text('Help'), findsOneWidget);
      expect(find.byKey(const Key('score-value')), findsOneWidget);
      expect(find.text('${(score['score'] as Map)['value']}%'), findsOneWidget);
      expect(calls, containsAll(['GET /api/clients/1/score', 'GET /api/clients/1/performance', 'GET /api/clients/1/calendar']));
      // owner wording in the bottom bar
      final nav = find.byType(NavigationBar);
      for (final tab in ['Home', 'Replies', 'AI Post']) {
        expect(find.descendant(of: nav, matching: find.text(tab)), findsOneWidget);
      }
      // carousel: growth this week, then the tracker
      await tester.drag(find.byType(PageView), const Offset(-400, 0));
      await tester.pumpAndSettle();
      expect(find.text('Growth in Marketing Score'), findsOneWidget);
      await tester.drag(find.byType(PageView), const Offset(-400, 0));
      await tester.pumpAndSettle();
      expect(find.text('Marketing Tracker'), findsOneWidget);
      expect(find.text((score['tracker'] as Map)['headline'] as String), findsOneWidget);
      // Growth Action checklist
      final actions = (score['actions'] as List).cast<Map>();
      final done = actions.where((a) => a['done'] == true).length;
      expect(find.text('$done of 10 done · ${10 - done} left'), findsOneWidget);
      await tester.tap(find.byKey(const Key('growth-action')));
      await tester.pumpAndSettle();
      expect(find.text('Complete your profile'), findsOneWidget);
      expect(find.text('Approve posts'), findsOneWidget);
    });

    testWidgets('improve score opens the breakdown with tips', (tester) async {
      await pumpApp(tester, []);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.text('Improve Marketing Score'));
      await tester.pumpAndSettle();
      expect(find.text('Your score: ${(score['score'] as Map)['value']} / 100'), findsOneWidget);
      expect(find.textContaining('Tip: '), findsWidgets);
    });

    testWidgets('performance filter, calendar months, keywords and competitors', (tester) async {
      final calls = <String>[];
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      expect(find.text("Google's Performance"), findsOneWidget);
      await tester.tap(find.byKey(const Key('perf-days')));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(CheckedPopupMenuItem<int>).last);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('perf-days')), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('perf-days'))).data, '120 Days');

      await scrollTo(tester, find.byKey(const Key('cal-month')));
      final month = tester.widget<Text>(find.byKey(const Key('cal-month'))).data;
      await tester.tap(find.byTooltip('Next month'));
      await tester.pumpAndSettle();
      expect(tester.widget<Text>(find.byKey(const Key('cal-month'))).data, isNot(month));

      final tracked = (score['tracked_keywords'] as List).first as Map;
      await scrollTo(tester, find.text(tracked['keyword'] as String));
      await scrollTo(tester, find.text('Competitor Analysis'));
      expect(find.textContaining('LOCAL COMPETITORS'), findsOneWidget);
      await scrollTo(tester, find.text('Smile Dental Studio (you)'));
      await scrollTo(tester, find.text('Stay active on Social Media'));
      expect(find.text('Facebook'), findsOneWidget);
    });

    testWidgets('keyword planner: search, add and remove', (tester) async {
      final calls = <String>[];
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await scrollTo(tester, find.text('Access Keyword Planner'));
      await tester.tap(find.text('Access Keyword Planner'));
      await tester.pumpAndSettle();
      expect(find.text('Keyword Planner'), findsOneWidget);
      final kp = fixture('keyword_planner_client') as Map<String, dynamic>;
      expect(find.text((kp['tracked'] as List).first['keyword'] as String), findsOneWidget);
      await tester.enterText(find.byKey(const Key('kp-keyword')), 'dental implants');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();
      final search = fixture('keyword_search_client') as Map<String, dynamic>;
      final credits = search['credits'] as Map;
      expect(tester.widget<Text>(find.byKey(const Key('kp-credits'))).data, '${credits['used']} / ${credits['limit']}');
      final results = (search['results'] as List).cast<Map>();
      final i = results.indexWhere((r) => !(kp['tracked'] as List).any((t) => (t as Map)['keyword'] == r['keyword']));
      final row = find.text('${i + 1}. ${results[i]['keyword']}');
      await tester.scrollUntilVisible(row, 200, scrollable: find.descendant(of: find.byType(ListView).last, matching: find.byType(Scrollable)).first);
      final card = find.ancestor(of: row, matching: find.byType(Card)).first;
      await tester.tap(find.descendant(of: card, matching: find.text('ADD')));
      await tester.pumpAndSettle();
      expect(calls, contains('POST /api/clients/1/keyword-planner/keywords'));
      expect(find.descendant(of: card, matching: find.text('ADDED')), findsOneWidget);
    });
  });

  group('owner home: help and social connect', () {
    final score = fixture('score_client') as Map<String, dynamic>;

    Future<void> openSocial(WidgetTester tester) async {
      await tester.scrollUntilVisible(find.text('Stay active on Social Media'), 300,
          scrollable: find.descendant(of: find.byType(ListView), matching: find.byType(Scrollable)).first);
      await tester.ensureVisible(find.text('Stay active on Social Media'));
      await tester.pumpAndSettle();
    }

    testWidgets('Help opens a popup to call or WhatsApp the account manager', (tester) async {
      await pumpApp(tester, []);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.text('Help'));
      await tester.pumpAndSettle();
      expect(find.text('Talk to ${(score['support'] as Map)['name']}'), findsOneWidget);
      expect(find.text('Chat on WhatsApp'), findsOneWidget);
      await tester.tap(find.byTooltip('Close'));
      await tester.pumpAndSettle();
      expect(find.text('Chat on WhatsApp'), findsNothing);
    });

    testWidgets('Connect: Taking you to Facebook → pick the Page → connected', (tester) async {
      final opened = <Uri>[];
      MetaConnectScreen.openUrl = (u) async {
        opened.add(u);
        return true;
      };
      final calls = <String>[];
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await openSocial(tester);
      final connect = find.byWidgetPredicate((w) => w is TextButton && (w.key as ValueKey?)?.value.toString().startsWith('connect-') == true);
      expect(connect, findsWidgets);
      await tester.tap(connect.first);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400)); // page transition
      expect(find.byKey(const Key('meta-intro')), findsOneWidget);
      await tester.pump(const Duration(seconds: 1)); // opens Facebook's login
      expect(opened.single.host, 'www.facebook.com');
      await tester.pump(const Duration(seconds: 2)); // first poll: several Pages
      await tester.pump();
      expect(find.text('Which Page is your business?'), findsOneWidget);
      await tester.tap(find.text('Smile Dental Kids'));
      await tester.pumpAndSettle();
      expect(calls, contains('POST /api/clients/1/meta/connect/att1/choose'));
      expect(find.byType(MetaConnectScreen), findsNothing);
      expect(find.textContaining('connected'), findsWidgets);
    });

    testWidgets('Connect: login not finished → explains and offers Connect again', (tester) async {
      MetaConnectScreen.openUrl = (u) async => false; // the phone couldn't open Facebook
      await pumpApp(tester, []);
      await signIn(tester, 'anjali@smiledental.in');
      await openSocial(tester);
      await tester.tap(find.byWidgetPredicate((w) => w is TextButton && (w.key as ValueKey?)?.value.toString().startsWith('connect-') == true).first);
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();
      expect(find.textContaining('login failed'), findsOneWidget);
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('meta-failed')), findsOneWidget);
      expect(find.text('Allow every permission it asks for'), findsOneWidget);
      expect(find.textContaining('again'), findsWidgets);
      await tester.tap(find.text('Show me step by step'));
      await tester.pumpAndSettle();
      expect(find.textContaining('step by step'), findsWidgets);
    });
  });

  group('owner review replies', () {
    final reviews = ((fixture('reviews_owner_all') as Map)['items'] as List).cast<Map<String, dynamic>>();

    Future<void> openReplies(WidgetTester tester, List<String> calls) async {
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Replies')));
      await tester.pumpAndSettle();
    }

    Finder inList(Finder f) => f;
    Future<void> scrollTo(WidgetTester tester, Finder f) async {
      await tester.scrollUntilVisible(f, 250, scrollable: find.descendant(of: find.byType(OwnerReviewsScreen), matching: find.byType(Scrollable)).first);
      await tester.ensureVisible(f);
      await tester.pumpAndSettle();
    }

    testWidgets('trend, tabs, keywords used and the reply with keywords in bold', (tester) async {
      final calls = <String>[];
      await openReplies(tester, calls);
      expect(find.text('Review Replies'), findsOneWidget);
      expect(find.text('Reviews Trend'), findsOneWidget);
      expect(calls, containsAll(['GET /api/reviews/summary', 'GET /api/reviews']));
      final counts = (fixture('reviews_summary_client') as Map)['counts'] as Map;
      expect(find.text('All (${counts['all']})'), findsOneWidget);
      expect(find.text('Replied (${counts['replied']})'), findsOneWidget);
      final withKw = reviews.firstWhere((r) => (r['keywords_used'] as List).isNotEmpty);
      await scrollTo(tester, inList(find.byKey(Key('keywords-${withKw['id']}'))));
      expect(find.text('Keyword Used'), findsWidgets);
      expect(find.text(((withKw['keywords_used'] as List).first as Map)['keyword'] as String), findsOneWidget);
      final rich = tester.widget<RichText>(find.descendant(of: find.byKey(Key('reply-${withKw['id']}')), matching: find.byType(RichText)));
      final bold = <String>[];
      rich.text.visitChildren((s) {
        if (s is TextSpan && s.style?.fontWeight == FontWeight.w800) bold.add(s.text!.toLowerCase());
        return true;
      });
      expect(bold, containsAll(['dental', 'clinic']));
      // switch to Pending
      await tester.drag(find.byType(ListView).first, const Offset(0, 3000));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('tab-pending')));
      await tester.pumpAndSettle();
      expect(calls.where((c) => c == 'GET /api/reviews').length, greaterThan(1));
    });

    testWidgets('write a reply and post it; edit a posted reply', (tester) async {
      final calls = <String>[];
      await openReplies(tester, calls);
      final pending = reviews.firstWhere((r) => r['reply'] == null && (r['rating'] as int) >= 3);
      final card = find.byKey(ValueKey(pending['id']));
      await scrollTo(tester, find.descendant(of: card, matching: find.text('Write reply')));
      await tester.tap(find.descendant(of: card, matching: find.text('Write reply')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(Key('reply-editor-${pending['id']}')), 'Thank you for visiting our dental clinic!');
      await tester.tap(find.byKey(Key('save-${pending['id']}')));
      await tester.pumpAndSettle();
      expect(calls, contains('POST /api/reviews/${pending['id']}/post'));
      expect(find.text('Reply posted'), findsOneWidget);

      final posted = reviews.firstWhere((r) => r['reply_status'] == 'published');
      final pc = find.byKey(ValueKey(posted['id']));
      await scrollTo(tester, find.descendant(of: pc, matching: find.byTooltip('Edit reply')));
      await tester.tap(find.descendant(of: pc, matching: find.byTooltip('Edit reply')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key('save-${posted['id']}')));
      await tester.pumpAndSettle();
      expect(find.text('Reply updated successfully'), findsOneWidget);
    });

    testWidgets('Reply Settings: category, length, language search and save', (tester) async {
      final calls = <String>[];
      await openReplies(tester, calls);
      await tester.tap(find.byKey(const Key('reply-settings')));
      await tester.pumpAndSettle();
      expect(find.text('Reply Settings'), findsOneWidget);
      expect(find.textContaining('in 24 hours'), findsOneWidget);
      await tester.tap(find.text('1-2 Stars'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('lang-hi')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('lang-hi')));
      await tester.pumpAndSettle();
      expect(tester.widget<Text>(find.byKey(const Key('sample-reply'))).data, contains('खेद'));
      await tester.ensureVisible(find.byKey(const Key('search-language')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('search-language')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('language-search')), 'tam');
      await tester.pumpAndSettle();
      await tester.tap(find.text('Tamil'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('lang-ta')), findsOneWidget);
      expect(find.textContaining('written in Tamil'), findsOneWidget);
      await tester.tap(find.byKey(const Key('reply-settings-save')));
      await tester.pumpAndSettle();
      expect(calls, contains('PUT /api/clients/1/reply-settings'));
      expect(find.text('Reply Settings'), findsNothing);
    });
  });

  group('owner AI post', () {
    Future<void> openAiPost(WidgetTester tester, List<String> calls) async {
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('AI Post')));
      await tester.pumpAndSettle();
    }

    Future<void> tapKey(WidgetTester tester, String key) async {
      await tester.ensureVisible(find.byKey(Key(key)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    testWidgets('quota, scheduled tabs, the post detail with its keywords', (tester) async {
      final calls = <String>[];
      await openAiPost(tester, calls);
      final q = (fixture('ai_posts_overview') as Map)['quota'] as Map;
      expect(find.text('Try Generating Viral Video'), findsOneWidget);
      expect(find.text('(${q['videos']['used']}/${q['videos']['limit']})'), findsOneWidget);
      expect(find.text('Generate AI Post (${q['posts']['used']}/${q['posts']['limit']})'), findsOneWidget);
      expect(calls, contains('GET /api/clients/1/ai-posts'));
      final pending = ((fixture('ai_posts_pending') as Map)['items'] as List).first as Map<String, dynamic>;
      expect(find.byKey(Key('post-${pending['id']}')), findsOneWidget);
      expect(find.text('Waiting for your approval'), findsWidgets);

      await tapKey(tester, 'seg-approved');
      final approved = ((fixture('ai_posts_approved') as Map)['items'] as List).first as Map<String, dynamic>;
      expect(find.byKey(Key('post-${approved['id']}')), findsOneWidget);
      expect(find.text('Approved for 18 Oct'), findsOneWidget);
      await tapKey(tester, 'seg-rejected');
      expect(find.byKey(Key('post-${approved['id']}')), findsNothing);
      await tapKey(tester, 'seg-posted');
      expect(find.text('00 Posts'), findsOneWidget);
      expect(find.text('Lifetime'), findsOneWidget);

      await tapKey(tester, 'seg-scheduled');
      await tapKey(tester, 'seg-pending');
      await tapKey(tester, 'post-${pending['id']}');
      expect(find.text('This post targets the following keywords'), findsOneWidget);
      final kw = (pending['keywords'] as List).first as Map;
      expect(find.descendant(of: find.byKey(const Key('targets-keywords')), matching: find.text(kw['keyword'] as String)), findsOneWidget);
      expect(find.textContaining('~${pending['estimated_views']}'), findsWidgets);
    });

    testWidgets('viral video: template, preview, generating, review, schedule', (tester) async {
      final calls = <String>[];
      await openAiPost(tester, calls);
      await tapKey(tester, 'viral-banner');
      expect(calls, contains('GET /api/video-templates'));
      await tapKey(tester, 'template-deal_alert');
      expect(find.text('Preview'), findsWidgets);
      await tester.ensureVisible(find.byKey(const Key('generate-video')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('generate-video')));
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(calls, contains('POST /api/clients/1/ai-posts/video'));
      expect(find.textContaining('Content Agent is creating'), findsOneWidget);
      expect(find.byKey(const Key('gen-step')), findsOneWidget);
      // the next poll finds the video ready
      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();
      expect(find.text('Your video is ready'), findsOneWidget);
      final video = fixture('ai_post_video') as Map<String, dynamic>;
      expect(tester.widget<Text>(find.byKey(const Key('review-caption'))).data, startsWith(video['caption'] as String));

      await tapKey(tester, 'approve-post');
      expect(find.text('Select Date & Time'), findsOneWidget);
      expect(calls, contains('GET /api/clients/1/ai-posts/free-slot'));
      // the suggested free slot is 7:00 AM India time, whatever the device's zone
      expect(find.text('Schedule for 18 October'), findsOneWidget);
      await tapKey(tester, 'schedule-post');
      expect(sentBodies['approve'], {'scheduled_at': '2026-10-18T01:30:00.000Z'});
      expect(calls, contains('POST /api/clients/1/ai-posts/${video['id']}/approve'));
      expect(find.byKey(const Key('scheduled-ok')), findsOneWidget);
      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scheduled-ok')), findsNothing);
    });

    testWidgets('generate AI post: add an item, then make a poster from it', (tester) async {
      final calls = <String>[];
      AddItemScreen.pickPhoto = () async => (base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='), 'p.png');
      await openAiPost(tester, calls);
      await tapKey(tester, 'generate-ai-post');
      expect(find.text('Select Item'), findsOneWidget);
      expect(find.text('Teeth Whitening'), findsOneWidget);

      await tapKey(tester, 'add-item');
      await tester.tap(find.byKey(const Key('save-item')));
      await tester.pumpAndSettle();
      expect(find.text('Add a photo and a name'), findsOneWidget);
      ScaffoldMessenger.of(tester.element(find.byKey(const Key('save-item')))).hideCurrentSnackBar();
      await tester.pumpAndSettle();
      await tapKey(tester, 'pick-photo');
      await tester.enterText(find.byKey(const Key('item-name')), 'Teeth Whitening');
      await tapKey(tester, 'save-item');
      expect(calls, contains('POST /api/clients/1/items'));
      expect(find.text('Select Item'), findsOneWidget);

      await tapKey(tester, 'item-1');
      expect(calls, contains('POST /api/clients/1/ai-posts/poster'));
      expect(find.text('Your post is ready'), findsOneWidget);
      await tester.tap(find.text('Reject Post'));
      await tester.pumpAndSettle();
      expect(calls, contains('POST /api/clients/1/ai-posts/${(fixture('ai_post_poster') as Map)['id']}/reject'));
      expect(find.text('Your post is ready'), findsNothing);
    });
  });

  group('owner Google Post', () {
    final gp = fixture('google_posts_client') as Map<String, dynamic>;
    final items = (gp['items'] as List).cast<Map<String, dynamic>>();
    final pending = items.firstWhere((p) => p['group'] == 'pending');
    final approved = items.firstWhere((p) => p['group'] == 'approved');

    Future<void> openGooglePost(WidgetTester tester, List<String> calls) async {
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Google Post')));
      await tester.pumpAndSettle();
    }

    Future<void> tapKey(WidgetTester tester, String key) async {
      await tester.ensureVisible(find.byKey(Key(key)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    testWidgets('keywords card, posts by status, approve, edit and reject', (tester) async {
      final calls = <String>[];
      await openGooglePost(tester, calls);
      expect(calls, contains('GET /api/clients/1/google-posts'));
      expect(find.text('Google works best with keywords'), findsOneWidget);
      expect(find.text(((gp['keywords'] as List).first as Map)['keyword'] as String), findsOneWidget);
      expect(find.text('+${(gp['keyword_count'] as int) - 3} more'), findsOneWidget);
      expect(find.text('WAITING FOR YOUR APPROVAL'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('SCHEDULED'), 200,
          scrollable: find.descendant(of: find.byType(GooglePostScreen), matching: find.byType(Scrollable)).first);
      expect(find.text('SCHEDULED'), findsOneWidget);
      expect(find.byKey(Key('gp-approve-${approved['id']}')), findsNothing);
      // the post's keyword words are highlighted in its text
      final rich = tester.widget<RichText>(find.descendant(of: find.byKey(Key('gp-text-${pending['id']}')), matching: find.byType(RichText)));
      final blue = <String>[];
      rich.text.visitChildren((s) {
        if (s is TextSpan && s.style?.color == const Color(0xFF1F63C6)) blue.add(s.text!.toLowerCase());
        return true;
      });
      expect(blue, [pending['keyword']]);  // the whole search phrase, not "Dental" in the business name

      await tapKey(tester, 'gp-approve-${pending['id']}');
      expect(calls, contains('POST /api/clients/1/ai-posts/${pending['id']}/approve'));
      expect(find.textContaining('Approved — it posts on'), findsOneWidget);
      ScaffoldMessenger.of(tester.element(find.byType(GooglePostScreen))).hideCurrentSnackBar();
      await tester.pumpAndSettle();

      await tapKey(tester, 'gp-edit-${pending['id']}');
      await tester.enterText(find.byKey(const Key('gp-edit-text')), 'Looking for a dental clinic near me in Pune? Call Smile Dental Studio.');
      await tapKey(tester, 'gp-edit-save');
      expect(sentBodies['gp-edit'], {'text': 'Looking for a dental clinic near me in Pune? Call Smile Dental Studio.'});
      ScaffoldMessenger.of(tester.element(find.byType(GooglePostScreen))).hideCurrentSnackBar();
      await tester.pumpAndSettle();

      await tapKey(tester, 'gp-reject-${approved['id']}');
      expect(calls, contains('POST /api/clients/1/ai-posts/${approved['id']}/reject'));
    });

    testWidgets('post automatically asks first; write a post now; optimise keywords', (tester) async {
      final calls = <String>[];
      await openGooglePost(tester, calls);
      await tapKey(tester, 'gp-auto');
      expect(find.text('Post automatically?'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(calls, isNot(contains('PUT /api/clients/1/google-posts/settings')));
      await tapKey(tester, 'gp-auto');
      await tapKey(tester, 'gp-auto-confirm');
      expect(sentBodies['gp-settings'], {'auto': true});
      expect(find.textContaining('by Dr. Anjali Rao'), findsOneWidget);

      await tapKey(tester, 'gp-write-now');
      expect(calls, contains('POST /api/clients/1/google-posts/generate'));
      final made = fixture('google_post_generated') as Map;
      expect(find.textContaining('“${made['keyword']}”'), findsOneWidget);
      ScaffoldMessenger.of(tester.element(find.byType(GooglePostScreen))).hideCurrentSnackBar();
      await tester.pumpAndSettle();

      await tapKey(tester, 'optimise-keywords');
      expect(calls, contains('GET /api/clients/1/keyword-planner'));
      expect(find.text('Keyword Planner'), findsWidgets);
    });

    testWidgets('no posts yet', (tester) async {
      googlePostsFixture = 'google_posts_empty';
      addTearDown(() => googlePostsFixture = 'google_posts_client');
      await openGooglePost(tester, []);
      expect(find.text('No text posts yet'), findsOneWidget);
      expect(find.text('Text-only posts the Content Agent publishes for you will appear here.'), findsOneWidget);
    });
  });

  group('owner Google Media', () {
    const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

    Future<void> openMedia(WidgetTester tester, List<String> calls) async {
      sentBodies.remove('gm-upload');
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Google Media')));
      await tester.pumpAndSettle();
    }

    Future<void> tapKey(WidgetTester tester, String key) async {
      await tester.ensureVisible(find.byKey(Key(key)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    testWidgets('tabs with counts, where it uploads, what to upload, approve and retry', (tester) async {
      final calls = <String>[];
      await openMedia(tester, calls);
      expect(calls, containsAll(['GET /api/clients/1/google-media', 'GET /api/google-media/categories']));
      final sched = fixture('google_media_scheduled') as Map<String, dynamic>;
      expect(find.text('${sched['counts']['scheduled']} Media scheduled'), findsOneWidget);
      final pending = (sched['items'] as List).cast<Map<String, dynamic>>().firstWhere((m) => m['needs_approval'] == true);
      expect(find.text('Needs approval'), findsOneWidget);

      await tapKey(tester, 'where-it-uploads');
      expect(find.text('Fresh photos can get you up to 25% more calls', findRichText: true), findsOneWidget);
      expect(find.text('Smile Dental Studio'), findsWidgets);
      await tapKey(tester, 'got-it');

      await tester.tap(find.byTooltip('What to upload?'));
      await tester.pumpAndSettle();
      expect(find.text('Exterior Photos'), findsOneWidget);
      await tester.drag(find.byKey(const Key('what-carousel')), const Offset(-300, 0));
      await tester.pumpAndSettle();
      expect(find.text('Interior Photos'), findsOneWidget);
      await tapKey(tester, 'what-got-it');

      await tapKey(tester, 'gm-item-${pending['id']}');
      await tapKey(tester, 'gm-approve');
      expect(calls, contains('POST /api/clients/1/google-media/${pending['id']}/approve'));

      await tapKey(tester, 'gm-tab-uploaded');
      expect(find.text('1 Media uploaded'), findsOneWidget);
      await tapKey(tester, 'gm-tab-not_posted');
      final failed = ((fixture('google_media_not_posted') as Map)['items'] as List).first as Map;
      await tapKey(tester, 'gm-item-${failed['id']}');
      expect(find.textContaining('Image too blurry'), findsOneWidget);
      await tapKey(tester, 'gm-retry');
      expect(calls, contains('POST /api/clients/1/google-media/${failed['id']}/retry'));
    });

    testWidgets('upload from the gallery: category and one a day', (tester) async {
      GoogleMediaScreen.pickGallery = () async => [
            (bytes: base64Decode(png), name: 'front.png', video: false),
            (bytes: base64Decode(png), name: 'counter.png', video: false),
          ];
      final calls = <String>[];
      await openMedia(tester, calls);
      await tapKey(tester, 'upload-media');
      await tapKey(tester, 'open-gallery');
      expect(find.text('2 items selected'), findsOneWidget);
      await tapKey(tester, 'cat-PRODUCT');
      await tapKey(tester, 'gm-upload');
      final bodies = sentBodies['gm-upload'] as List<String>;
      expect(bodies, hasLength(2));
      expect(bodies.first, allOf(contains('PRODUCT'), contains('spread'), contains('front.png')));
      expect(find.text('2 items added — find them under Scheduled'), findsOneWidget);
    });

    testWidgets('record a video with the camera and post it now', (tester) async {
      GoogleMediaScreen.pickCamera = (video) async => (bytes: [0, 0, 0, 24], name: video ? 'clip.mp4' : 'photo.jpg', video: video);
      await openMedia(tester, []);
      await tapKey(tester, 'upload-media');
      await tapKey(tester, 'open-camera');
      await tapKey(tester, 'camera-video');
      expect(find.byIcon(Icons.videocam), findsOneWidget);
      await tapKey(tester, 'when-now');
      await tapKey(tester, 'gm-upload');
      expect((sentBodies['gm-upload'] as List<String>).single, allOf(contains('clip.mp4'), contains('now')));
    });

    testWidgets('nothing yet', (tester) async {
      googleMediaEmpty = true;
      addTearDown(() => googleMediaEmpty = false);
      await openMedia(tester, []);
      expect(find.text('0 Media scheduled'), findsOneWidget);
      expect(find.text('No Media Scheduled'), findsOneWidget);
      expect(find.text('Upload now to attract more customers'), findsOneWidget);
    });
  });

  group('owner Report', () {
    final report = fixture('monthly_report_client') as Map<String, dynamic>;

    Future<void> openReport(WidgetTester tester, List<String> calls) async {
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.byKey(const Key('owner-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Report'));
      await tester.pumpAndSettle();
    }

    Future<void> tapKey(WidgetTester tester, String key) async {
      await tester.ensureVisible(find.byKey(Key(key)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    testWidgets('summary against last month, growth actions and the performance trends', (tester) async {
      final calls = <String>[];
      await openReport(tester, calls);
      expect(calls, contains('GET /api/clients/1/monthly-report'));
      expect(find.textContaining('${report['month_label']} Performance Summary', findRichText: true), findsOneWidget);
      expect(find.textContaining('(vs ${report['previous_label']})', findRichText: true), findsOneWidget);
      final views = (report['summary'] as List).cast<Map<String, dynamic>>().first;
      expect(find.descendant(of: find.byKey(const Key('tile-views')), matching: find.text(NumberFormat.decimalPattern('en_IN').format(views['value']))),
          findsOneWidget);
      expect(find.byKey(const Key('tile-website')), findsOneWidget);
      // the tiles slide sideways with a mouse drag too (desktop and web)
      final before = tester.getTopLeft(find.byKey(const Key('tile-views'))).dx;
      await tester.drag(find.byKey(const Key('summary-scroll')), const Offset(-150, 0), kind: PointerDeviceKind.mouse);
      await tester.pumpAndSettle();
      expect(tester.getTopLeft(find.byKey(const Key('tile-views'))).dx, lessThan(before - 100));

      // Growth Action Report: weeks of last month, then 6 months
      expect(find.text('SEO Post Published'), findsOneWidget);
      expect(find.text('Last Month'), findsWidgets);
      await tapKey(tester, 'filter-posts');
      expect(find.text('Date Filters'), findsOneWidget);
      await tester.tap(find.text('Last 6 Months').last);
      await tester.pumpAndSettle();
      expect(find.text('Last 6 Months'), findsOneWidget);

      // Performance Report
      await tester.dragUntilVisible(find.byKey(const Key('tab-performance')), find.byKey(const Key('report-list')), const Offset(0, 300));
      await tapKey(tester, 'tab-performance');
      expect(find.text('Growth in Score'), findsOneWidget);
      final views12 = (report['trends'] as List).cast<Map<String, dynamic>>().firstWhere((t) => t['key'] == 'views');
      await tester.dragUntilVisible(find.byKey(const Key('insight-views')), find.byKey(const Key('report-list')), const Offset(0, -300));
      expect(find.text(views12['insight'] as String), findsOneWidget);
      await tapKey(tester, 'filter-views');
      await tester.tap(find.text('Last 12 Months').last);
      await tester.pumpAndSettle();
      expect(find.text('Last 12 Months'), findsOneWidget);
    });

    testWidgets('download the PDF and pick another month', (tester) async {
      Uri? opened;
      OwnerReportScreen.openUrl = (url) async {
        opened = url;
        return true;
      };
      final calls = <String>[];
      await openReport(tester, calls);
      await tester.tap(find.byKey(const Key('report-download')));
      await tester.pumpAndSettle();
      expect(calls, contains('POST /api/clients/1/monthly-report/link'));
      expect(opened.toString(), (fixture('monthly_report_link') as Map)['url']);
      expect(find.textContaining('Report downloaded'), findsOneWidget);

      await tapKey(tester, 'report-month');
      final now = DateTime.now();
      final key = DateFormat('yyyy-MM').format(DateTime(now.year, now.month - 3));
      await tapKey(tester, 'month-$key');
      expect(sentBodies['report-month'], key);
    });

    testWidgets('no score history yet', (tester) async {
      reportNoScore = true;
      addTearDown(() => reportNoScore = false);
      await openReport(tester, []);
      await tapKey(tester, 'tab-performance');
      expect(find.text('No score history yet'), findsOneWidget);
      expect(find.text('Your Marketing Score is calculated every Monday. The first point lands next week.'), findsOneWidget);
    });
  });

  group('owner My Plan', () {
    Future<void> openPlan(WidgetTester tester, List<String> calls) async {
      planPaid = false;
      sentBodies.remove('plan-billing');
      await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.byKey(const Key('owner-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('menu-my-plan')));
      await tester.pumpAndSettle();
    }

    Future<void> tapKey(WidgetTester tester, String key) async {
      await tester.ensureVisible(find.byKey(Key(key)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    testWidgets('Razorpay test keys: the app says no real money moves', (tester) async {
      planRazorpayTest = true;
      addTearDown(() => planRazorpayTest = false);
      await openPlan(tester, []);
      await tapKey(tester, 'plan-start');
      await tapKey(tester, 'go-premium');
      expect(find.textContaining('Razorpay test mode: no real money moves'), findsOneWidget);
      expect(find.textContaining('success@razorpay'), findsOneWidget);
      expect(find.textContaining('Practice mode'), findsNothing);
    });

    testWidgets('not activated, no mandates, no payments; billing details', (tester) async {
      final calls = <String>[];
      await openPlan(tester, calls);
      expect(calls, contains('GET /api/clients/1/plan'));
      expect(find.text('Your Pro Plan is'), findsOneWidget);
      expect(find.text('Not Activated'), findsOneWidget);
      expect(find.text('Start @ ₹999/-'), findsOneWidget);
      expect(find.text('No Active Mandates'), findsOneWidget);
      expect(find.text('No payments yet'), findsOneWidget);

      await tapKey(tester, 'billing-details');
      expect(find.text('Billing Details'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('gstin')), '27ABCDE1234F1Z5');
      await tester.enterText(find.byKey(const Key('billing-address')), '12 Baner Rd, Pune 411045');
      await tapKey(tester, 'billing-save');
      expect(sentBodies['plan-billing'], {'gstin': '27ABCDE1234F1Z5', 'billing_address': '12 Baner Rd, Pune 411045', 'shipping_same': true, 'shipping_address': ''});
      expect(find.text('Billing details saved'), findsOneWidget);
    });

    testWidgets('compare plans, choose 12 months, coupon, pay and come back active', (tester) async {
      Uri? opened;
      MyPlanScreen.openUrl = (url) async {
        opened = url;
        return true;
      };
      final calls = <String>[];
      await openPlan(tester, calls);
      await tapKey(tester, 'plan-start');
      expect(find.byKey(const Key('compare-table')), findsOneWidget);
      expect(find.text('BESTSELLER'), findsOneWidget);
      await tapKey(tester, 'go-premium');

      expect(find.text('Choose your plan'), findsOneWidget);
      expect(find.text('₹16,000'), findsWidgets);
      expect(tester.widget<Text>(find.byKey(const Key('plan-total'))).data, '₹16,000');
      expect(find.textContaining('Practice mode'), findsOneWidget);
      await tapKey(tester, 'coupon-open');
      await tester.enterText(find.byKey(const Key('coupon')), 'NOPE');
      await tapKey(tester, 'coupon-apply');
      expect(find.text("That coupon code isn't valid"), findsOneWidget);
      await tester.enterText(find.byKey(const Key('coupon')), 'WELCOME10');
      await tapKey(tester, 'coupon-apply');
      expect(tester.widget<Text>(find.byKey(const Key('plan-total'))).data, '₹14,400');
      expect(find.textContaining('you save ₹1,600'), findsOneWidget);

      await tapKey(tester, 'plan-continue');
      expect(sentBodies['plan-checkout'], {'plan': 'pro_12', 'coupon': 'WELCOME10'});
      expect(opened.toString(), (fixture('plan_checkout') as Map)['url']);
      // back from the payment page
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Plan activated'), findsOneWidget);
      await tapKey(tester, 'plan-done');
      expect(find.text('Active'), findsOneWidget);
      expect(find.textContaining('Valid till'), findsOneWidget);
      expect(find.byKey(const Key('payment-1')), findsOneWidget);
      expect(find.text('Paid'), findsOneWidget);
    });
  });

  group('owner Settings', () {
    Future<Session> openSettings(WidgetTester tester, List<String> calls) async {
      analyticsOn = false;
      prefState = null;
      sentBodies.clear();
      final session = await pumpApp(tester, calls);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.byKey(const Key('owner-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('menu-settings')));
      await tester.pumpAndSettle();
      return session;
    }

    Future<void> tapKey(WidgetTester tester, String key) async {
      if (find.byKey(Key(key)).evaluate().isEmpty) {
        // not built yet: it's further down — or back up, after scrolling to the footer
        await tester.dragUntilVisible(find.byKey(Key(key)), find.byType(Scrollable).last, const Offset(0, 300), maxIteration: 20)
            .catchError((Object _) => tester.dragUntilVisible(find.byKey(Key(key)), find.byType(Scrollable).last, const Offset(0, -300)));
      }
      await tester.ensureVisible(find.byKey(Key(key)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(Key(key)));
      await tester.pumpAndSettle();
    }

    Future<void> back(WidgetTester tester) async {
      await tester.pageBack();
      await tester.pumpAndSettle();
    }

    testWidgets('plan card, sections, privacy choice, legal pages and footer', (tester) async {
      final calls = <String>[];
      final session = await openSettings(tester, calls);
      expect(calls, contains('GET /api/clients/1/settings'));
      expect(find.text('Smile Dental Studio'), findsWidgets);
      expect(find.text('Upgrade to Pro'), findsOneWidget);
      for (final h in ['TOOLS', 'ACCOUNT', 'PRIVACY', 'LEGAL']) {
        await tester.scrollUntilVisible(find.text(h), 200, scrollable: find.byType(Scrollable).last);
        expect(find.text(h), findsOneWidget);
      }
      await tester.scrollUntilVisible(find.byKey(const Key('set-footer')), 200, scrollable: find.byType(Scrollable).last);
      expect(find.text('Green Media · #0001 · v1.0.0'), findsOneWidget);

      // Analytics & Personalisation is opt-in
      expect(tester.widget<SwitchListTile>(find.byKey(const Key('set-analytics'))).value, isFalse);
      await tapKey(tester, 'set-analytics');
      expect(analyticsOn, isTrue);
      expect(session.me!.analytics, isTrue);
      expect(tester.widget<SwitchListTile>(find.byKey(const Key('set-analytics'))).value, isTrue);

      await tapKey(tester, 'set-privacy');
      expect(find.text('Privacy Policy'), findsOneWidget);
      await tester.scrollUntilVisible(find.textContaining('Digital Personal Data Protection Act'), 300, scrollable: find.byType(Scrollable).last);
      expect(find.textContaining('Digital Personal Data Protection Act'), findsOneWidget);
      await back(tester);
      await tapKey(tester, 'set-terms');
      expect(find.text('Terms of Service'), findsWidgets);
      await back(tester);

      await tapKey(tester, 'plan-manage');
      expect(find.text('Your Pro Plan is'), findsOneWidget);
    });

    testWidgets('my QRs and a QR standee', (tester) async {
      Uri? opened;
      OwnerSettingsScreen.openUrl = (url) async {
        opened = url;
        return true;
      };
      ConfigureStandeeScreen.scanner = (onCode) => Center(
            child: TextButton(key: const Key('fake-scan'), onPressed: () => onCode('https://api.test/q/abcd123'), child: const Text('scan')),
          );
      final calls = <String>[];
      await openSettings(tester, calls);

      await tapKey(tester, 'set-qrs');
      final qrs = fixture('qrs_client') as Map<String, dynamic>;
      expect(find.text('${qrs['used']} / ${qrs['limit']}'), findsOneWidget);
      expect(find.text('1 SCAN'), findsOneWidget);
      await tapKey(tester, 'qr-generate');
      expect(calls, contains('POST /api/clients/1/qrs'));
      expect(find.byKey(const Key('qr-image')), findsOneWidget);
      await tapKey(tester, 'qr-download');
      expect(opened.toString(), (fixture('qr_link') as Map)['url']);
      expect(find.textContaining('QR standee downloaded'), findsOneWidget);
      await back(tester);

      await tapKey(tester, 'set-standee');
      expect(find.text('Align QR code within the frame'), findsOneWidget);
      await tester.tap(find.byKey(const Key('fake-scan')));
      await tester.pumpAndSettle();
      expect(sentBodies['claim'], {'code': 'https://api.test/q/abcd123'});
      expect(find.text('Standee set up'), findsOneWidget);
      await tapKey(tester, 'standee-done');
      expect(find.byKey(const Key('set-standee')), findsOneWidget);
    });

    testWidgets('change profile switches business', (tester) async {
      final calls = <String>[];
      final session = await openSettings(tester, calls);
      await tapKey(tester, 'set-profile');
      expect(find.text('Select profile'), findsOneWidget);
      final other = ((fixture('profiles_client') as Map)['profiles'] as List).cast<Map<String, dynamic>>().last;
      expect(find.text(other['title'] as String), findsOneWidget);
      expect(find.text('Current'), findsOneWidget);
      await tapKey(tester, 'profile-${other['user_id']}');
      expect(sentBodies['switch'], {'user_id': other['user_id']});
      expect(session.me!.clientName, other['title']);
    });

    testWidgets('refund request', (tester) async {
      await openSettings(tester, []);
      await tapKey(tester, 'set-refund');
      await tapKey(tester, 'refund-plan-pro_12');
      expect(find.textContaining('Eligible for a refund request within 7 days'), findsOneWidget);
      await tapKey(tester, 'refund-request-pro_12');
      await tester.enterText(find.byKey(const Key('refund-reason')), 'Not for us');
      await tapKey(tester, 'refund-send');
      final paid = ((fixture('refunds_client') as Map)['payments'] as List).first as Map;
      expect(sentBodies['refund'], {'payment_id': paid['id'], 'reason': 'Not for us'});
      expect(find.textContaining('Refund requested'), findsOneWidget);
    });

    testWidgets('delete account needs DELETE typed, then signs out', (tester) async {
      final session = await openSettings(tester, []);
      await tapKey(tester, 'set-delete');
      expect(tester.widget<FilledButton>(find.byKey(const Key('delete-confirm'))).onPressed, isNull);
      await tester.enterText(find.byKey(const Key('delete-confirm-text')), 'delete');
      await tester.pump();
      await tapKey(tester, 'delete-confirm');
      expect(sentBodies['delete-account'], {'confirm': 'delete'});
      expect(session.signedIn, isFalse);
      expect(find.text('Get OTP'), findsOneWidget);
    });
  });

  testWidgets('review queue: escalated replies cannot be published before approval', (tester) async {
    await pumpApp(tester, []);
    await signIn(tester, 'admin@greenmedia.in');
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Reviews')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Needs reply ('), findsOneWidget);
    expect(find.byType(ReviewCard), findsWidgets);
  });

  group('owner Preference', () {
    Future<void> openPreference(WidgetTester tester) async {
      analyticsOn = false;
      prefState = null;
      sentBodies.clear();
      await pumpApp(tester, []);
      await signIn(tester, 'anjali@smiledental.in');
      await tester.tap(find.byKey(const Key('owner-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('menu-settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('set-preference')));
      await tester.pumpAndSettle();
    }

    Finder list() => find.descendant(of: find.byKey(const Key('pref-list')), matching: find.byType(Scrollable)).first;

    Future<void> reveal(WidgetTester tester, Finder f) async {
      if (f.evaluate().isEmpty) {
        await tester.dragUntilVisible(f, list(), const Offset(0, -300), maxIteration: 60)
            .catchError((Object _) => tester.dragUntilVisible(f, list(), const Offset(0, 300), maxIteration: 60));
      }
      await tester.ensureVisible(f);
      await tester.pumpAndSettle();
    }

    Future<void> tapIt(WidgetTester tester, Finder f) async {
      await reveal(tester, f);
      await tester.tap(f);
      await tester.pumpAndSettle();
    }

    Finder inField(String k, String inner) => find.descendant(of: find.byKey(Key('field-$k')), matching: find.byKey(Key(inner)));
    List<Map> patches() => ((sentBodies['preference'] as List?) ?? []).cast<Map>();

    testWidgets('progress, socials, tabs and editing a poster field', (tester) async {
      await openPreference(tester);
      final pref = fixture('preference_client') as Map<String, dynamic>;
      final prog = pref['progress'] as Map;
      expect(find.text('${prog['done']}/${prog['total']}'), findsOneWidget);
      expect(find.text((prog['next'] as Map)['label'] as String), findsOneWidget);
      expect(find.byKey(const Key('social-google')), findsOneWidget);
      expect(find.text('@smiledentalstudio'), findsOneWidget);
      expect(find.byKey(const Key('connect-instagram')), findsOneWidget);
      expect(find.byKey(const Key('pref-add-product')), findsOneWidget);

      await tester.tap(find.byKey(const Key('pref-tab-2')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('poster-preview')), findsOneWidget);
      expect(tester.widget<Text>(find.byKey(const Key('poster-name'))).data, 'Smile Dental Studio');

      await tapIt(tester, inField('brand_name', 'edit'));
      await tester.enterText(inField('brand_name', 'input'), 'Smile Dental');
      await tapIt(tester, inField('brand_name', 'save'));
      expect(patches().last, {'brand_name': 'Smile Dental'});
      expect(inField('brand_name', 'save'), findsNothing);
      await reveal(tester, find.byKey(const Key('poster-name')));
      expect(tester.widget<Text>(find.byKey(const Key('poster-name'))).data, 'Smile Dental');

      await tapIt(tester, find.byKey(const Key('field-founder_in_promos')));
      expect(patches().last, {'founder_in_promos': false});
    });

    testWidgets('logo photo: pick, upload and remove', (tester) async {
      AddItemScreen.pickPhoto = () async => (base64Decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='), 'logo.png');
      await openPreference(tester);
      await tapIt(tester, find.byKey(const Key('photo-logo')));
      expect(sentBodies['pref-photo'], allOf(contains('name="image"'), contains('logo.png')));
      final done = ((fixture('preference_logo') as Map)['progress'] as Map)['done'];
      await reveal(tester, find.byKey(const Key('pref-progress-count')));
      expect(tester.widget<Text>(find.byKey(const Key('pref-progress-count'))).data, '$done/6');
      await tapIt(tester, find.byKey(const Key('photo-remove-logo')));
      expect(sentBodies['pref-photo'], 'deleted');
      expect(find.byKey(const Key('photo-remove-logo')), findsNothing);
    });

    testWidgets('hashtags: add with space, up to 10, save and mode', (tester) async {
      await openPreference(tester);
      await reveal(tester, find.byKey(const Key('hashtag-input')));
      await tester.enterText(find.byKey(const Key('hashtag-input')), '#Pune ');
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('hashtag-input')), 'dentist');
      await tapIt(tester, find.byKey(const Key('hashtag-add')));
      expect(find.byKey(const Key('tag-#Pune')), findsOneWidget);
      expect(find.byKey(const Key('tag-#dentist')), findsOneWidget);
      await tester.enterText(find.byKey(const Key('hashtag-input')), 'pune a b c d e f g h i j k');
      await tapIt(tester, find.byKey(const Key('hashtag-add')));
      expect(tester.widget<Text>(find.byKey(const Key('hashtag-count'))).data, '10/10 hashtags added');
      await tapIt(tester, find.byKey(const Key('hashtag-save')));
      expect(patches().last, {'hashtags': ['#Pune', '#dentist', '#a', '#b', '#c', '#d', '#e', '#f', '#g', '#h']});
      await tapIt(tester, find.byKey(const Key('hashtag-exact')));
      expect(patches().last, {'hashtag_mode': 'exact'});
    });

    testWidgets('advance settings: colour, choices, publish switches and AI terms', (tester) async {
      await openPreference(tester);
      expect(find.byKey(const Key('color-#0F7A45')), findsNothing);
      await tester.ensureVisible(find.byKey(const Key('pref-tab-3')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('pref-tab-3')));
      await tester.pumpAndSettle();
      expect(tester.getTopLeft(find.byKey(const Key('color-#0F7A45'))).dy, lessThan(500)); // the tab scrolled there
      await tapIt(tester, find.byKey(const Key('color-#0F7A45')));
      expect(patches().last, {'brand_color': '#0F7A45'});
      expect(find.text('Posters use #0F7A45'), findsOneWidget);

      await tapIt(tester, find.byKey(const Key('field-target_age')));
      await tester.tap(find.text('25-34').last);
      await tester.pumpAndSettle();
      expect(patches().last, {'target_age': '25-34'});

      await tapIt(tester, find.byKey(const Key('publish-instagram')));
      expect(patches().last, {'publish': {'instagram': false}});
      expect(tester.widget<SwitchListTile>(find.byKey(const Key('publish-instagram'))).value, isFalse);
      await tapIt(tester, find.byKey(const Key('religious-jain')));
      expect(patches().last, {'religious': {'jain': false}});

      await tapIt(tester, find.byKey(const Key('pref-ai-terms')));
      expect(find.text((fixture('legal_ai') as Map)['title'] as String), findsWidgets);
    });
  });

  testWidgets('ReviewCard disables Publish for an unapproved low rating', (tester) async {
    final session = Session(store: MemoryStore(), api: ApiClient(baseUrl: 'http://api.test', httpClient: fakeApi([])));
    session.me = Me.fromJson((fixture('login_admin') as Map<String, dynamic>)['user'] as Map<String, dynamic>);
    final review = Review.fromJson({
      'id': 1, 'client_id': 1, 'client_name': 'Smile Dental Studio', 'author': 'Rahul M.', 'rating': 1, 'text': 'Terrible',
      'language': 'en', 'sentiment': 'negative', 'reply': 'We are sorry', 'reply_status': 'drafted', 'needs_escalation': true,
      'created_at': '2026-09-20T10:00:00+00:00', 'published_at': null,
    });
    await tester.pumpWidget(ChangeNotifierProvider.value(
      value: session,
      child: MaterialApp(home: Scaffold(body: ListView(children: [ReviewCard(review: review, onChanged: () {})]))),
    ));
    final publish = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Publish'));
    expect(publish.onPressed, isNull);
    expect(find.widgetWithText(FilledButton, 'Approve'), findsOneWidget);
    expect(find.textContaining('2★ or lower'), findsOneWidget);
  });

  testWidgets('ReviewCard: nothing publishes without approval, whatever the rating', (tester) async {
    final session = Session(store: MemoryStore(), api: ApiClient(baseUrl: 'http://api.test', httpClient: fakeApi([])));
    session.me = Me.fromJson((fixture('login_admin') as Map<String, dynamic>)['user'] as Map<String, dynamic>);
    Review review(String status) => Review.fromJson({
          'id': 2, 'client_id': 1, 'client_name': 'Smile Dental Studio', 'author': 'Priya S.', 'rating': 5, 'text': 'Lovely staff!',
          'language': 'en', 'sentiment': 'positive', 'reply': 'Thank you!', 'reply_status': status, 'needs_escalation': false,
          'created_at': '2026-09-20T10:00:00+00:00', 'published_at': null,
        });
    Future<FilledButton> publishFor(String status) async {
      await tester.pumpWidget(ChangeNotifierProvider.value(
        value: session,
        child: MaterialApp(home: Scaffold(body: ListView(children: [ReviewCard(key: UniqueKey(), review: review(status), onChanged: () {})]))),
      ));
      return tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Publish'));
    }

    expect((await publishFor('drafted')).onPressed, isNull); // 5★ but not approved
    expect((await publishFor('approved')).onPressed, isNotNull);
  });

  test('greetings use the first name, not the title', () {
    expect(firstName('Dr. Anjali Rao'), 'Anjali');
    expect(firstName('Aarav Mehta'), 'Aarav');
    expect(firstName('Mrs Kavya Iyer'), 'Kavya');
    expect(firstName('Dr.'), 'Dr.');
  });

  test('fixtures parse into typed models', () {
    final reviews = fixture('reviews_admin') as Map<String, dynamic>;
    expect([for (final r in reviews['items'] as List) Review.fromJson(r as Map<String, dynamic>)], isNotEmpty);
    final content = [for (final c in fixture('content_admin') as List) ContentItem.fromJson(c as Map<String, dynamic>)];
    expect(content.every((c) => c.scheduledAt == null || c.scheduledAt!.isUtc == false), isTrue); // converted to local time
    final clients = [for (final c in fixture('clients_admin') as List) ClientBrief.fromJson(c as Map<String, dynamic>)];
    expect(clients.length, 24);
  });

  test('ApiClient flattens FastAPI validation errors and flags 401s', () async {
    var unauthorized = false;
    final api = ApiClient(
      baseUrl: 'http://api.test',
      httpClient: MockClient((req) async => req.url.path == '/401'
          ? http.Response('{"detail":"Invalid or expired token"}', 401)
          : http.Response('{"detail":[{"loc":["body","topic"],"msg":"String should have at least 2 characters"}]}', 422)),
    )..onUnauthorized = () => unauthorized = true;
    await expectLater(api.post('/422', {}), throwsA(isA<ApiException>().having((e) => e.message, 'message', 'topic: String should have at least 2 characters')));
    await expectLater(api.get('/401'), throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', true)));
    expect(unauthorized, isTrue);
  });
}
