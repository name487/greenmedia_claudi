import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.greenmedia.commandcenter',
  appName: 'Green Media',
  webDir: 'dist',
  backgroundColor: '#0b1a12',
  plugins: {
    SplashScreen: { launchShowDuration: 800, backgroundColor: '#0b1a12', showSpinner: false },
  },
};

export default config;
