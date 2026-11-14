import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AuthenticatedWorkspace from './AuthenticatedWorkspace.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AuthenticatedWorkspace />
  </StrictMode>,
)
