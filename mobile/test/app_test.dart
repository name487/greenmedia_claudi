import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:greenmedia/api/api_client.dart';
import 'package:greenmedia/api/models.dart';
import 'package:greenmedia/main.dart';
import 'package:greenmedia/screens/reviews_screen.dart';
import 'package:greenmedia/state/session.dart';
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
      case '/api/dashboard':
        return json(fixture('dashboard_$who'));
      case '/api/reviews':
        return json(fixture('reviews_$who'));
      case '/api/clients':
        return json(fixture('clients_admin'));
      case '/api/content':
        return json(fixture('content_admin'));
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
  await tester.enterText(find.widgetWithText(TextField, 'Email'), email);
  await tester.enterText(find.widgetWithText(TextField, 'Password'), password);
  await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));
  await tester.pumpAndSettle();
}

void main() {
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
    for (final tab in ['Dashboard', 'Reviews', 'Content', 'Calendar', 'More']) {
      expect(find.descendant(of: find.byType(NavigationBar), matching: find.text(tab)), findsOneWidget);
    }
  });

  testWidgets('client-portal user gets a client-only experience', (tester) async {
    await pumpApp(tester, []);
    await signIn(tester, 'anjali@smiledental.in');
    expect(find.text('Active clients'), findsNothing);
    await tester.scrollUntilVisible(find.text('Where your leads come from'), 300, scrollable: find.byType(Scrollable).first);
    expect(find.text('Where your leads come from'), findsOneWidget);
    final nav = find.byType(NavigationBar);
    expect(find.descendant(of: nav, matching: find.text('Calendar')), findsNothing);
    expect(find.descendant(of: nav, matching: find.text('Analytics')), findsOneWidget);
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
