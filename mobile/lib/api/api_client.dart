import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;

  bool get isUnauthorized => status == 401;

  @override
  String toString() => message;
}

/// Thin JSON client for the FastAPI backend. All business rules live on the server.
class ApiClient {
  ApiClient({required this.baseUrl, this.token, http.Client? httpClient}) : _http = httpClient ?? http.Client();

  String baseUrl;
  String? token;
  final http.Client _http;

  /// Called when the API rejects the token so the app can return to the login screen.
  void Function()? onUnauthorized;

  Uri _uri(String path, [Map<String, Object?> query = const {}]) {
    final q = <String, String>{
      for (final e in query.entries)
        if (e.value != null && '${e.value}'.isNotEmpty) e.key: '${e.value}',
    };
    final base = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    return Uri.parse('$base$path').replace(queryParameters: q.isEmpty ? null : q);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Future<dynamic> get(String path, [Map<String, Object?> query = const {}]) =>
      _send(() => _http.get(_uri(path, query), headers: _headers));

  Future<dynamic> post(String path, [Object? body]) =>
      _send(() => _http.post(_uri(path), headers: _headers, body: jsonEncode(body ?? {})));

  Future<dynamic> patch(String path, Object body) =>
      _send(() => _http.patch(_uri(path), headers: _headers, body: jsonEncode(body)));

  Future<dynamic> delete(String path) => _send(() => _http.delete(_uri(path), headers: _headers));

  Future<dynamic> _send(Future<http.Response> Function() request) async {
    http.Response res;
    try {
      res = await request().timeout(const Duration(seconds: 90));
    } catch (e) {
      throw ApiException(0, 'Cannot reach the server at $baseUrl. Check your connection or the server address in Settings.');
    }
    final body = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode >= 400) {
      if (res.statusCode == 401) onUnauthorized?.call();
      throw ApiException(res.statusCode, _detail(body) ?? 'Request failed (${res.statusCode})');
    }
    return body;
  }

  static String? _detail(dynamic body) {
    if (body is! Map) return null;
    final d = body['detail'];
    if (d is String) return d;
    if (d is List) {
      return d.map((e) => e is Map ? '${(e['loc'] as List?)?.skip(1).join('.') ?? ''}: ${e['msg']}' : '$e').join('; ');
    }
    return null;
  }
}
