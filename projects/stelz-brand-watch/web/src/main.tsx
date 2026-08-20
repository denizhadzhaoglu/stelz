import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './lib/auth'
import { MembershipProvider } from './lib/membership'
import { signalReport } from './lib/signal'
import type { DetectionRow } from './lib/types'

// Dev-only: `signalReport()` in the browser console prints the tagged/untagged
// mix over whatever the dashboard last cached. Uses the same classifier the UI
// does, so the number can never drift from what's on screen.
if (import.meta.env.DEV) {
  ;(window as unknown as { signalReport: () => void }).signalReport = () => {
    const raw = localStorage.getItem('spotthebrand:dashboard-cache:v2')
    if (!raw) return console.warn('No cached dashboard data — load the dashboard once first.')
    signalReport((JSON.parse(raw).detections ?? []) as DetectionRow[])
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <MembershipProvider>
          <App />
        </MembershipProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
