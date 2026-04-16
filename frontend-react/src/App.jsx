import Button from './components/ui/Button';
import Card from './components/ui/Card';

const features = [
  {
    title: 'Resume parsing',
    description:
      'Upload a PDF and auto-fill your profile. Get an AI enhancement score with prioritised improvement guidance.',
  },
  {
    title: 'RAG job matching',
    description:
      'Semantic retrieval + GPT-4o ranking returns your top 5 matches from 2,000+ listings, scored out of 10.',
  },
  {
    title: 'Actionable insights',
    description:
      'Fit reasons, skill gaps, experience alignment, tailored bullet rewrites, and cover letter actions per job.',
  },
  {
    title: 'Application tracking',
    description:
      'Move jobs through Saved → Applied → Interviewing → Offer/Rejected with optional notes.',
  },
];

const workflow = [
  {
    step: '1',
    title: 'Upload your resume',
    description: 'Drag and drop a PDF. Fields are auto-filled so setup takes under a minute.',
  },
  {
    step: '2',
    title: 'Get AI-ranked matches',
    description: 'The RAG pipeline finds your top 5 jobs and scores each one out of 10.',
  },
  {
    step: '3',
    title: 'Take action',
    description: 'Generate cover letters, tailor resume bullets, track every application.',
  },
];

const allFeatures = [
  'Resume upload & PDF parsing',
  'RAG-based job matching',
  'Match score cards',
  'Cover letter generation',
  'Resume enhancement score',
  'Resume tailoring',
  'Application tracking',
  'Bookmarking',
  'Email results',
  'Dark mode',
  'Google sign-in',
  'Copy to clipboard',
];

function jumpTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export default function App() {
  return (
    <div className="min-h-screen font-sans text-text-base">

      {/* ── Header ── */}
      <header className="sticky top-0 z-20 border-b border-border-light bg-parchment/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3 sm:px-8">
          <div className="text-base font-bold tracking-tight text-text-base">
            JobMatch <span className="text-teal">AI</span>
          </div>
          <nav className="flex items-center gap-1 text-sm">
            <button
              onClick={() => jumpTo('how-it-works')}
              className="rounded-md px-3 py-1.5 text-text-sub transition hover:bg-parchment-section hover:text-text-base"
            >
              How it works
            </button>
            <button
              onClick={() => jumpTo('features')}
              className="rounded-md px-3 py-1.5 text-text-sub transition hover:bg-parchment-section hover:text-text-base"
            >
              Features
            </button>
            <a
              href="/"
              className="ml-2 rounded-lg border border-teal bg-teal px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-teal-hover"
            >
              Open app
            </a>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-5 pb-20 pt-14 sm:px-8">

        {/* ── Hero ── */}
        <section className="animate-rise mb-16 max-w-2xl">
          <span className="mb-4 inline-block rounded-full border border-teal/30 bg-teal-light px-3 py-1 text-xs font-semibold text-teal">
            RAG-powered · GPT-4o
          </span>
          <h1 className="mb-4 text-4xl font-extrabold leading-tight tracking-tight text-text-base sm:text-5xl">
            Match, tailor, and track<br />your job search in one place.
          </h1>
          <p className="mb-8 text-base leading-relaxed text-text-sub">
            Upload your resume, get semantically matched to real jobs, generate cover letters,
            tailor your bullets, and track every application — all from a single dashboard.
          </p>
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => (window.location.href = '/')}>Get started</Button>
            <Button variant="secondary" onClick={() => jumpTo('how-it-works')}>
              See how it works
            </Button>
          </div>
        </section>

        {/* ── What we built ── */}
        <section id="what-we-built" className="mb-16">
          <SectionLabel>What we built</SectionLabel>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {features.map((f, i) => (
              <Card key={f.title} className={`animate-rise [animation-delay:${i * 60}ms]`}>
                <h3 className="mb-1.5 font-semibold text-text-base">{f.title}</h3>
                <p className="text-sm leading-relaxed text-text-sub">{f.description}</p>
              </Card>
            ))}
          </div>
        </section>

        {/* ── How it works ── */}
        <section id="how-it-works" className="mb-16">
          <SectionLabel>How it works</SectionLabel>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            {workflow.map((step) => (
              <Card key={step.step} className="animate-rise">
                <div className="mb-3 inline-flex h-7 w-7 items-center justify-center rounded-full bg-teal text-xs font-bold text-white">
                  {step.step}
                </div>
                <h3 className="mb-1.5 font-semibold text-text-base">{step.title}</h3>
                <p className="text-sm leading-relaxed text-text-sub">{step.description}</p>
              </Card>
            ))}
          </div>
        </section>

        {/* ── Feature list ── */}
        <section id="features" className="mb-16">
          <SectionLabel>Full feature set</SectionLabel>
          <div className="mt-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {allFeatures.map((name) => (
              <div
                key={name}
                className="flex items-center gap-2.5 rounded-lg border border-border-light bg-cream px-4 py-3 text-sm text-text-sub"
              >
                <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-teal" />
                {name}
              </div>
            ))}
          </div>
        </section>

        {/* ── CTA ── */}
        <section className="rounded-xl border border-teal/20 bg-teal-light px-8 py-10 text-center">
          <h2 className="mb-2 text-2xl font-bold text-text-base">Ready to find your next role?</h2>
          <p className="mb-6 text-text-sub">Everything you need is already live.</p>
          <Button onClick={() => (window.location.href = '/')}>Open the app</Button>
        </section>

      </main>

      <footer className="border-t border-border-light py-6 text-center text-xs text-text-muted">
        JobMatch AI · Built with RAG + GPT-4o
      </footer>
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <h2 className="text-xs font-bold uppercase tracking-widest text-teal">{children}</h2>
  );
}
