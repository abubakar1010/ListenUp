import { fireEvent, render, screen } from '@testing-library/react';

import { BusyButton } from './BusyButton';

test('while busy it stays focusable, says so and ignores presses', () => {
  const onClick = vi.fn();
  render(
    <BusyButton busy className="x" onClick={onClick}>
      Saving…
    </BusyButton>,
  );
  const button = screen.getByRole('button', { name: 'Saving…' });

  expect(button).toBeEnabled();
  expect(button).toHaveAttribute('aria-disabled', 'true');
  expect(button).toHaveAttribute('aria-busy', 'true');
  expect(button).toHaveAttribute('type', 'button');
  button.focus();
  fireEvent.click(button);
  expect(onClick).not.toHaveBeenCalled();
  expect(button).toHaveFocus();
});

test('a busy submit button does not submit its form again', () => {
  const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
  render(
    <form onSubmit={onSubmit}>
      <BusyButton type="submit" busy>
        Signing in…
      </BusyButton>
    </form>,
  );

  fireEvent.click(screen.getByRole('button'));

  expect(onSubmit).not.toHaveBeenCalled();
});

test('when not busy it is an ordinary button', () => {
  const onClick = vi.fn();
  render(
    <BusyButton busy={false} onClick={onClick} aria-describedby="why">
      Save
    </BusyButton>,
  );
  const button = screen.getByRole('button', { name: 'Save' });

  expect(button).not.toHaveAttribute('aria-disabled');
  expect(button).not.toHaveAttribute('aria-busy');
  expect(button).toHaveAttribute('aria-describedby', 'why');
  fireEvent.click(button);
  expect(onClick).toHaveBeenCalledTimes(1);
});
