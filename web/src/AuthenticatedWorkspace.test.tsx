import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SignInScreen } from './AuthenticatedWorkspace'
import { hasDevelopmentSession, signInDevelopment, signOutDevelopment } from './auth'

const defaults = { checking: false, busy: false, configured: true, error: '', onAuthenticate: () => {} }
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('company sign-in screen', () => {
  it('offers email/password only in the local account mode', () => {
    const html = renderToStaticMarkup(<SignInScreen {...defaults} local configured={false} />)
    expect(html).toContain('type="email"')
    expect(html).toContain('type="password"')
    expect(html).toContain('Show password')
    expect(html).not.toContain('Sign in with Microsoft')
    expect(html).not.toContain('Company sign-in is not configured')
    expect(html).not.toContain('disabled=""')
  })

  it('offers only the real Microsoft sign-in flow', () => {
    const html = renderToStaticMarkup(<SignInScreen {...defaults} />)
    expect(html).toContain('Sign in with Microsoft')
    expect(html).toContain('/canadian-home.svg')
    expect(html).toContain('Architectural drawing of a Canadian home')
    expect(html).not.toContain('/residential-exterior.jpg')
    expect(html).not.toContain('type="password"')
    expect(html).not.toContain('type="email"')
  })

  it('fails closed when company authentication is unconfigured', () => {
    const html = renderToStaticMarkup(<SignInScreen {...defaults} configured={false} />)
    expect(html).toContain('disabled=""')
    expect(html).toContain('Company sign-in is not configured')
  })

  it('renders restoration and authentication error states', () => {
    const html = renderToStaticMarkup(<SignInScreen {...defaults} checking error="Sign-in expired" />)
    expect(html).toContain('role="status"')
    expect(html).toContain('Restoring sign-in')
    expect(html).toContain('Sign-in expired')
    expect(html).not.toContain('Sign in with Microsoft')
  })
})

describe('local account session', () => {
  it('checks the API and stores only the email, then signs out', async () => {
    const stored = new Map<string, string>()
    vi.stubEnv('DEV', true)
    vi.stubGlobal('sessionStorage', { getItem: (key: string) => stored.get(key), setItem: (key: string, value: string) => stored.set(key, value), removeItem: (key: string) => stored.delete(key) })
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ authenticated: true, email: 'inspector@example.com' }))
    vi.stubGlobal('fetch', fetchMock)
    expect(hasDevelopmentSession()).toBe(false)
    await signInDevelopment('inspector@example.com', 'test-password')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/development/login')
    expect(hasDevelopmentSession()).toBe(true)
    expect(Array.from(stored.values())).toEqual(['inspector@example.com'])
    signOutDevelopment()
    expect(hasDevelopmentSession()).toBe(false)
  })

  it('does not save a session after rejected credentials', async () => {
    vi.stubEnv('DEV', true)
    const storage = { setItem: vi.fn() }
    vi.stubGlobal('sessionStorage', storage)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ detail: 'Email or password is incorrect.' }, { status: 401 })))
    await expect(signInDevelopment('inspector@example.com', 'wrong-password')).rejects.toThrow('Email or password is incorrect.')
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it('never sends local passwords in a production build', async () => {
    vi.stubEnv('DEV', false)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await expect(signInDevelopment('inspector@example.com', 'test-password')).rejects.toThrow('unavailable')
    expect(fetchMock).not.toHaveBeenCalled()
    expect(hasDevelopmentSession()).toBe(false)
  })
})