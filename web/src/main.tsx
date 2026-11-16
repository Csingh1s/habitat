import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/public-sans/latin-400.css'
import '@fontsource/public-sans/latin-600.css'
import AuthenticatedWorkspace from './AuthenticatedWorkspace.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthenticatedWorkspace />
  </StrictMode>,
)
