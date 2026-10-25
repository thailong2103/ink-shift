/**
 * SPA Navigation Tracker for Chromium Extension.
 *
 * Listens to chrome.webNavigation.onHistoryStateUpdated to detect client-side
 * SPA route transitions (e.g., chapter changes on manga reader websites)
 * and dispatches SPA_NAVIGATION_DETECTED message to the active tab to reset overlays.
 */

import type { IPCMessage } from '../shared/ipc_types';

/**
 * Initializes listeners for SPA history state updates on the top frame.
 */
export function initNavigationTracker(): void {
  if (
    typeof chrome === 'undefined' ||
    !chrome.webNavigation ||
    !chrome.webNavigation.onHistoryStateUpdated
  ) {
    return;
  }

  chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
    // Only dispatch for the top-level main frame (frameId === 0)
    if (details.frameId !== 0) {
      return;
    }

    const message: IPCMessage = {
      type: 'SPA_NAVIGATION_DETECTED',
      payload: { url: details.url },
    };

    chrome.tabs.sendMessage(details.tabId, message).catch(() => {
      // Content script may not be injected on this page or tab closed; safe to ignore
    });
  });
}
