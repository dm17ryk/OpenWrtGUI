import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useLocation } from 'react-router'

type Props = { children: ReactNode }
type State = { message: string | null }

/** A screen that throws shows what happened; the header, the guard banner and the other screens stay (v1.0c D8). */
export class ScreenBoundary extends Component<Props, State> {
  state: State = { message: null }

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof Error ? error.message : String(error) }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    if (import.meta.env.DEV) console.error('screen error', error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.message === null) return this.props.children
    return (
      <main className="wrap">
        <div className="note x" role="alert">
          {`This screen hit an error: ${this.state.message}. The other screens still work.`}
        </div>
        <button className="btn" type="button" onClick={() => this.setState({ message: null })}>
          Try again
        </button>
      </main>
    )
  }
}

/** One boundary per screen: moving to another screen starts it clean. */
export function RouteBoundary({ children }: Props) {
  const { pathname } = useLocation()
  return <ScreenBoundary key={pathname}>{children}</ScreenBoundary>
}
