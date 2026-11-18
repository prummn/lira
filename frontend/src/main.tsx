import { Component, StrictMode, useLayoutEffect } from 'react'
import type { ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

declare global {
  interface Window { __liraStartup?: { ready(): void; fail(): void } }
}

class StartupBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error) {
    console.error('LIRA could not render the workspace', error)
    window.__liraStartup?.fail()
  }
  render() { return this.state.failed ? null : this.props.children }
}

function WorkspaceEntry() {
  // Only a committed React tree can dismiss the dependency-free startup view.
  useLayoutEffect(() => { window.__liraStartup?.ready() }, [])
  return <App />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><StartupBoundary><WorkspaceEntry /></StartupBoundary></StrictMode>
)
