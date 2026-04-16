import Button from './components/ui/Button';
import Card from './components/ui/Card';

const heroBadges = [
  'Resume parsing + scoring',
  'RAG semantic matching',
  'Cover letter generation',
  'Resume tailoring',
  'Application tracking',
];

const builtCards = [
  {
    id: '01',
    title: 'Resume parsing',
    description:
      'Upload PDF, auto-fill profile fields, and get an AI enhancement score with prioritized improvement guidance.',
  },
  {
    id: '02',
    title: 'RAG job matching',
    description:
      'Semantic retrieval plus GPT-4o ranking returns top 5 matches from 2000+ listings, scored out of 10.',
  },
  {
    id: '03',
    title: 'Actionable insights',
    description:
      'Every result includes fit reasons, skill gaps, experience alignment, tailored bullet rewrites, and cover letter actions.',
  },
  {
    id: '04',
    title: 'Full workflow',
    description:
      'Track saved → applied → interviewing → offer/rejected, with bookmarks, email export, and persistent dark mode.',
  },
];

const workflow = [
  {
    step: '1',
    title: 'Upload your resume',
    description: 'Drag-and-drop PDF parsing auto-fills profile data so setup is fast and structured.',
  },
  {
    step: '2',
    title: 'Get AI-ranked matches',
    description: 'RAG pipeline finds top 5 jobs and scores each role out of 10 for transparent ranking.',
  },
  {
    step: '3',
    title: 'Take action',
    description:
      'Generate cover letters, tailor resume bullets, and move jobs through the application tracker.',
  },
];

const fullFeatureSet = [
  {
    icon: '📄',
    title: 'Resume Upload & PDF Parsing',
    description: 'Drag-and-drop PDF parsing that auto-fills your profile form.',
  },
  {
    icon: '🧠',
    title: 'RAG-based Job Matching',
    description: 'Pinecone semantic retrieval + GPT-4o ranking for top 5 matches.',
  },
  {
    icon: '🎯',
    title: 'Match Score Cards',
    description: 'Color-coded scores, fit reasons, skill gaps, and next-step guidance.',
  },
  {
    icon: '✉️',
    title: 'Cover Letter Generation',
    description: 'Per-job tailored letters with professional/friendly/concise tone options.',
  },
  {
    icon: '📈',
    title: 'Resume Enhancement',
    description: '0-100 AI audit with ATS, quantification, formatting, and priority suggestions.',
  },
  {
    icon: '🛠️',
    title: 'Resume Tailoring',
    description: 'Bullet rewrites, skills to add/emphasize, and keyword-gap analysis.',
  },
  {
    icon: '🗂️',
    title: 'Application Tracking',
    description: 'Track status from saved to offer/rejected with optional notes.',
  },
  {
    icon: '⭐',
    title: 'Bookmarking',
    description: 'Persist starred jobs across sessions for quick follow-up.',
  },
  {
    icon: '📧',
    title: 'Email Results',
    description: 'Send your matched job report to yourself instantly.',
  },
  {
    icon: '🌙',
    title: 'Dark Mode',
    description: 'Theme preference persists via localStorage.',
  },
  {
    icon: '🔐',
    title: 'Google Sign-In + Local Fallback',
    description: 'Authenticated flow with session persistence and fallback sign-in.',
  },
  {
    icon: '📋',
    title: 'Copy to Clipboard',
    description: 'Copy job details in one click for applications and outreach.',
  },
];

function jumpTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export default function App() {
  return (
    <div className="min-h-screen bg-canvas bg-mesh text-ink">
      <div className="mx-auto max-w-6xl px-5 pb-16 pt-6 sm:px-8">
        <header className="sticky top-0 z-20 mb-8 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-slate-950/65 px-4 py-3 backdrop-blur-xl">
          <div className="text-lg font-extrabold tracking-tight">JobMatch AI</div>
          <nav className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
            <button onClick={() => jumpTo('what-we-built')} className="hover:text-white">What We Built</button>
            <button onClick={() => jumpTo('workflow')} className="hover:text-white">Workflow</button>
            <button onClick={() => jumpTo('feature-set')} className="hover:text-white">Full Feature Set</button>
            <a href="/" className="rounded-full border border-white/15 px-4 py-1.5 hover:bg-white/10">Open Current App</a>
          </nav>
        </header>

        <section className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
          <Card className="animate-rise">
            <p className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-emerald-300">RAG-powered job search</p>
            <h1 className="mb-4 max-w-3xl text-4xl font-extrabold leading-tight tracking-tight text-white sm:text-6xl">
              One AI workspace for matching, tailoring, and applying.
            </h1>
            <p className="max-w-2xl text-slate-300">
              Upload your resume, get RAG-matched to real jobs, generate cover letters, tailor your resume, and track your applications - all in one place.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => jumpTo('workflow')}>See Workflow</Button>
              <Button onClick={() => (window.location.href = '/')}>Get Started</Button>
            </div>
            <div className="mt-6 flex flex-wrap gap-2">
              {heroBadges.map((badge) => (
                <span key={badge} className="rounded-full border border-emerald-300/30 bg-emerald-300/10 px-3 py-1 text-xs font-semibold text-emerald-200">
                  {badge}
                </span>
              ))}
            </div>
          </Card>

          <Card className="animate-rise [animation-delay:120ms]">
            <p className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-mango">Product snapshot</p>
            <h2 className="mb-3 text-2xl font-bold text-white">What's inside</h2>
            <ul className="grid grid-cols-1 gap-2 text-sm text-slate-200">
              {[
                'Resume upload',
                'AI scoring',
                'RAG matching',
                'Cover letters',
                'Resume tailoring',
                'Application tracking',
                'Bookmarks',
                'Email export',
              ].map((item) => (
                <li key={item} className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
                  {item}
                </li>
              ))}
            </ul>
          </Card>
        </section>

        <section id="what-we-built" className="mt-10">
          <div className="mb-5 max-w-3xl">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-300">Product summary</p>
            <h2 className="mt-2 text-3xl font-extrabold text-white">What we built</h2>
            <p className="mt-2 text-slate-300">
              Your landing page now reflects the actual shipped capabilities, not a future roadmap.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {builtCards.map((card) => (
              <Card key={card.id} className="animate-rise">
                <p className="mb-2 text-xs font-bold tracking-[0.15em] text-emerald-300">{card.id}</p>
                <h3 className="mb-2 text-xl font-bold text-white">{card.title}</h3>
                <p className="text-sm text-slate-300">{card.description}</p>
              </Card>
            ))}
          </div>
        </section>

        <section id="workflow" className="mt-12">
          <div className="mb-5 max-w-3xl">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-mango">User journey</p>
            <h2 className="mt-2 text-3xl font-extrabold text-white">How it works</h2>
            <p className="mt-2 text-slate-300">Fast path from resume ingestion to job actions.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {workflow.map((step) => (
              <Card key={step.step} className="animate-rise">
                <div className="mb-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-neon text-sm font-bold text-slate-950">
                  {step.step}
                </div>
                <h3 className="mb-2 text-lg font-bold text-white">{step.title}</h3>
                <p className="text-sm text-slate-300">{step.description}</p>
              </Card>
            ))}
          </div>
        </section>

        <section id="feature-set" className="mt-12">
          <div className="mb-5 max-w-3xl">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-rose">Shipped capabilities</p>
            <h2 className="mt-2 text-3xl font-extrabold text-white">Full Feature Set</h2>
            <p className="mt-2 text-slate-300">All 12 features are already live in your current backend-powered app.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {fullFeatureSet.map((feature) => (
              <Card key={feature.title} className="animate-rise">
                <h3 className="mb-2 text-lg font-bold text-white">
                  <span className="mr-2">{feature.icon}</span>
                  {feature.title}
                </h3>
                <p className="text-sm text-slate-300">{feature.description}</p>
              </Card>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
