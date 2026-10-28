import { expect, test as base, type Page } from '@playwright/test';

export { expect };

/**
 * `getUserMedia` for browsers with no fake-device switch (WebKit, #99): a Web Audio
 * oscillator stream. The page still records it with the real MediaRecorder, so Safari
 * produces genuine AAC in MP4 and the upload path sees real bytes.
 */
function fakeMicrophone() {
  // WebKit only lets an AudioContext run if it was resumed inside a user gesture, and
  // getUserMedia is called after an await, so the tone is built at the first gesture.
  let stream: MediaStream | undefined;
  const build = () => {
    if (stream) return;
    const context = new AudioContext();
    void context.resume();
    const tone = context.createOscillator();
    tone.frequency.value = 440;
    const destination = context.createMediaStreamDestination();
    tone.connect(destination);
    tone.start();
    stream = destination.stream;
  };
  for (const type of ['pointerdown', 'keydown', 'click'])
    window.addEventListener(type, build, { capture: true });
  // On the prototype: WebKit hands out a fresh MediaDevices object, so patching the
  // instance does not last.
  MediaDevices.prototype.getUserMedia = () => {
    build();
    return Promise.resolve(stream!.clone());
  };
}

/** `getUserMedia` refused the way a browser refuses after the learner clicks Block. */
function blockedMicrophone() {
  MediaDevices.prototype.getUserMedia = () =>
    Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));
}

/**
 * Safari's Tab skips buttons and links unless Full Keyboard Access is on; Option+Tab
 * reaches them. WebKit on macOS behaves the same, so the keyboard specs, which Tab
 * between buttons, press Option+Tab there. Every other browser is untouched.
 */
const SAFARI_TAB: Record<string, string> = { Tab: 'Alt+Tab', 'Shift+Tab': 'Alt+Shift+Tab' };

export const test = base.extend({
  page: async ({ page, browserName }, provide) => {
    if (browserName === 'webkit') await page.addInitScript(fakeMicrophone);
    if (browserName === 'webkit' && process.platform === 'darwin') {
      const press = page.keyboard.press.bind(page.keyboard);
      page.keyboard.press = (key, options) => press(SAFARI_TAB[key] ?? key, options);
    }
    await provide(page);
  },
});

/**
 * Deny the microphone. Chromium has a real permission switch over CDP; the other
 * engines have none, so the refusal is simulated at `getUserMedia`.
 */
export async function denyMicrophone(page: Page, browserName: string) {
  if (browserName === 'chromium') {
    const cdp = await page.context().newCDPSession(page);
    const { targetInfo } = await cdp.send('Target.getTargetInfo');
    await cdp.send('Browser.setPermission', {
      browserContextId: targetInfo.browserContextId,
      permission: { name: 'microphone' },
      setting: 'denied',
      origin: new URL(page.url()).origin,
    });
  } else {
    await page.evaluate(blockedMicrophone);
  }
}

/** Playwright's WebKit driver refuses `route.fulfill` with a 3xx status. */
export const WEBKIT_NO_REDIRECT_MOCK =
  "Playwright's WebKit cannot fulfil a redirect response, so the mock cannot stand in for the server";

/**
 * Playwright's Linux WebKit build ships without MediaRecorder, so a recording cannot
 * be made there. The same specs run on WebKit on macOS in the cross-browser workflow.
 */
export async function skipWithoutMediaRecorder(page: Page) {
  const present = await page.evaluate(() => typeof MediaRecorder !== 'undefined');
  test.skip(!present, 'this browser build has no MediaRecorder, so no recording can be made');
}
