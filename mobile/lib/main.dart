import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/home_shell.dart';
import 'screens/phone_login_screen.dart';
import 'state/session.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final session = Session(store: DeviceSessionStore())..restore();
  runApp(GreenMediaApp(session: session));
}

const brandGreen = Color(0xFF0F7A45);

ThemeData buildTheme(Brightness b) {
  final scheme = ColorScheme.fromSeed(seedColor: brandGreen, brightness: b);
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: b == Brightness.light ? const Color(0xFFF4F7F5) : const Color(0xFF0C1511),
    cardTheme: CardThemeData(
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: BorderSide(color: scheme.outlineVariant)),
    ),
    inputDecorationTheme: InputDecorationTheme(border: OutlineInputBorder(borderRadius: BorderRadius.circular(10))),
  );
}

class GreenMediaApp extends StatelessWidget {
  const GreenMediaApp({super.key, required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider.value(
      value: session,
      child: MaterialApp(
        title: 'Green Media',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        // sideways lists (report tiles, charts, carousels) slide with a mouse drag too, on Windows, macOS and the web
        scrollBehavior: const MaterialScrollBehavior().copyWith(dragDevices: PointerDeviceKind.values.toSet()),
        home: Consumer<Session>(
          builder: (context, s, _) {
            if (s.restoring) return const Scaffold(body: Center(child: CircularProgressIndicator()));
            // Keyed by user so switching accounts rebuilds every screen from scratch.
            return s.signedIn ? HomeShell(key: ValueKey(s.me!.id)) : const PhoneLoginScreen();
          },
        ),
      ),
    );
  }
}
