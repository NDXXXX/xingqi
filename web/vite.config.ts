import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  base: "/react/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/zhiyu/web/static/react",
    emptyOutDir: true,
    lib: {
      entry: "src/dialogHost.tsx",
      formats: ["es"],
      fileName: "dialogHost",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        assetFileNames: "dialogHost.[ext]",
      },
    },
  },
});
