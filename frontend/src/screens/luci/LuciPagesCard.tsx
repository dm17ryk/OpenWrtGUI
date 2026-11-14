import { Link } from 'react-router'
import { ApiError } from '../../api/client'
import type { LuciPageView } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'
import { luciPageLink, nativeScreen, useLuciPages } from './pages'

function InThisApp({ page, routerId }: { page: LuciPageView; routerId: string }) {
  const screen = page.native ? nativeScreen(page.native, routerId, page.path) : null
  if (!screen) return <span className="b har">no screen here yet</span>
  return (
    <>
      <span className="b air">native</span> <Link to={screen.to}>{screen.label}</Link>
    </>
  )
}

/** Every LuCI page the router offers, and where it lives in this app. */
export function LuciPagesCard({ routerId, short }: { routerId: string; short: string }) {
  const pages = useLuciPages(routerId)
  const error = pages.error instanceof ApiError ? pages.error.detail : pages.error ? String(pages.error) : null
  const shown = (pages.data ?? []).filter((p) => p.available !== false)
  const lacking = (pages.data ?? []).filter((p) => p.available === false)
  return (
    <section className="card stack" aria-labelledby="luci-h">
      <div className="row" style={{ alignItems: 'baseline' }}>
        <div className="hrow">
          <h2 id="luci-h">LuCI pages on {short}</h2>
          <Help topic={HELP.luciWhich} />
        </div>
        <span className="muted">
          every page LuCI shows on this router, and where it lives in this app. A page with no screen here yet opens in
          LuCI, inside the app.
        </span>
      </div>
      {error && <div className="note x">{error}</div>}
      {pages.data && pages.data.length === 0 && <div className="muted">This router has no LuCI menu.</div>}
      {pages.data && pages.data.length > 0 && (
        <div className="scroll-x">
          <table className="tbl">
            <thead>
              <tr>
                <th>LuCI package</th>
                <th>Page</th>
                <th>In this app</th>
                <th>
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.path}>
                  <td className="mono">{p.package}</td>
                  <td>{p.label}</td>
                  <td>
                    <InThisApp page={p} routerId={routerId} />
                  </td>
                  <td>
                    {p.native === null && (
                      <Link className="btn" to={luciPageLink(routerId, p.path)} aria-label={`Open ${p.label} in LuCI`}>
                        Open in LuCI
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lacking.length > 0 && (
        <details>
          <summary>Not on this router ({lacking.length})</summary>
          <ul aria-label={`LuCI pages not on ${short}`}>
            {lacking.map((p) => (
              <li key={p.path}>
                {p.label}: {p.missing}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
