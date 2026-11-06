import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the React app runs on :5173 and proxies /api to the FastAPI server on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ["/api", "/docs", "/openapi.json"].map((p) => [p, { target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000", changeOrigin: true }]),
    ),
  },
});
