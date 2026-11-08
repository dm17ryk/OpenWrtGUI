import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, postJson } from '../../api/client'
import type { DiscoveryState, FirmwareCheck, ProfileOut } from '../../api/types'
import { Help, HelpTip } from '../../help/Help'
import { HELP } from '../../help/topics'
import { ImportImage } from '../ImagesSection'

type Props = { routerId: string; state: DiscoveryState; onFlash: () => void }

/** The image this router matches, the firmware check, and the way to Flash (decision D11). */
export function ImageSection({ routerId, state, onFlash }: Props) {
  const client = useQueryClient()
  const [check, setCheck] = useState<FirmwareCheck | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isBusy, setBusy] = useState(false)
  const refresh = (): void => {
    void client.invalidateQueries({ queryKey: ['discovery', routerId] })
    void client.invalidateQueries({ queryKey: ['images'] })
  }
  const run = async (action: () => Promise<void>): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err))
    } finally {
      setBusy(false)
    }
  }
  const checkFirmware = (): Promise<void> =>
    run(async () => setCheck(await postJson<FirmwareCheck>(`/api/routers/${routerId}/discovery/firmware`)))
  const buildFromRom = (): Promise<void> =>
    run(async () => {
      await postJson<ProfileOut>(`/api/routers/${routerId}/images/rom`)
      refresh()
    })
  const profile = state.profile
  const fromImage = profile !== null && profile.sha256 !== 'rom'
  return (
    <section className="card stack" aria-labelledby="dimg-h">
      <div className="hrow">
        <h2 id="dimg-h">Image</h2>
        <Help topic={HELP.discoveryImage} />
      </div>
      {profile ? (
        <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
          <span>
            Matches <strong>{profile.board} {profile.revision}</strong>
            {fromImage ? '' : ' (built from this router’s /rom)'}
          </span>
          <span className="spacer" />
          <HelpTip topic={HELP.firmwareCheck}>
            <button className="btn" type="button" disabled={isBusy || !fromImage} onClick={() => void checkFirmware()}>
              Check firmware
            </button>
          </HelpTip>
          <HelpTip topic={HELP.flash}>
            <button className="btn" type="button" disabled={isBusy} onClick={onFlash}>
              Flash an image…
            </button>
          </HelpTip>
        </div>
      ) : (
        <>
          <div className="note">{state.match_note}</div>
          <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
            <ImportImage onImported={refresh} />
            <HelpTip topic={HELP.routerFamily}>
              <button className="btn" type="button" disabled={isBusy} onClick={() => void buildFromRom()}>
                Build from this router’s /rom
              </button>
            </HelpTip>
          </div>
        </>
      )}
      {check && <div className={check.matches ? 'note' : 'note x'}>{check.detail}</div>}
      {error && <div className="note x">{error}</div>}
    </section>
  )
}
