import { Capacitor } from '@capacitor/core';

declare global {
  interface Window {
    desktop?: { platform: string; isDesktop: boolean };
  }
}

export type RuntimePlatform = 'ios' | 'android' | 'desktop' | 'web';

export function runtimePlatform(): RuntimePlatform {
  if (window.desktop?.isDesktop) return 'desktop';
  const p = Capacitor.getPlatform();
  return p === 'ios' || p === 'android' ? p : 'web';
}

export async function initNativeShell() {
  if (!Capacitor.isNativePlatform()) return;
  const [{ StatusBar, Style }, { SplashScreen }, { App }] = await Promise.all([
    import('@capacitor/status-bar'),
    import('@capacitor/splash-screen'),
    import('@capacitor/app'),
  ]);
  StatusBar.setStyle({ style: Style.Dark }).catch(() => {});
  SplashScreen.hide().catch(() => {});
  // Android hardware back button: navigate back in-app, exit at the root.
  App.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) window.history.back();
    else App.exitApp();
  });
}
