import { useEffect, useState } from 'react'
import { House, LogIn, LoaderCircle } from 'lucide-react'
import App from './App'
import { authConfigured, isSignedIn, signIn } from './auth'

export default function AuthenticatedWorkspace() {
  const [authenticated, setAuthenticated] = useState(import.meta.env.DEV)
  const [checking, setChecking] = useState(!import.meta.env.DEV && authConfigured)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (import.meta.env.DEV || !authConfigured) return
    let active = true
    isSignedIn().then((value) => { if (active) setAuthenticated(value) })
      .catch((failure: unknown) => { if (active) setError(failure instanceof Error ? failure.message : 'Sign-in could not be restored.') })
      .finally(() => { if (active) setChecking(false) })
    return () => { active = false }
  }, [])
  async function authenticate() {
    setBusy(true); setError('')
    try { await signIn(); setAuthenticated(true) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Sign-in could not be completed.') }
    finally { setBusy(false) }
  }
  if (authenticated) return <App />
  return <main className="signin-screen"><div className="brand-mark"><House size={26} /></div><h1>Habitat</h1><h2>Inspector Workspace</h2>
    {checking ? <LoaderCircle className="spinning" aria-label="Restoring sign-in" /> : <button className="primary-button" disabled={busy || !authConfigured} onClick={() => void authenticate()}><LogIn size={18} />{busy ? 'Signing in' : 'Sign in with Microsoft'}</button>}
    {!authConfigured && <p role="alert">This deployment is missing its Microsoft Entra configuration.</p>}
    {error && <p role="alert">{error}</p>}
  </main>
}