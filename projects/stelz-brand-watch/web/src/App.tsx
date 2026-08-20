import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, Route, Routes, Navigate, useLocation } from 'react-router-dom'
import { InboxBell } from './components/InboxBell'
import { useAuth } from './lib/auth'

import Home from './pages/Home'
import Creator from './pages/Creator'
import Sounds from './pages/Sounds'
import ProjectPage from './pages/Project'
import LowlandsPage from './pages/Lowlands'
import Settings from './pages/Settings'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Signup from './pages/Signup'
import Terms from './pages/Terms'
import Privacy from './pages/Privacy'

// Primary routes:
//   /              Home (tabs: Dashboard · Feed · Review · Creators)
//   /lowlands      Client roster tab — import screen until the project
//                  exists, then a redirect to its project page
//   /sounds(/:key) Sound leaderboard + drill-down
//   /creators/:id  Creator detail
//   /projects/:id  Project detail (tracked creator groups)
//   /settings      Settings
//   /login + /signup + /landing  Public auth + marketing
//   /terms /privacy              Static legal (no nav)

const NAV: { to: string; label: string; matchPrefix?: string }[] = [
  { to: '/', label: 'Home' },
  // matchPrefix '/projects': the Lowlands tab stays lit while reading any
  // project roster — the tab redirects there once the roster exists.
  { to: '/lowlands', label: 'Lowlands', matchPrefix: '/projects' },
  { to: '/sounds', label: 'Sounds', matchPrefix: '/sounds' },
  { to: '/settings', label: 'Settings' },
]

const OLD_ROUTE_REDIRECTS: Record<string, string> = {
  '/today': '/',
  '/feed': '/',
  '/dashboard': '/',
  '/highlights': '/',
  '/reports': '/',
  '/outreach': '/',
  '/discover': '/',
  '/welcome': '/',
  '/checkout': '/settings',
  '/accept-invite': '/',
  '/onboarding': '/settings',
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/landing" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />

      {/* Legacy redirects (so old bookmarks don't 404) */}
      {Object.entries(OLD_ROUTE_REDIRECTS).map(([from, to]) => (
        <Route key={from} path={from} element={<Navigate to={to} replace />} />
      ))}

      {/* App (protected) */}
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route path="/" element={<Home />} />
        <Route path="/creators/:handle" element={<Creator />} />
        <Route path="/sounds" element={<Sounds />} />
        <Route path="/sounds/:soundKey" element={<Sounds />} />
        <Route path="/lowlands" element={<LowlandsPage />} />
        <Route path="/projects/:projectId" element={<ProjectPage />} />
        <Route path="/settings" element={<Settings />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) {
    return <div className="min-h-screen flex items-center justify-center text-[12px] text-[var(--color-ink-subtle)]">Loading…</div>
  }
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  return <>{children}</>
}

function AppLayout() {
  const { pathname } = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  useEffect(() => { setNavOpen(false) }, [pathname])

  return (
    <div className="min-h-screen flex relative">
      {/* Mobile top bar — navy, like the Stelz announcement bar */}
      <div className="lg:hidden fixed top-0 inset-x-0 h-12 z-30 bg-[var(--color-ink)] flex items-center px-4 justify-between">
        <button onClick={() => setNavOpen((v) => !v)} className="w-8 h-8 flex items-center justify-center -ml-2">
          <span className="block w-4 h-px bg-white relative before:content-[''] before:absolute before:w-4 before:h-px before:bg-white before:-top-1.5 after:content-[''] after:absolute after:w-4 after:h-px after:bg-white after:top-1.5"></span>
        </button>
        <SidebarLogo />
        <div className="text-white"><InboxBell /></div>
      </div>

      {navOpen && <div className="lg:hidden fixed inset-0 bg-black/20 z-30" onClick={() => setNavOpen(false)} />}

      {/* Navy sidebar — the Stelz hero panel */}
      <aside
        className={`fixed lg:sticky top-0 left-0 h-screen w-60 shrink-0 bg-[var(--color-ink)] text-white flex flex-col z-40 transition-transform lg:transition-none ${
          navOpen ? 'translate-x-0' : '-translate-x-full'
        } lg:translate-x-0`}
      >
        <div className="h-16 flex items-center justify-between px-5 border-b border-white/10">
          <SidebarLogo />
          <div className="hidden lg:block text-white">
            <InboxBell />
          </div>
        </div>

        <BrandSwitcher />

        <nav className="flex-1 py-3 overflow-y-auto">
          {NAV.map((n) => {
            const active = pathname === n.to || (n.matchPrefix && pathname.startsWith(n.matchPrefix))
            return (
              <NavLink
                key={n.to}
                to={n.to}
                className={`block px-5 py-2.5 text-[12px] uppercase tracking-[0.08em] font-medium border-l-2 transition-colors ${
                  active
                    ? 'border-[var(--color-accent)] bg-white/5 text-white'
                    : 'border-transparent text-white/55 hover:text-white'
                }`}
              >
                {n.label}
              </NavLink>
            )
          })}
        </nav>

        <UserStrip />
      </aside>

      <main className="flex-1 min-w-0 pt-12 lg:pt-0">
        <Outlet />
      </main>
    </div>
  )
}

function SidebarLogo() {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="w-9 h-9 rounded-full bg-white flex items-center justify-center shrink-0">
        <img src="/stelz-logo.png" alt="" className="w-7 h-7 object-contain" />
      </span>
      <span className="stelz-display text-[15px] text-white leading-none">Stëlz</span>
    </span>
  )
}

function BrandSwitcher() {
  return (
    <div className="px-5 py-4 border-b border-white/10">
      <div className="text-[9px] uppercase tracking-widest text-[var(--color-accent)] font-medium mb-1.5">Community Watch</div>
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-white">Stëlz Hard Drinks</span>
      </div>
    </div>
  )
}

function UserStrip() {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  return (
    <div className="px-5 py-3 border-t border-white/10 relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between text-[11px] text-white/50 hover:text-white"
      >
        <span className="truncate text-left">{user?.email ?? '—'}</span>
        <span className="ml-2">▾</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-3 right-3 mb-1 z-20 bg-[var(--color-surface)] border border-[var(--color-border-strong)]">
            <button
              onClick={async () => { setOpen(false); await signOut(); window.location.href = '/login' }}
              className="w-full px-3 py-2 text-left text-[12px] hover:bg-[var(--color-bg)]"
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  )
}
