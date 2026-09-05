import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest) => {
            // The browser origin is the Vite LAN address during development.
            // Rewrite it on the internal proxy hop so Flask treats this as
            // the trusted same-origin development proxy request.
            proxyRequest.setHeader('Origin', 'http://127.0.0.1:5000');
          });
        },
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
  },
});
