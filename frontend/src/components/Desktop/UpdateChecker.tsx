// Preferences shared with the unified source + signed Desktop updater.
// Only signed Tauri release builds can install binary updates; Preview
// installers always use VITE_OPENJARVIS_NO_UPDATER=1.
const DISABLED_KEY = 'oj-auto-update-disabled';

export function isUpdaterBuildDisabled(): boolean {
  const value = (import.meta as any).env?.VITE_OPENJARVIS_NO_UPDATER;
  return value === '1' || value === 'true';
}

export function isAutoUpdateDisabled(): boolean {
  try {
    return localStorage.getItem(DISABLED_KEY) === '1';
  } catch {
    return false;
  }
}

export function setAutoUpdateDisabled(disabled: boolean): void {
  try {
    if (disabled) localStorage.setItem(DISABLED_KEY, '1');
    else localStorage.removeItem(DISABLED_KEY);
  } catch { /* Settings remains usable without local storage. */ }
}
