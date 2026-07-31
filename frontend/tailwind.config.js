/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surface palette driven by CSS variables so it flips between the dark and
        // light themes (opacity variants work via the `<alpha-value>` channel form).
        base: {
          900: "rgb(var(--base-900) / <alpha-value>)",
          800: "rgb(var(--base-800) / <alpha-value>)",
          700: "rgb(var(--base-700) / <alpha-value>)",
          600: "rgb(var(--base-600) / <alpha-value>)",
          500: "rgb(var(--base-500) / <alpha-value>)",
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
