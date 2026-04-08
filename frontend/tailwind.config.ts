import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        "coral-black": "#0F0B0B",
        "tundora": "#4C4C4C",
        "light-gray": "#E5E5E5",
      },
      fontSize: {
        "2xs": "0.6875rem",
      },
    },
    /* Deloitte Design System: Sharp corners (0px border-radius) */
    borderRadius: {
      none: "0px",
      sm: "0px",
      DEFAULT: "0px",
      md: "0px",
      lg: "0px",
      xl: "0px",
      "2xl": "0px",
      "3xl": "0px",
      full: "0px", /* Prevent pill shapes */
    },
  },
  plugins: [],
};
export default config;
