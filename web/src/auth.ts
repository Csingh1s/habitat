import { PublicClientApplication } from '@azure/msal-browser'

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID as string | undefined
const authority = import.meta.env.VITE_ENTRA_AUTHORITY as string | undefined
const scope = import.meta.env.VITE_ENTRA_API_SCOPE as string | undefined
export const authConfigured = Boolean(clientId && authority && scope)
let application: PublicClientApplication | null = null
let initialization: Promise<void> | null = null

async function client(): Promise<PublicClientApplication> {
  if (!authConfigured) throw new Error('Microsoft Entra sign-in is not configured for this deployment.')
  application ??= new PublicClientApplication({
    auth: { clientId: clientId!, authority: authority!, redirectUri: window.location.origin },
    cache: { cacheLocation: 'sessionStorage' },
  })
  initialization ??= application.initialize()
  await initialization
  return application
}

export async function isSignedIn(): Promise<boolean> {
  if (import.meta.env.DEV) return true
  const instance = await client()
  return instance.getAllAccounts().length > 0
}

export async function signIn(): Promise<void> {
  const instance = await client()
  const result = await instance.loginPopup({ scopes: [scope!] })
  instance.setActiveAccount(result.account)
}

export async function authorizationHeaders(): Promise<Record<string, string>> {
  if (import.meta.env.DEV) return {}
  const instance = await client()
  const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0]
  if (!account) throw new Error('Sign in to the inspector workspace before accessing records.')
  try {
    const token = await instance.acquireTokenSilent({ account, scopes: [scope!] })
    return { Authorization: `Bearer ${token.accessToken}` }
  } catch {
    throw new Error('Your sign-in requires renewal. Use Sign in again to continue.')
  }
}

export async function signOut(): Promise<void> {
  const instance = await client()
  await instance.logoutPopup({ account: instance.getActiveAccount() ?? instance.getAllAccounts()[0], mainWindowRedirectUri: window.location.origin })
}

const developmentSessionKey = 'habitat-development-email'

export function hasDevelopmentSession(): boolean {
  return import.meta.env.DEV && Boolean(sessionStorage.getItem(developmentSessionKey))
}

export async function signInDevelopment(email: string, password: string): Promise<void> {
  if (!import.meta.env.DEV) throw new Error('Local account sign-in is unavailable in this build.')
  let response: Response
  try {
    response = await fetch('/api/development/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim(), password }), signal: AbortSignal.timeout(15_000),
    })
  } catch {
    throw new Error('The local API could not be reached. Check the API on port 8001 and retry.')
  }
  const result: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = result && typeof result === 'object' && 'detail' in result ? result.detail : null
    throw new Error(typeof detail === 'string' ? detail : 'Sign-in could not be completed. Try again.')
  }
  if (!result || typeof result !== 'object' || !('authenticated' in result) || result.authenticated !== true || !('email' in result) || typeof result.email !== 'string') {
    throw new Error('The API returned an unexpected sign-in response.')
  }
  sessionStorage.setItem(developmentSessionKey, result.email)
}

export function signOutDevelopment(): void {
  if (import.meta.env.DEV) sessionStorage.removeItem(developmentSessionKey)
}