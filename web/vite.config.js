/*
 * vite.config.js - Build da PWA.
 *
 * - plugin-react: JSX/React.
 * - vite-plugin-pwa: gera o manifest (instalar na tela inicial, RF14) e o
 *   service worker que guarda a "casca" do app para abrir mesmo sem rede (RF15).
 *   As rotas /api NUNCA são cacheadas: alerta precisa ser sempre o dado real.
 * - server.proxy: em desenvolvimento (npm run dev) repassa /api para o Python na porta 8000.
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icone.svg"],
      manifest: {
        name: "Sentinela - Monitoramento de Quedas",
        short_name: "Sentinela",
        description: "Alertas de queda em tempo real para cuidadores de ILPI",
        lang: "pt-BR",
        theme_color: "#0b1220",
        background_color: "#0b1220",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icone.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
          { src: "icone-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/],
        globPatterns: ["**/*.{js,css,html,svg,woff2}"],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", ws: true, changeOrigin: true },
    },
  },
});
