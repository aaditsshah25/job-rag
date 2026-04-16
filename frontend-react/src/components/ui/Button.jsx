export default function Button({ children, variant = 'primary', className = '', ...props }) {
  const base =
    'inline-flex items-center justify-center rounded-full px-5 py-2.5 text-sm font-semibold transition duration-200';

  const variants = {
    primary:
      'bg-neon text-slate-950 hover:-translate-y-0.5 hover:bg-emerald-300 shadow-glow',
    secondary:
      'border border-white/20 bg-white/5 text-ink hover:-translate-y-0.5 hover:bg-white/10',
  };

  return (
    <button className={`${base} ${variants[variant] || variants.primary} ${className}`} {...props}>
      {children}
    </button>
  );
}
