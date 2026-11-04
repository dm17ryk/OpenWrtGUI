import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { Help, HelpTip } from './Help'
import { WIKI } from './manual'

test('the help button names its section and shows the manual text on focus', async () => {
  const user = userEvent.setup()
  render(<Help topic="Dashboard#air-map" />)
  expect(screen.queryByRole('tooltip')).toBeNull()
  await user.tab()
  const tip = screen.getByRole('tooltip')
  expect(screen.getByRole('button', { name: 'Help: Air map' })).toHaveAttribute('aria-describedby', tip.id)
  expect(tip).toHaveTextContent('One map per band that has a radio')
  const more = screen.getByRole('link', { name: 'More in the manual' })
  expect(more).toHaveAttribute('href', `${WIKI}Dashboard#air-map`)
  expect(more).toHaveAttribute('target', '_blank')
  expect(more).toHaveAttribute('rel', 'noopener noreferrer')
})

test('Escape closes the help, and hovering opens it again', async () => {
  const user = userEvent.setup()
  render(<Help topic="Dashboard#headline" />)
  const button = screen.getByRole('button', { name: 'Help: Headline' })
  await user.hover(button)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('The title counts the bench')
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('tooltip')).toBeNull()
})

test('a tap opens it, for touch screens', async () => {
  const user = userEvent.setup()
  render(<Help topic="Dashboard#headline" />)
  await user.click(screen.getByRole('button', { name: 'Help: Headline' }))
  expect(screen.getByRole('tooltip')).toBeInTheDocument()
})

test('a button wrapped in HelpTip describes itself with the manual text', async () => {
  const user = userEvent.setup()
  render(
    <HelpTip topic="Updating#going-back">
      <button type="button">Reinstall previous version</button>
    </HelpTip>,
  )
  const button = screen.getByRole('button', { name: 'Reinstall previous version' })
  await user.hover(button)
  const tip = await screen.findByRole('tooltip')
  expect(button).toHaveAttribute('aria-describedby', tip.id)
  expect(tip).toHaveTextContent('Going back')
})

test('clicking the text inside the bubble keeps it open', async () => {
  const user = userEvent.setup()
  render(<Help topic="Dashboard#headline" />)
  await user.click(screen.getByRole('button', { name: 'Help: Headline' }))
  await user.click(screen.getByText(/The title counts the bench/))
  await new Promise((resolve) => setTimeout(resolve, 400))
  expect(screen.getByRole('tooltip')).toBeInTheDocument()
})

test('a tip on something that is not a control can still be reached with the keyboard', async () => {
  const user = userEvent.setup()
  render(
    <HelpTip topic="Dashboard#router-cards">
      <span className="b air">on air</span>
    </HelpTip>,
  )
  await user.tab()
  expect(screen.getByText('on air')).toHaveFocus()
  expect(screen.getByRole('tooltip')).toHaveTextContent('One card per router')
})

test('an unknown topic renders nothing extra', () => {
  const { container } = render(<Help topic="Nope#nothing" />)
  expect(container).toBeEmptyDOMElement()
})
