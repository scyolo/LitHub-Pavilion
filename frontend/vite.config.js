import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 仅开发服务器代理本地 API；公开静态构建没有 API 代理。
const base = process.env.VITE_BASE_PATH || "/";
if (!base.startsWith("/") || !base.endsWith("/") || base.includes("\\") || base.includes(":")) {
  throw new Error("VITE_BASE_PATH must be a URL path such as /LitHub-Pavilion/, not a filesystem path");
}

export default defineConfig({
  plugins: [react()],
  base,
  publicDir: "static",
  server: {
    // 5180：避开本机其他项目占用的 5173（曾导致打开到空壳应用）；strictPort 防止静默换端口；
    // 显式绑 IPv4，避免 Node 默认绑 ::1 造成 IPv4 侧无法访问
    host: "127.0.0.1",
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
