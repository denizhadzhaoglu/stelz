import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as fbSignOut,
  type User,
} from 'firebase/auth'
import { fbAuth } from './firebase'

type AuthState = {
  user: User | null
  loading: boolean
  signInGoogle: () => Promise<User>
  signInEmail: (email: string, password: string) => Promise<User>
  signUpEmail: (email: string, password: string) => Promise<User>
  signOut: () => Promise<void>
  getIdToken: () => Promise<string | null>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const off = onAuthStateChanged(fbAuth, (u) => {
      setUser(u)
      setLoading(false)
    })
    return off
  }, [])

  const signInGoogle = async () => {
    const provider = new GoogleAuthProvider()
    const { user } = await signInWithPopup(fbAuth, provider)
    return user
  }
  const signInEmail = async (email: string, password: string) => {
    const { user } = await signInWithEmailAndPassword(fbAuth, email, password)
    return user
  }
  const signUpEmail = async (email: string, password: string) => {
    const { user } = await createUserWithEmailAndPassword(fbAuth, email, password)
    return user
  }
  const signOut = async () => {
    await fbSignOut(fbAuth)
  }
  const getIdToken = async () => {
    if (!fbAuth.currentUser) return null
    return fbAuth.currentUser.getIdToken()
  }

  return (
    <Ctx.Provider value={{ user, loading, signInGoogle, signInEmail, signUpEmail, signOut, getIdToken }}>
      {children}
    </Ctx.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

// Friendly error mapper for Firebase Auth codes
export function authErrorMessage(err: unknown): string {
  const code = (err as { code?: string })?.code ?? ''
  switch (code) {
    case 'auth/invalid-email': return 'Invalid email address.'
    case 'auth/user-not-found': return 'No account with that email.'
    case 'auth/wrong-password':
    case 'auth/invalid-credential': return 'Email or password is incorrect.'
    case 'auth/email-already-in-use': return 'An account with this email already exists.'
    case 'auth/weak-password': return 'Password must be at least 6 characters.'
    case 'auth/popup-closed-by-user': return 'Sign-in cancelled.'
    case 'auth/network-request-failed': return 'Network error. Check your connection.'
    case 'auth/too-many-requests': return 'Too many attempts. Try again later.'
    default: return (err as { message?: string })?.message ?? 'Sign-in failed.'
  }
}
