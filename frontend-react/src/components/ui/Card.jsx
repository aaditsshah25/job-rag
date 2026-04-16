export default function Card({ children, className = '' }) {
  return (
    <article
      className={`rounded-xl border border-border-light bg-cream p-6 shadow-card ${className}`}
    >
      {children}
    </article>
  );
}
