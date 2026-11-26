/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        hazard: {
          blocked: "#ef4444",
          partial: "#f97316",
          clear: "#22c55e",
          uncertain: "#a855f7",
          stale: "#eab308",
          unknown: "#9ca3af",
        },
      },
    },
  },
  plugins: [],
};
