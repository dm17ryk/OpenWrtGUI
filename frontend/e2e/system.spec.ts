import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

// a throwaway public key (tools/record_fixtures.py PLACEHOLDER_KEYS): never a real one, the repository is public
const THROWAWAY_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEeN2gEjAeD8LVkj/gTQDSxOcPCD5IPg87e/h53vQKLn user@pc'

test('the System screen shows the model, the overview and three live charts', async ({ page }) => {
  await open(page, '/routers/ap1/system')
  await expect(page.getByRole('heading', { name: 'System', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Overview' })).toContainText('D-Link DWR-921 C3 (U-Boot)')
  await expect(page.locator('.rf-chart canvas')).toHaveCount(3)
  await noHorizontalScroll(page)
  for (const tab of ['Logs', 'Processes', 'Diagnostics', 'System and time', 'Access', 'Services', 'Scheduled tasks', 'LEDs', 'Mount points', 'Backup and reboot']) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
    await noHorizontalScroll(page)
  }
})

test('a host name change and back, a service restart and a backup in the simulator', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulator')
  await open(page, '/routers/ap1/system?tab=settings')
  const host = page.getByRole('textbox', { name: 'Host name' })
  const before = await host.inputValue()
  for (const name of ['owg-e2e', before]) {
    await host.fill(name)
    await expect(page.getByRole('region', { name: 'Command preview' })).toContainText(`hostname='${name}'`)
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')
  }

  await page.getByRole('tab', { name: 'Services' }).click()
  const ntp = page.getByRole('table', { name: 'Services' }).getByRole('row', { name: /^sysntpd\b/ })
  await ntp.getByRole('button', { name: 'Restart' }).click()
  await expect(page.getByRole('region', { name: 'Command preview' })).toContainText('/etc/init.d/sysntpd restart')
  await page.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')

  await page.getByRole('tab', { name: 'Backup and reboot' }).click()
  await page.getByRole('button', { name: 'Create backup' }).click()
  await expect(page.getByRole('table', { name: 'Backups' })).toContainText(/ap1-\d{8}-\d{6}\.tar\.gz/)
})

test('an SSH key added and removed, and an LED trigger changed and back, in the simulator', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulator')
  await open(page, '/routers/ap1/system?tab=access')
  const keys = page.getByRole('region', { name: 'SSH keys' })
  await keys.getByRole('button', { name: 'Add key' }).click()
  await keys.getByRole('textbox', { name: 'Public key line' }).fill(THROWAWAY_KEY)
  await expect(keys.getByRole('region', { name: 'Command preview' })).toContainText(THROWAWAY_KEY)
  await keys.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(keys.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')
  const added = keys.getByRole('table', { name: 'SSH keys' }).getByRole('row', { name: /user@pc/ })
  await expect(added.getByText('Other')).toBeVisible()
  await added.getByRole('button', { name: 'Remove' }).click()
  await keys.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(keys.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')
  await expect(keys.getByRole('table', { name: 'SSH keys' }).getByRole('row', { name: /user@pc/ })).toHaveCount(0)

  await page.getByRole('tab', { name: 'LEDs' }).click()
  const trigger = page.getByRole('combobox', { name: 'Trigger of led_lan' })
  const before = await trigger.inputValue()
  for (const value of ['heartbeat', before]) {
    await trigger.selectOption(value)
    await expect(page.getByRole('region', { name: 'Command preview' })).toContainText(`system.led_lan.trigger='${value}'`)
    await page.getByRole('button', { name: 'Apply', exact: true }).click()
    await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('Applied and checked')
    await expect(page.getByRole('status', { name: 'Apply result' })).toContainText('LED green:lan')
  }
})

test('a restore of a fresh backup through to back, in the simulator', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulator')
  test.setTimeout(120_000)
  await open(page, '/routers/ap1/system?tab=backup')
  await page.getByRole('button', { name: 'Create backup' }).click()
  await expect(page.getByRole('table', { name: 'Backups' })).toContainText(/ap1-\d{8}-\d{6}\.tar\.gz/)
  const restore = page.getByRole('region', { name: 'Restore' })
  await restore.getByRole('button', { name: 'Check' }).click()
  await expect(restore.getByRole('list', { name: 'Files in the backup' })).toContainText('/etc/config/network')
  await restore.getByRole('button', { name: 'Restore and reboot' }).click()
  await restore.getByRole('group', { name: 'Confirm restore' }).getByRole('button', { name: 'Restore now' }).click()
  await expect(restore.getByRole('status', { name: 'Restore' })).toContainText('every restored file matches the backup', { timeout: 90_000 })
})
