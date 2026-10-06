import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 画面は自分の PC でだけ使う。/api は手元のサーバー（app/server、既定 8000 番）へ渡す
const apiTarget = process.env.CD_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": apiTarget } },
  preview: { host: "127.0.0.1", port: 4173, proxy: { "/api": apiTarget } },
});
