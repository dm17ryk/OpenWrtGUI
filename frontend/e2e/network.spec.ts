import { expect, test } from '@playwright/test'
import { noHorizontalScroll, open } from './helpers'

const CARDS = ['Router addresses', 'DHCP server', 'Fixed addresses by MAC', 'Wi-Fi access by MAC', 'Active leases', 'DNS', 'Static routes and rules']

test('the Network screen fits the window', async ({ page }) => {
  await open(page, '/routers/ap1/network')
  await expect(page.getByRole('heading', { name: 'Network and DHCP', level: 1 })).toBeVisible()
  for (const name of CARDS) await expect(page.getByRole('region', { name })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Active leases' })).toContainText('f4:12:fa:f3:57:68')
  await noHorizontalScroll(page)
})

test('lan moves to .12 with the rollback, confirmed, and back to .2', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  await open(page, '/routers/ap2/network')
  const addresses = page.getByRole('region', { name: 'Router addresses' })
  const edit = addresses.getByRole('button', { name: 'Edit lan' })
  const address = addresses.getByRole('textbox', { name: 'Address (address/prefix)' })
  const apply = addresses.getByRole('button', { name: 'Apply with rollback' })

  await edit.click()
  await address.fill('192.168.1.12/24')
  await expect(addresses.getByRole('region', { name: 'Command preview' })).toContainText("set network.lan.ipaddr='192.168.1.12/24'")
  await expect(addresses.getByText(/Applies with a 60 s rollback/)).toBeVisible()
  await apply.click()
  await expect(addresses.getByText('Applied and confirmed')).toBeVisible()
  await expect(addresses.getByText('AP2 · office is now at 192.168.1.12')).toBeVisible()
  await expect(page.locator('.eyebrow .mono')).toHaveText('192.168.1.12')

  // back as it was: reopen the editor so it starts from the router's new address
  await edit.click()
  await edit.click()
  await address.fill('192.168.1.2/24')
  await expect(addresses.getByRole('region', { name: 'Command preview' })).toContainText("set network.lan.ipaddr='192.168.1.2/24'")
  await apply.click()
  await expect(addresses.getByText('AP2 · office is now at 192.168.1.2')).toBeVisible()
  await expect(page.locator('.eyebrow .mono')).toHaveText('192.168.1.2')
})

test('a fixed address is added, shows up, and is deleted again', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  await open(page, '/routers/ap1/network')
  const hosts = page.getByRole('region', { name: 'Fixed addresses by MAC' })
  const apply = hosts.getByRole('button', { name: 'Apply', exact: true })

  await hosts.getByRole('button', { name: '+ Fixed address' }).click()
  await hosts.getByRole('textbox', { name: 'Name of new address 1' }).fill('e2e-sta')
  await hosts.getByRole('textbox', { name: 'MAC of new address 1' }).fill('02:00:00:00:e2:e2')
  await hosts.getByRole('textbox', { name: 'IP of new address 1' }).fill('192.168.1.222')
  await expect(hosts.getByRole('region', { name: 'Command preview' })).toContainText("mac='02:00:00:00:e2:e2'")
  await apply.click()
  await expect(hosts.getByText('Applied and checked')).toBeVisible()
  await expect(hosts.getByRole('textbox', { name: 'IP of e2e-sta' })).toHaveValue('192.168.1.222')

  await hosts.getByRole('button', { name: 'Delete e2e-sta' }).click()
  await expect(hosts.getByRole('region', { name: 'Command preview' })).toContainText('uci -q delete dhcp.')
  await apply.click()
  await expect(hosts.getByRole('textbox', { name: 'IP of e2e-sta' })).toHaveCount(0)
})

test('a device is blocked now, without a Wi-Fi restart, and unblocked', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop-light', 'one project changes the simulated router')
  await open(page, '/routers/ap1/network')
  const access = page.getByRole('region', { name: 'Wi-Fi access by MAC' })
  const apply = access.getByRole('button', { name: 'Apply', exact: true })

  await access.getByRole('button', { name: '+ Device' }).click()
  await access.getByRole('textbox', { name: 'New device MAC' }).fill('f4:12:fa:f3:57:68')
  await access.getByRole('textbox', { name: 'New device name' }).fill('panel')
  await access.getByRole('button', { name: 'Add', exact: true }).click()
  await access.getByRole('button', { name: 'Block panel', exact: true }).click()
  await expect(access.getByText('Until the next Wi-Fi restart.')).toBeVisible()
  await expect(access.getByRole('region', { name: 'Command preview' })).toContainText('hostapd_cli -i phy0-ap0 deny_acl ADD_MAC f4:12:fa:f3:57:68')
  await apply.click()
  await expect(access.getByText('Applied and checked')).toBeVisible()
  const row = access.getByRole('table', { name: 'Devices' }).getByRole('row', { name: /f4:12:fa:f3:57:68/ })
  await expect(row).toContainText('phy0-ap0')

  await access.getByRole('button', { name: 'Unblock panel', exact: true }).click()
  await expect(access.getByRole('region', { name: 'Command preview' })).toContainText('deny_acl DEL_MAC f4:12:fa:f3:57:68')
  await apply.click()
  await expect(row).not.toContainText('phy0-ap0')
})
