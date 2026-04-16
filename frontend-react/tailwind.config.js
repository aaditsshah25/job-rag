/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        parchment: '#f4f2ed',
        cream: '#fffcf7',
        'cream-hover': '#f7f2e8',
        'parchment-section': '#f2ebdf',
        'border-light': '#dfd4c3',
        'border-mid': '#cdbfa9',
        teal: '#0d6d66',
        'teal-hover': '#0a5853',
        'teal-light': '#d8efe9',
        'teal-muted': 'rgba(13,109,102,0.1)',
        'text-base': '#1f1c16',
        'text-sub': '#4b4338',
        'text-muted': '#8c8172',
      },
      fontFamily: {
        sans: ['IBM Plex Sans', 'Manrope', 'Segoe UI', 'sans-serif'],
      },
      boxShadow: {
        card: '0 4px 12px rgba(49,35,14,0.08)',
        'card-md': '0 12px 30px rgba(49,35,14,0.12)',
      },
      keyframes: {
        rise: {
          '0%': { opacity: 0, transform: 'translateY(12px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
      },
      animation: {
        rise: 'rise 500ms ease forwards',
      },
    },
  },
  plugins: [],
};
