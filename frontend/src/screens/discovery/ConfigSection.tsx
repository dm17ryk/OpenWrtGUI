import type { DiscoveryState } from '../../api/types'
import { Help } from '../../help/Help'
import { HELP } from '../../help/topics'

/** Config changed (spec 7.8): per config with an image default, each option the router changed. */
export function ConfigSection({ state }: { state: DiscoveryState }) {
  const firstBoot = state.configs.filter((c) => c.first_boot)
  const changed = state.configs.filter((c) => !c.first_boot)
  return (
    <section className="card stack" aria-labelledby="cfg-h">
      <div className="hrow">
        <h2 id="cfg-h">Config changed</h2>
        <Help topic={HELP.configChanged} />
      </div>
      {changed.length === 0 && <div className="muted">No config differs from the image's defaults.</div>}
      {changed.map((c) => (
        <div key={c.config} className="stack" style={{ gap: 4, overflowX: 'auto' }}>
          <div className="eyebrow">{c.config}</div>
          <table>
            <thead>
              <tr>
                <th>Option</th>
                <th>Image</th>
                <th>Router</th>
              </tr>
            </thead>
            <tbody>
              {c.changes.map((o) => (
                <tr key={o.key}>
                  <td className="mono" style={{ overflowWrap: 'anywhere' }}>
                    {o.key}
                  </td>
                  <td className="mono">{o.image ?? '—'}</td>
                  <td className="mono">{o.router ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {firstBoot.map((c) => (
        <div key={c.config} className="muted">
          {c.config}: created at first boot (not in the image)
        </div>
      ))}
    </section>
  )
}
