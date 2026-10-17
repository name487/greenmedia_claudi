import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greenmedia/api/api_client.dart';
import 'package:greenmedia/api/models.dart';
import 'package:greenmedia/main.dart';
import 'package:greenmedia/screens/meta_connect_screen.dart';
import 'package:greenmedia/screens/owner_reviews_screen.dart';
import 'package:greenmedia/screens/reviews_screen.dart';
import 'package:greenmedia/state/session.dart';
import 'package:greenmedia/widgets/common.dart';
import 'package:http/http.dart' as http;
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

/// Fake backend: `who` is decided by the login email.
MockClient fakeApi(List<String> calls) {
  var who = 'admin';
  return MockClient((req) async {
    calls.add('${req.method} ${req.url.path}');
    http.Response json(Object body, [int status = 200]) =>
        http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json'});
    switch (req.url.path) {
      case '/api/auth/login':
        final email = (jsonDecode(req.body) as Map)['email'] as String;
        if ((jsonDecode(req.body) as Map)['password'] != 'demo1234') return json({'detail': 'Incorrect email or password'}, 401);
        who = email.startsWith('anjali') ? 'client' : 'admin';
        return json(fixture('login_$who'));
      case '/api/auth/otp/request':
        final digits = ((jsonDecode(req.body) as Map)['phone'] as String).replaceAll(RegExp(r'\D'), '');
        final phone = '+91$digits';
        return json({...fixture('otp_request') as Map, 'phone': phone, 'masked': '${phone.substring(0, phone.length - 6)}••••${phone.substring(phone.length - 2)}'});
      case '/api/auth/otp/verify':
        final b = jsonDecode(req.body) as Map;
        if (b['code'] != '1234') return json({'detail': 'Incorrect code — 4 attempts left'}, 400);
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

Future<void> signIn(WidgetTester tester, String email, [String password = 'demo1234']) async {
  // The app opens on mobile-number sign-in; staff use the email form behind this link.
  final emailLink = find.text('Agency team? Sign in with email');
  if (emailLink.evaluate().isNotEmpty) {
    await tester.tap(emailLink);
    await tester.pumpAndSettle();
  }
  await tester.enterText(find.widgetWithText(TextField, 'Email'), email);
  await tester.enterText(find.widgetWithText(TextField, 'Password'), password);
  await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));
  await tester.pumpAndSettle();
}

Future<void> requestCode(WidgetTester tester, String phone) async {
  await tester.enterText(find.byKey(const Key('phone')), phone);
  await tester.pump();
  await tester.tap(find.text('Get OTP'));
  await tester.pumpAndSettle();
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

      await tester.enterText(find.byKey(const Key('otp')), '9999');
      await tester.pumpAndSettle();
      expect(find.textContaining('Incorrect code'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('otp')), '1234'); // verifies automatically when complete
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

    testWidgets('a single profile opens straight away; demo code chip fills the code', (tester) async {
      final session = await pumpApp(tester, []);
      await requestCode(tester, '9000000001');
      await tester.tap(find.text('Demo server — code 1234'));
      await tester.pumpAndSettle();
      expect(session.signedIn, isTrue);
      expect(session.me!.role, 'admin');
    });

    testWidgets('back from the code step returns to the number', (tester) async {
      await pumpApp(tester, []);
      await requestCode(tester, '9876543210');
      await tester.tap(find.byTooltip('Back'));
      await tester.pumpAndSettle();
      expect(find.text('Enter your\nphone number'), findsOneWidget);
    });
  });

  testWidgets('wrong password shows the server message', (tester) async {
    await pumpApp(tester, []);
    await signIn(tester, 'admin@greenmedia.in', 'nope');
    expect(find.text('Incorrect email or password'), findsOneWidget);
  });

  testWidgets('admin signs in and sees the agency dashboard', (tester) async {
    final calls = <String>[];
    final session = await pumpApp(tester, calls);
    await signIn(tester, 'admin@greenmedia.in');
    expect(session.me!.role, 'admin');
    expect(calls, containsAllInOrder(['POST /api/auth/login', 'GET /api/dashboard']));
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
    expect(find.descendant(of: nav, matching: find.text('Analytics')), findsOneWidget);
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

  testWidgets('review queue: escalated replies cannot be published before approval', (tester) async {
    await pumpApp(tester, []);
    await signIn(tester, 'admin@greenmedia.in');
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Reviews')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Needs reply ('), findsOneWidget);
    expect(find.byType(ReviewCard), findsWidgets);
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
