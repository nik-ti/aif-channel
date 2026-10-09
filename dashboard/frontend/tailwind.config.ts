// Tailwind theme tokens; the values live in app/globals.css (light and dark).
// Dark mode is class-based (toggled by Header.tsx) since the app defaults
// to light mode but still offers a light/dark switch.
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          primary: "var(--surface-primary)",
          secondary: "var(--surface-secondary)",
          solid: "var(--surface-solid)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          soft: "var(--accent-soft)",
        },
        ink: {
          primary: "var(--ink-primary)",
          muted: "var(--ink-muted)",
        },
        border: "var(--border-color)",
        status: {
          published: "#10B981",
          rejected: "#DC2626",
          hold: "#F59E0B",
          duplicate: "#2563EB",
          expired: "#9CA3AF",
        },
      },
    },
  },
  plugins: [],
};
export default config;
