# Accessibility statement

> Draft, prepared on 31 October 2026 for #98. It must be reviewed, and its contact completed, before launch.

ListenUp is a web app for practising English listening. We want everyone who can take part in a listening exercise to be able to use it, with a keyboard, a screen reader, a phone or a large text size.

## Our target

We aim to meet the Web Content Accessibility Guidelines (WCAG) 2.1 at level AA. The design also follows two WCAG 2.2 rules: targets are at least 44 by 44 pixels on phones and 24 by 24 pixels on larger screens, and nothing that stays at the top of the screen covers the control you are on.

## Where we are

ListenUp is **partially conformant** with WCAG 2.1 AA: most of it meets the guidelines, and the gaps we know of are listed below. The checks with a screen reader on a computer and on a phone have not yet been done, so we do not yet claim that ListenUp works with screen readers.

## What we check

- An automated check (axe) runs on every screen and its main states, at a desktop width, at 360 pixels wide and in the dark theme, each time the code changes.
- A keyboard-only run goes through each of the three plan paths, from the library to the finished plan, including a mark, a card and the three Shadow rounds. Every control is reached with Tab, and each one shows where the focus is.
- At 360 pixels wide, no screen scrolls sideways and every control is at least 44 pixels in each direction.
- Colours meet the contrast ratios of WCAG 2.1 AA in the light and the dark theme.

## Using ListenUp with a keyboard

- Every control can be reached with Tab and used with Enter or Space. Practice screens list their keys on the page.
- In the player outside a text field: Space or K plays and pauses, J goes back 5 seconds, R replays, and the square brackets change the speed.
- In Transcript, Left and Right move between words, Shift with an arrow selects several words, and M marks them.
- Dialogs put focus on the safe choice, keep focus inside, and close with Escape.

## Rules of the exercises

Some limits are the exercise itself, not barriers we can remove:

- Blind plays the passage once, with no pause, rewind or speed change, and only the volume can be changed. It starts only when you press Start listening.
- Dictation and Blind do not show the words you are listening to. Transcript shows them, with every word linked to its place in the audio.
- The Shadow rounds play at the original speed, and they need a microphone.

Because ListenUp trains listening, its exercises depend on hearing the audio.

## Known limitations

- In Shadow, when a round finishes playing, keyboard focus moves to the top of the page instead of staying with the next step. Tab still reaches Start round. A fix has been reported.
- In Shadow, the link to the voice recording consent is shorter than 44 pixels on phones. A fix has been reported.
- ListenUp is in English only.

## Tell us about a problem

If something in ListenUp is hard or impossible for you to use, tell us what you were doing and what happened. [Accessibility contact: to be completed before launch.]
