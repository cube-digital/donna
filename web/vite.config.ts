import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_PROXY_TARGET ?? "http://localhost:8000";
  const wsTarget = apiTarget.replace(/^http/, "ws");

  // Honor PORT env var so external launchers (preview, docker, CI) can
  // assign a port. Falls back to 5173 for local `npm run dev`.
  const port = Number(process.env.PORT) || 5173;
  const strictPort = !process.env.PORT;

  return {
    plugins: [react()],
    server: {
      port,
      strictPort,
      proxy: {
        "/api": { target: apiTarget, changeOrigin: true },
        "/ws": { target: wsTarget, ws: true, changeOrigin: true },
      },
    },
  };
});
