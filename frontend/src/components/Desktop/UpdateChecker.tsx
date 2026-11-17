// Preferences for verified owner-signed Desktop updates. The unsigned
// Preview cannot update its compiled executable because it has no trusted key.
// Automatic installation is explicit opt-in and never silently enabled.
const AUTO_INSTALL_KEY = 'oj-signed-desktop-auto-install-enabled';

export function isUpdaterBuildDisabled(): boolean {
  const value = (import.meta as any).env?.VITE_OPENJARVIS_NO_UPDATER;
  return value === '1' || value === 'true';
}

export function isAutoUpdateDisabled(): boolean {
  try {
    return localStorage.getItem(AUTO_INSTALL_KEY) !== '1';
  } catch {
    return true;
  }
}

export function setAutoUpdateDisabled(disabled: boolean): void {
  try {
    localStorage.setItem(AUTO_INSTALL_KEY, disabled ? '0' : '1');
    window.dispatchEvent(new Event('openjarvis-auto-install-setting-changed'));
  } catch { /* No automatic installations if storage is unavailable. */ }
}
