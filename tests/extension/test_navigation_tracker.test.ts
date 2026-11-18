import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { initNavigationTracker } from '../../src/extension/background/navigation_tracker';

describe('SPA Navigation Tracker', () => {
  let navListener: ((details: { frameId: number; tabId: number; url: string }) => void) | null = null;
  let mockSendMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    navListener = null;
    mockSendMessage = vi.fn().mockResolvedValue(undefined);

    vi.stubGlobal('chrome', {
      webNavigation: {
        onHistoryStateUpdated: {
          addListener: vi.fn((cb) => {
            navListener = cb;
          }),
        },
      },
      tabs: {
        sendMessage: mockSendMessage,
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('registers listener and dispatches SPA_NAVIGATION_DETECTED for main frame (frameId 0)', () => {
    initNavigationTracker();
    expect(navListener).not.toBeNull();

    navListener!({ frameId: 0, tabId: 42, url: 'https://example.com/ch2' });

    expect(mockSendMessage).toHaveBeenCalledWith(42, {
      type: 'SPA_NAVIGATION_DETECTED',
      payload: { url: 'https://example.com/ch2' },
    });
  });

  it('ignores sub-frame history updates (frameId > 0)', () => {
    initNavigationTracker();
    navListener!({ frameId: 1, tabId: 42, url: 'https://example.com/iframe' });

    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it('safely handles rejected sendMessage when tab is closed or inactive', async () => {
    mockSendMessage.mockRejectedValueOnce(new Error('Receiving end does not exist'));
    initNavigationTracker();

    expect(() => {
      navListener!({ frameId: 0, tabId: 99, url: 'https://example.com/closed' });
    }).not.toThrow();
  });

  it('gracefully exits when chrome.webNavigation is unavailable', () => {
    vi.stubGlobal('chrome', {});
    expect(() => initNavigationTracker()).not.toThrow();
  });
});
