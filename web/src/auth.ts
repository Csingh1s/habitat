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