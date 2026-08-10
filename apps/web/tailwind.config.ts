import type { Config } from "tailwindcss";

/**
 * Semantic tokens, not decorative ones.
 *
 * Colour carries meaning in this product: `ok` is reserved for verified and
 * approved states, `warn` for pending and confirm-this states, `stop` for
 * blocking issues only. `accent` is the single navy used for navigation state
 * and primary actions. Nothing else gets a colour.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#111c2e", // headings and primary values
          body: "#26364d", // narrative and body copy
          muted: "#5a6b83",
          faint: "#8194ab", // labels, metadata
        },
        line: {
          DEFAULT: "#e3e8ee",
          soft: "#edf1f5",
          strong: "#cfd8e3",
        },
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f5f7f9", // app background
          sunken: "#eef2f6",
          paper: "#fcfcfb", // the demand letter itself
        },
        accent: {
          50: "#eef3f9",
          100: "#dbe6f2",
          200: "#b9cde4",
          500: "#3a6ea5",
          600: "#2c5c8f",
          700: "#22496f",
          800: "#1b3a58",
          900: "#152c43",
        },
        ok: {
          50: "#eef8f2",
          100: "#d6efe0",
          200: "#a9dcc0",
          600: "#1f7a4d",
          700: "#166039",
          800: "#124b2d",
        },
        warn: {
          50: "#fdf6e9",
          100: "#faeacb",
          200: "#f0d49b",
          600: "#a86a12",
          700: "#87540c",
          800: "#6b4209",
        },
        stop: {
          50: "#fdf1f1",
          100: "#fadcdc",
          200: "#f2b8b8",
          600: "#b3373a",
          700: "#8f2b2e",
          800: "#722224",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        serif: ["ui-serif", "Georgia", "Cambria", "Times New Roman", "serif"],
        mono: ["ui-monospace", "Cascadia Mono", "Consolas", "monospace"],
      },
      fontSize: {
        // A deliberate scale rather than ad-hoc sizes.
        "2xs": ["0.6875rem", { lineHeight: "1rem" }], // 11px — labels
        label: ["0.75rem", { lineHeight: "1.125rem", letterSpacing: "0.06em" }],
        meta: ["0.8125rem", { lineHeight: "1.25rem" }], // 13px — metadata
        body: ["0.9375rem", { lineHeight: "1.5rem" }], // 15px — UI body
        prose: ["1rem", { lineHeight: "1.75rem" }], // 16px — legal narrative
        "card-title": ["1rem", { lineHeight: "1.5rem", letterSpacing: "-0.005em" }],
        section: ["1.1875rem", { lineHeight: "1.625rem", letterSpacing: "-0.01em" }],
        metric: ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.02em" }],
        "metric-lg": ["1.625rem", { lineHeight: "2rem", letterSpacing: "-0.02em" }],
        case: ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.022em" }],
      },
      boxShadow: {
        panel: "0 1px 2px rgba(17, 28, 46, 0.04)",
        rail: "0 1px 3px rgba(17, 28, 46, 0.06)",
        paper: "0 1px 2px rgba(17, 28, 46, 0.05), 0 6px 20px -12px rgba(17, 28, 46, 0.18)",
        overlay: "0 10px 40px -12px rgba(17, 28, 46, 0.35)",
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        md: "0.375rem",
      },
      maxWidth: {
        workspace: "1440px",
        letter: "68ch",
      },
      transitionDuration: {
        DEFAULT: "150ms",
      },
    },
  },
  plugins: [],
};

export default config;
