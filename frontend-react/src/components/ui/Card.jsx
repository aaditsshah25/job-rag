export default function Card({ children, className = '' }) {
  return (
    <article
      className={`rounded-3xl border border-white/10 bg-white/[0.03] p-6 backdrop-blur-sm ${className}`}
    >
      {children}
    </article>
  );
}
