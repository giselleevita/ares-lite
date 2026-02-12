import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        tactical: {
          950: "#04070d",
          900: "#0a111e",
          800: "#111c2f",
          700: "#1a2b44",
          600: "#274265",
          500: "#2d5f87",
          300: "#79b2d9",
          200: "#9dd3f7",
        },
        accent: {
          amber: "#d8b45f",
          red: "#be5c5c",
          green: "#68bb8d",
        },
      },
      fontFamily: {
        tactical: ["Rajdhani", "Eurostile", "sans-serif"],
        mono: ["Share Tech Mono", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(121, 178, 217, 0.25), 0 0 24px rgba(121, 178, 217, 0.08)",
      },
    },
  },
  plugins: [],
} satisfies Config;
