import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { CapabilityRow } from '../../api/types'
import { CapabilityChips } from './CapabilityChips'
import { capabilityLink } from './capabilityLinks'

const ROWS: CapabilityRow[] = [
  { name: 'Switch', state: 'in image', reason: null },
  { name: 'Air survey', state: 'in image', reason: null },
  { name: 'Throughput', state: 'in image', reason: null },
  { name: 'Traffic generator', state: 'missing', reason: 'needs socat' },
  { name: 'Connections', state: 'missing', reason: 'needs nf_conntrack.ko' },
  { name: 'Port statistics', state: 'added after flashing', reason: null },
]

function show(rows: CapabilityRow[] = ROWS) {
  render(
    <MemoryRouter>
      <CapabilityChips routerId="ap1" rows={rows} />
    </MemoryRouter>,
  )
}

test('a section of chips, each with its state in words', () => {
  show()
  expect(screen.getByRole('heading', { name: 'Capabilities' })).toBeInTheDocument()
  expect(screen.getAllByRole('listitem')).toHaveLength(6)
  expect(screen.getByText('Port statistics · added after flashing')).toBeInTheDocument()
})

test('a chip opens the screen that uses it', () => {
  show()
  expect(screen.getByRole('link', { name: 'Air survey · in image' })).toHaveAttribute(
    'href',
    '/routers/ap1/rf#channel-analysis',
  )
  expect(screen.getByRole('link', { name: 'Switch · in image' })).toHaveAttribute('href', '/routers/ap1/ports')
})

test('a missing capability with a page still links, and says what it needs', () => {
  show()
  const chip = screen.getByRole('link', { name: 'Connections · missing: needs nf_conntrack.ko' })
  expect(chip).toHaveAttribute('href', '/routers/ap1/tools/connections')
  expect(chip).toHaveClass('missing')
})

test('the active tool pages are links too (v1.2b)', () => {
  show()
  expect(screen.getByRole('link', { name: 'Throughput · in image' })).toHaveAttribute(
    'href',
    '/routers/ap1/tools/throughput',
  )
  const missing = screen.getByRole('link', { name: 'Traffic generator · missing: needs socat' })
  expect(missing).toHaveAttribute('href', '/routers/ap1/tools/traffic')
  expect(missing).toHaveClass('missing')
})

test('a capability without a page is not a link', () => {
  show([{ name: 'Nope', state: 'in image', reason: null }])
  expect(screen.getByText('Nope · in image').closest('a')).toBeNull()
})

test('every link the chips know', () => {
  const links = Object.fromEntries(
    [
      'Switch',
      'LTE',
      'Capture',
      'netem',
      'Firewall',
      'Monitor mode',
      'Air survey',
      'Port statistics',
      'Connections',
      'Throughput',
      'Traffic generator',
      'Station management',
      'Nope',
    ].map((n) => [n, capabilityLink('ap1', n)]),
  )
  expect(links).toEqual({
    Switch: '/routers/ap1/ports',
    LTE: '/routers/ap1/lte',
    Capture: '/routers/ap1/faults#capture',
    netem: '/routers/ap1/faults',
    Firewall: '/routers/ap1/firewall',
    'Monitor mode': '/routers/ap1/rf#frame-analysis',
    'Air survey': '/routers/ap1/rf#channel-analysis',
    'Port statistics': '/routers/ap1/tools/port-stats',
    Connections: '/routers/ap1/tools/connections',
    Throughput: '/routers/ap1/tools/throughput',
    'Traffic generator': '/routers/ap1/tools/traffic',
    'Station management': '/routers/ap1/tools/stations',
    Nope: null,
  })
})
