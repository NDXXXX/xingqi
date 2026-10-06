import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

export default defineConfig({
  base: "/react/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/zhiyu/web/static/react",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        dialogHost: resolve(import.meta.dirname, "src/dialogHost.tsx"),
        app: resolve(import.meta.dirname, "src/app.tsx"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
});
