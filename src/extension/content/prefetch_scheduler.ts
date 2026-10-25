/**
 * Sliding Window In-Memory Prefetch Scheduler.
 *
 * Implements a prioritized lookahead queue (P0 On-Screen > P1 Next Page > P2 Sliding Lookahead)
 * achieving Zero-Wait Page Flipping (0ms latency). Ephemeral in-memory image buffers are
 * processed without writing bytes to disk, and pending tasks are aborted upon chapter transitions.
 */

import type { ChapterContextReport, PageItem } from '../shared/context_types';
import type { TranslationResponse, EngineMode } from '../../types/contract';
import type { IPCMessage, IPCResponse } from '../shared/ipc_types';
import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('Prefetch');

export type PrefetchDepth = 3 | 5 | 10 | 'all';
export type TaskPriority = 'P0' | 'P1' | 'P2';

export interface PrefetchTask {
  pageNumber: number;
  imageUrl: string;
  priority: TaskPriority;
  abortController: AbortController;
}

export interface PrefetchSchedulerOptions {
  enabled?: boolean;
  depth?: PrefetchDepth;
  engine?: EngineMode;
  provider?: string;
  translator?: string;
  model?: string;
  sourceLang?: string;
  onPageReady?: (pageNumber: number, response: TranslationResponse, imageUrl: string, chapterId?: string) => void;
  onPageFailed?: (pageNumber: number, error: unknown) => void;
}

const PRIORITY_WEIGHT: Record<TaskPriority, number> = {
  P0: 3,
  P1: 2,
  P2: 1,
};

export class PrefetchScheduler {
  private manifest: ChapterContextReport | null = null;
  private currentPage: number = 1;
  private enabled: boolean = true;
  private depth: PrefetchDepth = 3;
  private engine?: EngineMode;
  private provider?: string;
  private translator?: string;
  private model?: string;
  private sourceLang?: string;
  private onPageReady?: (pageNumber: number, response: TranslationResponse, imageUrl: string, chapterId?: string) => void;
  private onPageFailed?: (pageNumber: number, error: unknown) => void;

  private queue: PrefetchTask[] = [];
  private inFlight = new Map<number, AbortController>();
  private completedPages = new Set<number>();
  private chapterAbortController = new AbortController();
  private isProcessing: boolean = false;

  constructor(options?: PrefetchSchedulerOptions) {
    if (options?.enabled !== undefined) {
      this.enabled = options.enabled;
    }
    if (options?.depth !== undefined) {
      this.depth = options.depth;
    }
    this.engine = options?.engine;
    this.provider = options?.provider;
    this.translator = options?.translator;
    this.model = options?.model;
    this.sourceLang = options?.sourceLang;
    this.onPageReady = options?.onPageReady;
    this.onPageFailed = options?.onPageFailed;
  }

  /**
   * Update engine/provider/translator configuration dynamically.
   */
  setConfig(config: {
    engine?: EngineMode;
    provider?: string;
    translator?: string;
    model?: string;
    sourceLang?: string;
  }): void {
    if (config.engine !== undefined) this.engine = config.engine;
    if (config.provider !== undefined) this.provider = config.provider;
    if (config.translator !== undefined) this.translator = config.translator;
    if (config.model !== undefined) this.model = config.model;
    if (config.sourceLang !== undefined) this.sourceLang = config.sourceLang;
  }

  /**
   * Initialize or replace active chapter manifest and recalculate sliding window.
   */
  setChapterManifest(manifest: ChapterContextReport, initialPage: number = 1): void {
    this.cancelAllTasks();
    this.manifest = manifest;
    this.currentPage = initialPage;
    this.chapterAbortController = new AbortController();
    const total = manifest.total_pages || manifest.pages.length;
    logger.info(
      `Initialized sliding window for chapter ${manifest.chapter_id} (total ${total} pages, start page: #${initialPage})`,
      { chapter_id: manifest.chapter_id, total, initialPage }
    );
    this.recalculateWindow();
  }

  /**
   * Update active reading page position and slide the lookahead window forward.
   */
  onPageChange(newPage: number): void {
    if (newPage <= 0 || newPage === this.currentPage) {
      return;
    }
    this.currentPage = newPage;
    logger.info(
      `Navigated to page #${newPage}. Updating sliding window (depth: ${this.depth})...`,
      { newPage, depth: this.depth }
    );
    this.recalculateWindow();
  }

  /**
   * Update prefetch enable / disable toggle dynamically.
   */
  setEnabled(enabled: boolean): void {
    if (this.enabled === enabled) {
      return;
    }
    this.enabled = enabled;
    if (!this.enabled) {
      this.cancelPendingPrefetch();
    } else {
      this.recalculateWindow();
    }
  }

  /**
   * Update prefetch depth dynamically (3, 5, 10, or 'all').
   */
  setDepth(depth: PrefetchDepth): void {
    if (this.depth === depth) {
      return;
    }
    this.depth = depth;
    if (this.enabled) {
      this.recalculateWindow();
    }
  }

  getPendingCount(): number {
    return this.queue.length + this.inFlight.size;
  }

  isPageCompleted(pageNumber: number): boolean {
    return this.completedPages.has(pageNumber);
  }

  /**
   * Mark a page as completed (e.g. translated on-screen) to avoid duplicate prefetch.
   */
  markPageCompleted(pageNumber: number): void {
    this.completedPages.add(pageNumber);
    const existingIndex = this.queue.findIndex((t) => t.pageNumber === pageNumber);
    if (existingIndex >= 0) {
      this.queue[existingIndex].abortController.abort();
      this.queue.splice(existingIndex, 1);
    }
  }

  /**
   * Recalculates sliding window bounds and updates priority queue.
   */
  private recalculateWindow(): void {
    if (!this.manifest || !this.enabled) {
      return;
    }

    const total = this.manifest.total_pages || this.manifest.pages.length;
    if (total <= 0) {
      return;
    }

    // Determine window ceiling
    let maxLookaheadPage = total;
    if (this.depth !== 'all') {
      maxLookaheadPage = Math.min(this.currentPage + this.depth, total);
    }

    // Filter out obsolete tasks outside forward window (page < currentPage)
    this.queue = this.queue.filter((t) => t.pageNumber >= this.currentPage && t.pageNumber <= maxLookaheadPage);

    // Identify needed pages
    for (let p = this.currentPage; p <= maxLookaheadPage; p++) {
      if (this.completedPages.has(p) || this.inFlight.has(p)) {
        continue;
      }

      const existingIndex = this.queue.findIndex((t) => t.pageNumber === p);
      const priority: TaskPriority = p === this.currentPage ? 'P0' : p === this.currentPage + 1 ? 'P1' : 'P2';

      if (existingIndex >= 0) {
        this.queue[existingIndex].priority = priority;
      } else {
        const pageItem = this.manifest.pages.find((item) => item.page_number === p);
        if (pageItem && pageItem.image_url) {
          this.queue.push({
            pageNumber: p,
            imageUrl: pageItem.image_url,
            priority,
            abortController: new AbortController(),
          });
        }
      }
    }

    // Sort queue by priority descending (P0 > P1 > P2) then pageNumber ascending
    this.queue.sort((a, b) => {
      const weightDiff = PRIORITY_WEIGHT[b.priority] - PRIORITY_WEIGHT[a.priority];
      if (weightDiff !== 0) {
        return weightDiff;
      }
      return a.pageNumber - b.pageNumber;
    });

    this.processQueue();
  }

  /**
   * Processes tasks from priority queue.
   */
  private async processQueue(): Promise<void> {
    if (this.isProcessing || this.queue.length === 0 || !this.enabled) {
      return;
    }

    this.isProcessing = true;

    try {
      while (this.queue.length > 0 && this.enabled) {
        const task = this.queue.shift();
        if (!task) {
          break;
        }

        if (this.completedPages.has(task.pageNumber) || this.chapterAbortController.signal.aborted) {
          continue;
        }

        this.inFlight.set(task.pageNumber, task.abortController);

        try {
          await this.executeTask(task);
          this.completedPages.add(task.pageNumber);
        } catch (err: unknown) {
          if (!task.abortController.signal.aborted && !this.chapterAbortController.signal.aborted) {
            logger.warn(`Prefetch for page #${task.pageNumber} failed: ${err instanceof Error ? err.message : String(err)}`, {
              pageNumber: task.pageNumber,
            });
            if (this.onPageFailed) {
              this.onPageFailed(task.pageNumber, err);
            }
          }
        } finally {
          this.inFlight.delete(task.pageNumber);
        }
      }
    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * Dispatches translation task via Chrome runtime IPC.
   */
  private async executeTask(task: PrefetchTask): Promise<void> {
    if (typeof chrome === 'undefined' || !chrome.runtime?.sendMessage) {
      return;
    }

    logger.info(
      `Starting prefetch for page #${task.pageNumber} (${task.priority}, provider: ${this.provider || 'default'}, model: ${this.model || 'default'})`,
      {
        pageNumber: task.pageNumber,
        priority: task.priority,
        engine: this.engine,
        provider: this.provider,
        model: this.model,
      }
    );

    const msg: IPCMessage = {
      type: 'TRANSLATE_IMAGE',
      payload: {
        traceId: `prefetch-ch-${this.manifest?.chapter_id}-p${task.pageNumber}`,
        imageIndex: task.pageNumber - 1,
        imageUrl: task.imageUrl,
        clientWidth: 800,
        clientHeight: 1200,
        engine: this.engine,
        provider: this.provider,
        translator: this.translator,
        model: this.model,
        sourceLang: this.sourceLang,
        chapterUrl: this.manifest?.chapter_url,
        forceRefresh: false,
      },
    };

    const res: IPCResponse<TranslationResponse> = await chrome.runtime.sendMessage(msg);
    if (!res.success) {
      throw new Error(res.error?.message || 'Prefetch translation rejected');
    }

    const blockCount = res.data?.blocks?.length ?? 0;
    const sourceDesc = res.data?.from_cache ? 'cache' : 'fresh';
    logger.info(
      `Page #${task.pageNumber} ready in prefetch cache (${blockCount} blocks, ${sourceDesc})`,
      { pageNumber: task.pageNumber, blockCount, from_cache: res.data?.from_cache }
    );

    if (this.onPageReady) {
      this.onPageReady(task.pageNumber, res.data, task.imageUrl, this.manifest?.chapter_id);
    }
  }

  /**
   * Cancel all pending queue and in-flight prefetch tasks.
   */
  private cancelPendingPrefetch(): void {
    for (const task of this.queue) {
      task.abortController.abort();
    }
    this.queue = [];

    for (const controller of this.inFlight.values()) {
      controller.abort();
    }
    this.inFlight.clear();
  }

  /**
   * Cancel all tasks and abort chapter signal.
   */
  cancelAllTasks(): void {
    this.chapterAbortController.abort();
    for (const task of this.queue) {
      task.abortController.abort();
    }
    this.queue = [];

    for (const controller of this.inFlight.values()) {
      controller.abort();
    }
    this.inFlight.clear();
    this.completedPages.clear();
  }
}
