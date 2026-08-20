// Who is allowed to change things, and what the UI does about it.
//
// The app is handed to testers with any Google account. Reading is open to
// them by design — that IS the test. Writing is not: rejecting a detection or
// deleting a reference image changes what the detector learns, permanently and
// for everyone. Both are gated server-side on brand membership
// (main.py._require_brand_member, firestore.rules). This module mirrors that
// gate in the UI so a non-member sees "read-only" instead of discovering it
// through a 403 after the click.
//
// The mirror is cosmetic. Anything that relies on `canWrite` for safety rather
// than for clarity is a bug — the server is the authority.

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fbIsBrandMember, fbBrandHasMembers } from './firestore'
import { useAuth } from './auth'

type Membership = {
  /** Undefined while the check is in flight — render neither state yet. */
  isMember: boolean | undefined
  /** Convenience: false while loading, so buttons start disabled, not enabled. */
  canWrite: boolean
  /**
   * The brand has no members at all, so it is up for grabs. The first caller of
   * bootstrap becomes its owner — which is why this exists: the Run scan button
   * is what calls bootstrap, so hiding it from non-members would leave a fresh
   * brand with no way for anyone to ever claim it.
   */
  brandUnclaimed: boolean
}

const Ctx = createContext<Membership>({ isMember: undefined, canWrite: false, brandUnclaimed: false })

export function MembershipProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [isMember, setIsMember] = useState<boolean | undefined>(undefined)
  const [brandUnclaimed, setBrandUnclaimed] = useState(false)

  useEffect(() => {
    if (!user) { setIsMember(undefined); setBrandUnclaimed(false); return }
    let cancelled = false
    setIsMember(undefined)
    fbIsBrandMember(user.uid)
      .then(async (ok) => {
        if (cancelled) return
        setIsMember(ok)
        // Only worth asking when we are NOT a member: a member proves the
        // brand is claimed, so the second read would be pure waste.
        if (!ok) {
          const claimed = await fbBrandHasMembers()
          if (!cancelled) setBrandUnclaimed(!claimed)
        } else {
          setBrandUnclaimed(false)
        }
      })
      .catch(() => { if (!cancelled) { setIsMember(false); setBrandUnclaimed(false) } })
    return () => { cancelled = true }
  }, [user])

  return (
    <Ctx.Provider value={{ isMember, canWrite: isMember === true, brandUnclaimed }}>
      {children}
    </Ctx.Provider>
  )
}

export function useMembership(): Membership {
  return useContext(Ctx)
}

/** Banner shown once per page for read-only visitors. */
export function ReadOnlyNotice() {
  const { isMember, brandUnclaimed } = useMembership()
  if (isMember !== false || brandUnclaimed) return null
  return (
    <div className="mb-6 border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-4 py-3 text-[12px] leading-relaxed">
      <span className="uppercase tracking-[0.12em] text-[10px] font-medium text-[var(--color-accent)] mr-2">
        Read-only
      </span>
      You can browse and open everything. Actions that would change the live
      data — rejecting a hit, editing reference images, starting a scan — are
      disabled for your account. Nothing you click here can affect what the
      detector learns.
    </div>
  )
}
