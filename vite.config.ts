import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Relative base so the same build loads from file:// (Electron) and capacitor:// (iOS/Android).
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});
