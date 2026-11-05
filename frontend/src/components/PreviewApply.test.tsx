import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { HELP } from '../help/topics'
import { PreviewApply } from './PreviewApply'

const LINES = ["uci set wireless.radio0.channel='6'", 'uci commit wireless', 'wifi down radio0; wifi up radio0']

function renderPreview(extra: Partial<Parameters<typeof PreviewApply>[0]> = {}) {
  const onApply = vi.fn()
  render(
    <PreviewApply
      heading="Commands that will run on AP2"
      lines={LINES}
      warnings={['OpenWrt is already on air on AP1 · bench.']}
      error={null}
      isBusy={false}
      applyLabel="Apply to AP2"
      onApply={onApply}
      helpTopic={HELP.stepInstallKey}
      {...extra}
    />,
  )
  return onApply
}

test('shows the exact lines and warnings, and applies', async () => {
  const onApply = renderPreview()
  expect(screen.getByRole('region', { name: 'Command preview' }).textContent).toBe(LINES.join('\n'))
  expect(screen.getByText('OpenWrt is already on air on AP1 · bench.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Apply to AP2' }))
  expect(onApply).toHaveBeenCalledTimes(1)
})

test('an error is an alert and a busy apply cannot be pressed twice', () => {
  renderPreview({ error: 'Channel 14 is not allowed in country IL', isBusy: true })
  expect(screen.getByRole('alert')).toHaveTextContent('Channel 14 is not allowed in country IL')
  expect(screen.getByRole('button', { name: 'Applying…' })).toBeDisabled()
})

test('nothing to send means nothing to press', () => {
  renderPreview({ lines: [] })
  expect(screen.queryByRole('region', { name: 'Command preview' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Apply to AP2' })).toBeDisabled()
})
