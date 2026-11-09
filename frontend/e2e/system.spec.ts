import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

test('the System screen shows the model, the overview and three live charts', async ({ page }) => {
  await open(page, '/routers/ap1/system')
  await expect(page.getByRole('heading', { name: 'System', level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Overview' })).toContainText('D-Link DWR-921 C3 (U-Boot)')
  await expect(page.locator('.rf-chart canvas')).toHaveCount(3)
  await noHorizontalScroll(page)
  for (const tab of ['Logs', 'Processes', 'Diagnostics', 'System and time', 'Services', 'Scheduled tasks', 'Backup and reboot']) {
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
