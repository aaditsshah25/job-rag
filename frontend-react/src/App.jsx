import { useState } from 'react';

const NAV_LINKS = [
  { label: 'How it works', id: 'how-it-works' },
  { label: 'Features', id: 'features' },
];

const STATS = [
  { value: '2,000+', label: 'Job listings indexed' },
  { value: 'Top 5', label: 'Matches per search' },
  { value: '0–10', label: 'Transparent score' },
  { value: 'GPT-4o', label: 'Powered by' },
];

const FEATURES = [
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="h-5 w-5">
        <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    title: 'Resume Parsing',
    description: 'Upload a PDF and your profile is auto-filled instantly. No manual entry.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="h-5 w-5">
        <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    title: 'RAG Job Matching',
    description: 'Semantic retrieval + GPT-4o ranking surfaces your top 5 matches from 2,000+ real listings.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="h-5 w-5">
        <path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    title: 'Match Score Cards',
    description: 'Every job gets a score out of 10 with fit reasons, skill gaps, and next steps.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="h-5 w-5">
        <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    title: 'Cover Letter Generation',
    description: 'Per-job tailored cover letters in professional, friendly, or concise tone.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="h-5 w-5">
        <path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    title: 'Resume Tailoring',
    description: 'Bullet rewrites, keywords to add, and skill gap analysis per job.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="h-5 w-5">
        <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    ),
    title: 'Application Tracking',
    description: 'Track every job from Saved → Applied → Interviewing → Offer or Rejected.',
  },
];

const STEPS = [
  {
    step: '01',
    title: 'Upload your resume',
    description: 'Drag and drop your PDF. The parser auto-fills your profile in seconds.',
  },
  {
    step: '02',
    title: 'Get matched instantly',
    description: 'Our RAG pipeline scores you against 2,000+ listings and returns your top 5.',
  },
  {
    step: '03',
    title: 'Apply with confidence',
    description: 'Generate cover letters, tailor your resume, and track every application.',
  },
];

const GOOGLE_SSO_PATH = '/app#googleSignInButton';

function jumpTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen bg-parchment font-sans text-text-base">

      {/* ── Navbar ── */}
      <header className="sticky top-0 z-30 border-b border-border-light bg-parchment/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5 sm:px-8">
          <a href="#" className="flex items-center gap-2 text-sm font-bold tracking-tight text-text-base">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-teal text-xs font-bold text-white">J</span>
            JobMatch AI
          </a>
          <nav className="hidden items-center gap-1 sm:flex">
            {NAV_LINKS.map((l) => (
              <button
                key={l.id}
                onClick={() => jumpTo(l.id)}
                className="rounded-md px-3 py-1.5 text-sm text-text-sub transition hover:bg-parchment-section hover:text-text-base"
              >
                {l.label}
              </button>
            ))}
            <a
              href="/app"
              className="ml-3 rounded-lg bg-teal px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-teal-hover"
            >
              Get started
            </a>
            <a
              href={GOOGLE_SSO_PATH}
              className="ml-2 rounded-lg border border-border-mid bg-cream px-4 py-1.5 text-sm font-semibold text-text-base transition hover:bg-cream-hover"
            >
              Sign in with Google
            </a>
          </nav>
          <button className="sm:hidden p-1 text-text-sub" onClick={() => setMenuOpen(!menuOpen)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round"/>
            </svg>
          </button>
        </div>
        {menuOpen && (
          <div className="border-t border-border-light bg-parchment px-5 pb-4 pt-2 sm:hidden">
            {NAV_LINKS.map((l) => (
              <button
                key={l.id}
                onClick={() => { jumpTo(l.id); setMenuOpen(false); }}
                className="block w-full py-2 text-left text-sm text-text-sub"
              >
                {l.label}
              </button>
            ))}
            <a href="/app" className="mt-2 block rounded-lg bg-teal px-4 py-2 text-center text-sm font-semibold text-white">
              Get started
            </a>
            <a
              href={GOOGLE_SSO_PATH}
              className="mt-2 block rounded-lg border border-border-mid bg-cream px-4 py-2 text-center text-sm font-semibold text-text-base"
            >
              Sign in with Google
            </a>
          </div>
        )}
      </header>

      {/* ── Hero ── */}
      <section className="mx-auto max-w-6xl px-5 pb-20 pt-20 sm:px-8 sm:pt-28">
        <div className="mx-auto max-w-3xl text-center">
          <span className="mb-5 inline-flex items-center gap-1.5 rounded-full border border-teal/30 bg-teal-light px-3 py-1 text-xs font-semibold text-teal">
            <span className="h-1.5 w-1.5 rounded-full bg-teal" />
            RAG-powered · GPT-4o · Free to use
          </span>
          <h1 className="mb-5 text-5xl font-extrabold leading-[1.1] tracking-tight text-text-base sm:text-6xl">
            Find jobs that actually<br />
            <span className="text-teal">fit your resume.</span>
          </h1>
          <p className="mx-auto mb-8 max-w-xl text-lg leading-relaxed text-text-sub">
            Upload your resume, get AI-matched to real job listings, generate tailored cover letters, and track every application — in one place.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <a
              href="/app"
              className="rounded-lg bg-teal px-6 py-3 text-sm font-semibold text-white shadow-card transition hover:bg-teal-hover"
            >
              Get started free
            </a>
            <a
              href={GOOGLE_SSO_PATH}
              className="rounded-lg border border-border-mid bg-cream px-6 py-3 text-sm font-semibold text-text-base transition hover:bg-cream-hover"
            >
              Sign in with Google
            </a>
            <button
              onClick={() => jumpTo('how-it-works')}
              className="rounded-lg border border-border-mid bg-cream px-6 py-3 text-sm font-semibold text-text-base transition hover:bg-cream-hover"
            >
              See how it works
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="mx-auto mt-16 grid max-w-3xl grid-cols-2 gap-4 sm:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} className="rounded-xl border border-border-light bg-cream p-4 text-center shadow-card">
              <div className="text-xl font-extrabold text-text-base">{s.value}</div>
              <div className="mt-0.5 text-xs text-text-muted">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how-it-works" className="border-t border-border-light bg-parchment-section">
        <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
          <div className="mb-12 text-center">
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-teal">How it works</p>
            <h2 className="text-3xl font-extrabold tracking-tight text-text-base">Three steps to your next role</h2>
          </div>
          <div className="relative grid gap-8 sm:grid-cols-3">
            {/* connector line */}
            <div className="absolute left-0 right-0 top-8 hidden h-px bg-border-light sm:block" />
            {STEPS.map((s) => (
              <div key={s.step} className="relative flex flex-col items-center text-center">
                <div className="relative z-10 mb-4 flex h-16 w-16 items-center justify-center rounded-full border-2 border-teal/30 bg-cream shadow-card">
                  <span className="text-lg font-extrabold text-teal">{s.step}</span>
                </div>
                <h3 className="mb-2 font-semibold text-text-base">{s.title}</h3>
                <p className="text-sm leading-relaxed text-text-sub">{s.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="border-t border-border-light">
        <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
          <div className="mb-12 text-center">
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-teal">Features</p>
            <h2 className="text-3xl font-extrabold tracking-tight text-text-base">Everything you need, nothing you don't</h2>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="rounded-xl border border-border-light bg-cream p-5 shadow-card transition hover:border-teal/30 hover:shadow-card-md"
              >
                <div className="mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg bg-teal-light text-teal">
                  {f.icon}
                </div>
                <h3 className="mb-1.5 font-semibold text-text-base">{f.title}</h3>
                <p className="text-sm leading-relaxed text-text-sub">{f.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="border-t border-border-light bg-parchment-section">
        <div className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
          <div className="mx-auto max-w-xl rounded-2xl border border-teal/20 bg-teal-light px-8 py-12 text-center shadow-card">
            <h2 className="mb-3 text-2xl font-extrabold text-text-base">Ready to find your next role?</h2>
            <p className="mb-7 text-text-sub">Your resume is all you need to get started.</p>
            <a
              href="/app"
              className="inline-block rounded-lg bg-teal px-7 py-3 text-sm font-semibold text-white shadow-card transition hover:bg-teal-hover"
            >
              Get started free
            </a>
            <a
              href={GOOGLE_SSO_PATH}
              className="ml-3 inline-block rounded-lg border border-border-mid bg-cream px-7 py-3 text-sm font-semibold text-text-base transition hover:bg-cream-hover"
            >
              Sign in with Google
            </a>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t border-border-light">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
          <span className="flex items-center gap-2 text-sm font-bold text-text-base">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-teal text-xs font-bold text-white">J</span>
            JobMatch AI
          </span>
          <span className="text-xs text-text-muted">Built with RAG + GPT-4o</span>
        </div>
      </footer>

    </div>
  );
}
