import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": process.env.TAME_INK_API_TARGET ?? "http://127.0.0.1:8000",
    },
  },
});
