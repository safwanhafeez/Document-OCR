import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f5f0e8",
        ink: "#0a0a0f",
        terracotta: "#c8451a",
        muted: "#8a8070",
        surface: "#faf7f2",
        border: "#d4cec2"
      },
      fontFamily: {
        serif: ["var(--font-instrument-serif)", "Georgia", "serif"],
        mono: ["var(--font-dm-mono)", "ui-monospace", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;
