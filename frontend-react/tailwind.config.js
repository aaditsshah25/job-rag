/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#05050a',
        ink: '#e8ecf3',
        neon: '#10b981',
        mango: '#f59e0b',
        rose: '#f43f5e',
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(16,185,129,0.25), 0 12px 40px rgba(16,185,129,0.2)',
      },
      backgroundImage: {
        mesh: 'radial-gradient(circle at 15% 20%, rgba(16,185,129,0.18), transparent 38%), radial-gradient(circle at 85% 12%, rgba(245,158,11,0.2), transparent 34%), radial-gradient(circle at 50% 100%, rgba(244,63,94,0.18), transparent 30%)',
      },
      keyframes: {
        rise: {
          '0%': { opacity: 0, transform: 'translateY(16px)' },
          '100%': { opacity: 1, transform: 'translateY(0)' },
        },
      },
      animation: {
        rise: 'rise 700ms ease forwards',
      },
    },
  },
  plugins: [],
};
