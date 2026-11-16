import { useEffect, useState } from 'react'
import { CircleAlert, Eye, EyeOff, House, LockKeyhole, LogIn, LoaderCircle } from 'lucide-react'
import App from './App'
import { authConfigured, hasDevelopmentSession, isSignedIn, signIn, signInDevelopment, signOutDevelopment } from './auth'

type SignInScreenProps = {
  checking: boolean
  busy: boolean
  configured: boolean
  error: string
  local?: boolean
  onAuthenticate: (email: string, password: string) => void
}

export function SignInScreen({ checking, busy, configured, error, local = false, onAuthenticate }: SignInScreenProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  return <main className="signin-screen">
    <section className="signin-panel" aria-label="Company sign-in">
      <a className="brand signin-brand" href="/" aria-label="Habitat home"><span className="brand-mark"><House size={24} /></span><span>habitat</span></a>
      <form className="signin-form" onSubmit={(event) => { event.preventDefault(); onAuthenticate(email, password) }}>
        <div className="signin-label">INSPECTOR WORKSPACE</div>
        <h1>Sign in</h1>
        <div className="signin-account"><LockKeyhole size={16} />{local ? 'Local account' : 'Company account'}</div>
        {local && <div className="signin-fields">
          <label className="signin-field" htmlFor="signin-email">Email<input id="signin-email" type="email" autoComplete="username" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} /></label>
          <label className="signin-field" htmlFor="signin-password">Password</label>
          <div className="signin-password"><input id="signin-password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} /><button type="button" className="icon-button" title={showPassword ? 'Hide password' : 'Show password'} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
        </div>}
        {checking ? <div className="signin-progress" role="status"><LoaderCircle className="spinning" size={20} />Restoring sign-in</div> : <button type="submit" className="primary-button signin-submit" disabled={busy || (!local && !configured)}><LogIn size={19} />{busy ? 'Signing in' : local ? 'Sign in' : 'Sign in with Microsoft'}</button>}
        {!local && !configured && <div className="signin-alert" role="alert"><CircleAlert size={18} /><span>Company sign-in is not configured. Contact your administrator.</span></div>}
        {error && <div className="signin-alert signin-error" role="alert"><CircleAlert size={18} /><span>{error}</span></div>}
      </form>
      <footer className="signin-footer"><span>Habitat</span><span><LockKeyhole size={13} />Authorized access only</span></footer>
    </section>
    <figure className="signin-visual"><img src="/canadian-home.svg" alt="Architectural drawing of a Canadian home" width={1200} height={860} /></figure>
  </main>
}

export default function AuthenticatedWorkspace() {
  const [authenticated, setAuthenticated] = useState(hasDevelopmentSession)
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
  async function authenticate(email: string, password: string) {
    setBusy(true); setError('')
    try {
      if (import.meta.env.DEV) await signInDevelopment(email, password)
      else await signIn()
      setAuthenticated(true)
    }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Sign-in could not be completed.') }
    finally { setBusy(false) }
  }
  if (authenticated) return <App onDevelopmentSignOut={() => { signOutDevelopment(); setAuthenticated(false) }} />
  return <SignInScreen checking={checking} busy={busy} configured={authConfigured} error={error} local={import.meta.env.DEV} onAuthenticate={(email, password) => void authenticate(email, password)} />
}