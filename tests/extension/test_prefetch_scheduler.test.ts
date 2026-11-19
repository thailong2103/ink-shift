import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PrefetchScheduler } from '../../src/extension/content/prefetch_scheduler';
import type { ChapterContextReport } from '../../src/extension/shared/context_types';

describe('PrefetchScheduler', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    (globalThis as unknown as { chrome: unknown }).chrome = {
      runtime: {
        sendMessage: vi.fn().mockResolvedValue({
          success: true,
          data: {
            success: true,
            page_hash: 'mock-hash',
            engine_used: 'mock',
            execution_time_ms: 50,
            from_cache: false,
            blocks: [],
          },
        }),
      },
    };
  });

  const mockManifest: ChapterContextReport = {
    series_id: 's-1',
    series_title: 'Manga Title',
    source_domain: 'example.com',
    chapter_id: 'ch-1',
    chapter_ordinal: 1,
    chapter_label: 'Ch. 1',
    chapter_url: 'https://example.com/ch1',
    total_pages: 10,
    pages: Array.from({ length: 10 }, (_, i) => ({
      page_number: i + 1,
      image_url: `https://cdn/page-${i + 1}.jpg`,
      status: 'discovered',
    })),
  };

  it('enqueues sliding lookahead window respecting depth limit', async () => {
    const onReady = vi.fn();
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
      onPageReady: onReady,
    });

    scheduler.setChapterManifest(mockManifest, 1);

    // Initial page = 1, depth = 3 -> pages 1 (P0), 2 (P1), 3 (P2), 4 (P2)
    // Let async processQueue drain
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(chrome.runtime.sendMessage).toHaveBeenCalled();
    expect(scheduler.isPageCompleted(1)).toBe(true);
    expect(scheduler.isPageCompleted(2)).toBe(true);
    expect(scheduler.isPageCompleted(3)).toBe(true);
    expect(scheduler.isPageCompleted(4)).toBe(true);
    // Page 5 should NOT be pre-fetched yet because depth is 3 (1 + 3 = 4)
    expect(scheduler.isPageCompleted(5)).toBe(false);

    scheduler.cancelAllTasks();
  });

  it('slides lookahead window forward when reading page advances', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(scheduler.isPageCompleted(5)).toBe(false);

    // User flips to page 2 -> window expands to 2 + 3 = 5
    scheduler.onPageChange(2);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(scheduler.isPageCompleted(5)).toBe(true);

    scheduler.cancelAllTasks();
  });

  it('prefetches all remaining chapter pages when depth is set to all', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 'all',
    });

    scheduler.setChapterManifest(mockManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    // All 10 pages must be processed
    for (let p = 1; p <= 10; p++) {
      expect(scheduler.isPageCompleted(p)).toBe(true);
    }

    scheduler.cancelAllTasks();
  });

  it('cancels pending lookahead tasks when prefetch is disabled', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 5,
    });

    scheduler.setChapterManifest(mockManifest, 1);
    scheduler.setEnabled(false);

    expect(scheduler.getPendingCount()).toBe(0);

    scheduler.cancelAllTasks();
  });

  it('aborts previous chapter tasks upon chapter transition', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 1);

    const nextChapterManifest: ChapterContextReport = {
      ...mockManifest,
      chapter_id: 'ch-2',
      chapter_ordinal: 2,
      pages: Array.from({ length: 5 }, (_, i) => ({
        page_number: i + 1,
        image_url: `https://cdn/ch2-page-${i + 1}.jpg`,
        status: 'discovered',
      })),
    };

    scheduler.setChapterManifest(nextChapterManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(scheduler.isPageCompleted(1)).toBe(true);

    scheduler.cancelAllTasks();
  });

  it('marks on-screen page as completed and removes pending queue task', () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 1);
    expect(scheduler.isPageCompleted(2)).toBe(false);

    scheduler.markPageCompleted(2);
    expect(scheduler.isPageCompleted(2)).toBe(true);

    scheduler.cancelAllTasks();
  });

  it('forwards custom engine, provider, translator, and model options to TRANSLATE_IMAGE', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
      engine: 'cloud',
      provider: 'custom',
      translator: 'custom-model',
      model: 'qwen/qwen3.8-omni-flash:free',
    });

    scheduler.setChapterManifest(mockManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'TRANSLATE_IMAGE',
        payload: expect.objectContaining({
          engine: 'cloud',
          provider: 'custom',
          translator: 'custom-model',
          model: 'qwen/qwen3.8-omni-flash:free',
        }),
      })
    );

    scheduler.cancelAllTasks();
  });

  it('resets queue and dispatches active page with forceRefresh: true on resetForRescan', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(scheduler.isPageCompleted(1)).toBe(true);

    vi.mocked(chrome.runtime.sendMessage).mockClear();

    // Trigger resetForRescan on page 1
    scheduler.resetForRescan(1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'TRANSLATE_IMAGE',
        payload: expect.objectContaining({
          imageIndex: 0,
          forceRefresh: true,
        }),
      })
    );

    scheduler.cancelAllTasks();
  });

  it('assigns P0 for active page, P1 for next page, and P2 for lookahead pages', async () => {
    vi.mocked(chrome.runtime.sendMessage).mockClear();
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    const translatePayloads = vi
      .mocked(chrome.runtime.sendMessage)
      .mock.calls.map((call) => call[0] as { type?: string; payload?: { imageIndex?: number; priority?: string } })
      .filter((msg) => msg?.type === 'TRANSLATE_IMAGE')
      .map((msg) => msg.payload);

    expect(translatePayloads).toContainEqual(
      expect.objectContaining({ imageIndex: 0, priority: 'P0' })
    );
    expect(translatePayloads).toContainEqual(
      expect.objectContaining({ imageIndex: 1, priority: 'P1' })
    );
    if (mockManifest.pages.length >= 3) {
      expect(translatePayloads).toContainEqual(
        expect.objectContaining({ imageIndex: 2, priority: 'P2' })
      );
    }

    scheduler.cancelAllTasks();
  });

  it('does not mark page as completed when backend returns is_fallback: true', async () => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({
      success: true,
      data: {
        image_url: 'https://example.com/1.jpg',
        blocks: [],
        processing_time_ms: 10,
        is_fallback: true,
      },
    } as never);

    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 1);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(scheduler.isPageCompleted(1)).toBe(false);
    expect(scheduler.isPageCompleted(2)).toBe(false);

    scheduler.cancelAllTasks();
  });

  it('preempts in-flight distant task on page jump and re-queues it sequentially without dropping', async () => {
    let resolveP4!: (value: unknown) => void;
    const p4Deferred = new Promise((resolve) => {
      resolveP4 = resolve;
    });
    const dispatchedAfterJump: number[] = [];
    let jumped = false;

    vi.mocked(chrome.runtime.sendMessage).mockImplementation(async (rawMsg: unknown) => {
      const msg = rawMsg as { type?: string; payload?: { imageIndex?: number } };
      if (msg?.type !== 'TRANSLATE_IMAGE') {
        return { success: true, data: {} };
      }
      const pageNum = (msg?.payload?.imageIndex ?? 0) + 1;
      if (jumped) {
        dispatchedAfterJump.push(pageNum);
      }
      if (!jumped && pageNum === 4) {
        return p4Deferred;
      }
      return {
        success: true,
        data: {
          image_url: `https://example.com/${pageNum}.jpg`,
          blocks: [],
          processing_time_ms: 5,
          is_fallback: false,
        },
      };
    });

    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
    });

    scheduler.setChapterManifest(mockManifest, 3);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(scheduler.isPageCompleted(3)).toBe(true);

    // Jump backward to uncompleted page 1 while page 4 is still in-flight
    jumped = true;
    scheduler.onPageChange(1);
    resolveP4({
      success: false,
      error: { code: 'TRANSLATION_CANCELLED', message: 'cancelled' },
    });

    await new Promise((resolve) => setTimeout(resolve, 60));

    expect(dispatchedAfterJump).toEqual([1, 2, 4]);
    expect(scheduler.isPageCompleted(1)).toBe(true);
    expect(scheduler.isPageCompleted(2)).toBe(true);
    expect(scheduler.isPageCompleted(3)).toBe(true);
    expect(scheduler.isPageCompleted(4)).toBe(true);

    scheduler.cancelAllTasks();
  });
});

