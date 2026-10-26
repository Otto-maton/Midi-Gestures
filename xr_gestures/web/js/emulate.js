// Desktop testing without a headset (open the page with ?emulate).
// Installs Meta's Immersive Web Emulation Runtime as an emulated Quest 3 with
// hand tracking, plus its DevUI overlay for moving the head and hands.
// The emulated device is exposed as window.xrDevice. The DevUI re-applies its
// own hand poses every frame, so scripted tests use ?emulate=bare (no DevUI)
// and set xrDevice.hands.right.position etc. directly.
//
// iwer and three stay external so the DevUI shares the app's copies (via the
// import map in index.html).
const DEVUI_URL = 'https://esm.sh/@iwer/devui@2.5.0?external=iwer,three';

export async function installEmulator({ devUI = true } = {}) {
  const { XRDevice, metaQuest3 } = await import('iwer');
  const device = new XRDevice(metaQuest3);
  device.installRuntime({ forceInstall: true });
  device.primaryInputMode = 'hand';
  window.xrDevice = device;
  if (!devUI) return device;
  // The DevUI pulls in React and friends; never hold up the app for it.
  import(DEVUI_URL)
    .then(({ DevUI }) => device.installDevUI(DevUI))
    .catch((e) => console.warn('IWER DevUI could not be loaded; drive window.xrDevice from the console instead.', e));
  return device;
}
