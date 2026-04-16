export default function Button({ children, variant = 'primary', className = '', ...props }) {
  const base =
    'inline-flex items-center justify-center rounded-lg px-5 py-2.5 text-sm font-semibold transition duration-200 cursor-pointer';

  const variants = {
    primary:
      'bg-teal text-white hover:bg-teal-hover shadow-sm',
    secondary:
      'border border-border-mid bg-cream text-text-base hover:bg-cream-hover',
    ghost:
      'text-text-sub hover:text-text-base hover:bg-parchment-section',
  };

  return (
    <button className={`${base} ${variants[variant] || variants.primary} ${className}`} {...props}>
      {children}
    </button>
  );
}
