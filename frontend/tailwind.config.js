/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Institutional dark palette (Bloomberg/Koyfin-inspired).
        base: {
          900: "#0a0e14",
          800: "#0f172a",
          700: "#141b2d",
          600: "#1e293b",
          500: "#334155",
        },
        accent: { DEFAULT: "#38bdf8", muted: "#0284c7" },
        up: "#22c55e",
        down: "#ef4444",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
