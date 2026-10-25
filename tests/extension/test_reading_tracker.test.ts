import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ReadingProgressTracker } from '../../src/extension/content/reading_progress_tracker';

describe('ReadingProgressTracker', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    (globalThis as unknown as { chrome: unknown }).chrome = {
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({ success: true }),
      },
    };
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('debounces rapid page skimming and dispatches only after dwell time', async () => {
    const onProgress = vi.fn();
    const tracker = new ReadingProgressTracker('ch-test-1', {
      debounceMs: 2000,
      onProgressUpdate: onProgress,
    });

    // Rapid skimming: page 1 -> 2 -> 3
    tracker.trackPage(1);
    vi.advanceTimersByTime(500);
    tracker.trackPage(2);
    vi.advanceTimersByTime(500);
    tracker.trackPage(3);

    // No dispatch yet
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    expect(onProgress).not.toHaveBeenCalled();

    // Advance dwell time past 2000ms
    vi.advanceTimersByTime(2000);

    expect(onProgress).toHaveBeenCalledWith(3);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      type: 'UPDATE_READING_PROGRESS',
      payload: {
        chapter_id: 'ch-test-1',
        page_number: 3,
      },
    });

    tracker.destroy();
  });

  it('ignores redundant updates for the same page', async () => {
    const onProgress = vi.fn();
    const tracker = new ReadingProgressTracker('ch-test-2', {
      debounceMs: 1000,
      onProgressUpdate: onProgress,
    });

    tracker.trackPage(5);
    vi.advanceTimersByTime(1000);
    expect(onProgress).toHaveBeenCalledTimes(1);

    // Re-tracking page 5 should not schedule another dispatch
    tracker.trackPage(5);
    vi.advanceTimersByTime(1500);
    expect(onProgress).toHaveBeenCalledTimes(1);

    tracker.destroy();
  });

  it('handles single-page URL updates', async () => {
    const onProgress = vi.fn();
    const tracker = new ReadingProgressTracker('uuid-ch-99', {
      debounceMs: 500,
      onProgressUpdate: onProgress,
    });

    const url = new URL('https://mangadex.org/chapter/uuid-ch-99/7');
    tracker.handleUrlChange(url);

    vi.advanceTimersByTime(500);
    expect(onProgress).toHaveBeenCalledWith(7);

    tracker.destroy();
  });

  it('clears timers on destroy without dispatching pending update', async () => {
    const onProgress = vi.fn();
    const tracker = new ReadingProgressTracker('ch-test-3', {
      debounceMs: 2000,
      onProgressUpdate: onProgress,
    });

    tracker.trackPage(10);
    vi.advanceTimersByTime(500);
    tracker.destroy();

    vi.advanceTimersByTime(3000);
    expect(onProgress).not.toHaveBeenCalled();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });
});
