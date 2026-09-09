/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f1efff", 100: "#e1ddff", 500: "#7c6ff2", 600: "#6d5fe5", 700: "#5d50c8", 900: "#29235e",
        },
        surface: {
          DEFAULT: "var(--canvas)", card: "var(--surface)", border: "var(--border)", muted: "var(--hover)",
        },
        text: {
          primary: "var(--text)", secondary: "var(--secondary)", muted: "var(--muted)",
        },
        status: {
          ok: "var(--success)", warn: "var(--warning)", error: "var(--danger)", info: "var(--info)",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
