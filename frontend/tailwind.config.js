/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0f4ff",
          100: "#e0e9ff",
          500: "#4361ee",
          600: "#3451d1",
          700: "#2541b2",
          900: "#0d1f6e",
        },
        surface: {
          DEFAULT: "#0f111a",
          card: "#151823",
          border: "#1e2235",
          muted: "#262c42",
        },
        text: {
          primary: "#e8eaf6",
          secondary: "#8b92b8",
          muted: "#555e82",
        },
        status: {
          ok: "#22c55e",
          warn: "#f59e0b",
          error: "#ef4444",
          info: "#3b82f6",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
