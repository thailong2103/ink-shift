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

  it('forwards custom engine, provider, translator, model, and sourceLang options to TRANSLATE_IMAGE', async () => {
    const scheduler = new PrefetchScheduler({
      enabled: true,
      depth: 3,
      engine: 'cloud',
      provider: 'custom',
      translator: 'custom-model',
      model: 'qwen/qwen3.8-omni-flash:free',
      sourceLang: 'ja',
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
          sourceLang: 'ja',
        }),
      })
    );

    scheduler.cancelAllTasks();
  });
});
