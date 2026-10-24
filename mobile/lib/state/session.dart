import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../api/models.dart';

/// Where the token and server URL are persisted. The token goes to the Keychain / Android Keystore.
abstract class SessionStore {
  Future<String?> readToken();
  Future<void> writeToken(String? token);
  Future<String?> readBaseUrl();
  Future<void> writeBaseUrl(String url);
}

class DeviceSessionStore implements SessionStore {
  static const _secure = FlutterSecureStorage();
  static const _tokenKey = 'gm_token';
  static const _urlKey = 'gm_api_url';

  @override
  Future<String?> readToken() => _secure.read(key: _tokenKey);

  @override
  Future<void> writeToken(String? token) =>
      token == null ? _secure.delete(key: _tokenKey) : _secure.write(key: _tokenKey, value: token);

  @override
  Future<String?> readBaseUrl() async => (await SharedPreferences.getInstance()).getString(_urlKey);

  @override
  Future<void> writeBaseUrl(String url) async => (await SharedPreferences.getInstance()).setString(_urlKey, url);
}

/// Default API address: `--dart-define=API_URL=...` wins; otherwise the host machine as seen from
/// the Android emulator (10.0.2.2) or the iOS simulator (127.0.0.1).
String defaultApiUrl() {
  const fromEnv = String.fromEnvironment('API_URL');
  if (fromEnv.isNotEmpty) return fromEnv;
  if (!kIsWeb && Platform.isAndroid) return 'http://10.0.2.2:8001';
  return 'http://127.0.0.1:8001';
}

class Session extends ChangeNotifier {
  Session({required this.store, ApiClient? api}) : api = api ?? ApiClient(baseUrl: defaultApiUrl()) {
    this.api.onUnauthorized = () {
      if (me != null) logout();
    };
  }

  final SessionStore store;
  final ApiClient api;
  Me? me;
  bool restoring = true;

  bool get signedIn => me != null;

  Future<void> restore() async {
    api.baseUrl = await store.readBaseUrl() ?? api.baseUrl;
    api.token = await store.readToken();
    if (api.token != null) {
      try {
        me = Me.fromJson(await api.get('/api/auth/me') as Map<String, dynamic>);
      } on ApiException {
        api.token = null;
      }
    }
    restoring = false;
    notifyListeners();
  }

  Future<void> login(String email, String password) async {
    await _signIn(await api.post('/api/auth/login', {'email': email.trim(), 'password': password}) as Map<String, dynamic>);
  }

  /// Phone sign-in, step 1: the server texts a one-time code.
  Future<OtpSent> requestOtp(String phone, {String countryCode = '+91'}) async =>
      OtpSent.fromJson(await api.post('/api/auth/otp/request', {'phone': phone, 'country_code': countryCode}) as Map<String, dynamic>);

  /// Step 2: check the code; returns every profile (account) linked to the number.
  Future<OtpVerified> verifyOtp(String phone, String code) async =>
      OtpVerified.fromJson(await api.post('/api/auth/otp/verify', {'phone': phone, 'code': code}) as Map<String, dynamic>);

  /// Step 3: open one profile.
  Future<void> selectProfile(String otpToken, int userId) async {
    await _signIn(await api.post('/api/auth/otp/select', {'otp_token': otpToken, 'user_id': userId}) as Map<String, dynamic>);
  }

  /// Settings → Change Profile: open another profile on the same mobile number.
  Future<void> switchProfile(int userId) async {
    await _signIn(await api.post('/api/auth/switch', {'user_id': userId}) as Map<String, dynamic>);
  }

  /// Re-read the signed-in person (e.g. after changing a preference).
  Future<void> refreshMe() async {
    me = Me.fromJson(await api.get('/api/auth/me') as Map<String, dynamic>);
    notifyListeners();
  }

  Future<void> _signIn(Map<String, dynamic> out) async {
    api.token = out['access_token'] as String;
    await store.writeToken(api.token);
    me = Me.fromJson(out['user'] as Map<String, dynamic>);
    notifyListeners();
  }

  Future<void> logout() async {
    api.token = null;
    me = null;
    await store.writeToken(null);
    notifyListeners();
  }

  Future<void> setBaseUrl(String url) async {
    api.baseUrl = url.trim();
    await store.writeBaseUrl(api.baseUrl);
    notifyListeners();
  }
}
