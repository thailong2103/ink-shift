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
  forceRefresh?: boolean;
  cancelRequeues?: number;
}

export interface PrefetchSchedulerOptions {
  enabled?: boolean;
  depth?: PrefetchDepth;
  engine?: EngineMode;
  provider?: string;
  translator?: string;
  model?: string;
  customPrompt?: string;
  safeMask?: boolean;
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
  private customPrompt?: string;
  private safeMask?: boolean;
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
    this.customPrompt = options?.customPrompt;
    this.safeMask = options?.safeMask !== undefined ? options.safeMask : true;
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
    customPrompt?: string;
    safeMask?: boolean;
  }): void {
    if (config.engine !== undefined) this.engine = config.engine;
    if (config.provider !== undefined) this.provider = config.provider;
    if (config.translator !== undefined) this.translator = config.translator;
    if (config.model !== undefined) this.model = config.model;
    if (config.customPrompt !== undefined) this.customPrompt = config.customPrompt;
    if (config.safeMask !== undefined) this.safeMask = config.safeMask;
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
   * Resets pending and completed tasks for forced re-scan, re-evaluating the current window with forceRefresh=true on the active page.
   */
  resetForRescan(pageNumber?: number): void {
    this.cancelPendingPrefetch();
    this.completedPages.clear();
    if (pageNumber !== undefined && pageNumber > 0) {
      this.currentPage = pageNumber;
    }
    logger.info(
      `Resetting prefetch queue for RESCAN (chapter: ${this.manifest?.chapter_id || 'unknown'}, page: #${this.currentPage})...`
    );
    this.recalculateWindow(true);
  }

  /**
   * Recalculates sliding window bounds and updates priority queue.
   */
  private recalculateWindow(forceRefreshCurrentPage: boolean = false): void {
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
    this.queue = this.queue.filter((t) => {
      if (t.pageNumber >= this.currentPage && t.pageNumber <= maxLookaheadPage) {
        return true;
      }
      t.abortController.abort();
      return false;
    });

    // Abort in-flight prefetch tasks that fell outside the active sliding window,
    // or distant lower-priority in-flight tasks when the active page needs immediate service
    const urgentPagePending =
      !this.completedPages.has(this.currentPage) && !this.inFlight.has(this.currentPage);
    for (const [pageNum, controller] of Array.from(this.inFlight.entries())) {
      if (
        pageNum < this.currentPage ||
        pageNum > maxLookaheadPage ||
        (urgentPagePending && pageNum > this.currentPage)
      ) {
        controller.abort();
        this.inFlight.delete(pageNum);
      }
    }

    // Identify needed pages
    for (let p = this.currentPage; p <= maxLookaheadPage; p++) {
      if (this.completedPages.has(p) || this.inFlight.has(p)) {
        continue;
      }

      const existingIndex = this.queue.findIndex((t) => t.pageNumber === p);
      const priority: TaskPriority = p === this.currentPage ? 'P0' : p === this.currentPage + 1 ? 'P1' : 'P2';
      const isCurrentPage = p === this.currentPage;
      const taskForceRefresh = isCurrentPage && forceRefreshCurrentPage;

      if (existingIndex >= 0) {
        this.queue[existingIndex].priority = priority;
        if (taskForceRefresh) {
          this.queue[existingIndex].forceRefresh = true;
        }
      } else {
        const pageItem = this.manifest.pages.find((item) => item.page_number === p);
        if (pageItem && pageItem.image_url) {
          this.queue.push({
            pageNumber: p,
            imageUrl: pageItem.image_url,
            priority,
            abortController: new AbortController(),
            forceRefresh: taskForceRefresh,
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
          const resData = await this.executeTask(task);
          if (
            resData &&
            !resData.is_fallback &&
            !task.abortController.signal.aborted &&
            !this.chapterAbortController.signal.aborted
          ) {
            this.completedPages.add(task.pageNumber);
          }
        } catch (err: unknown) {
          const errMsg = err instanceof Error ? err.message : String(err);
          const isAbortMsg =
            errMsg.toLowerCase().includes('aborted') || errMsg.toLowerCase().includes('cancelled');
          if (
            !task.abortController.signal.aborted &&
            !this.chapterAbortController.signal.aborted &&
            !isAbortMsg
          ) {
            logger.warn(`Prefetch for page #${task.pageNumber} failed: ${errMsg}`, {
              pageNumber: task.pageNumber,
            });
            if (this.onPageFailed) {
              this.onPageFailed(task.pageNumber, err);
            }
          } else if (isAbortMsg && !task.abortController.signal.aborted) {
            task.abortController.abort();
          }
        } finally {
          if (this.inFlight.get(task.pageNumber) === task.abortController) {
            this.inFlight.delete(task.pageNumber);
          }
        }

        if (
          task.abortController.signal.aborted &&
          (task.cancelRequeues ?? 0) < 2 &&
          this.enabled &&
          this.manifest &&
          !this.chapterAbortController.signal.aborted &&
          !this.completedPages.has(task.pageNumber) &&
          !this.inFlight.has(task.pageNumber) &&
          !this.queue.some((q) => q.pageNumber === task.pageNumber)
        ) {
          const total = this.manifest.total_pages || this.manifest.pages.length;
          const maxLookaheadPage =
            this.depth === 'all' ? total : Math.min(this.currentPage + this.depth, total);
          if (task.pageNumber >= this.currentPage && task.pageNumber <= maxLookaheadPage) {
            const pageItem = this.manifest.pages.find((item) => item.page_number === task.pageNumber);
            if (pageItem && pageItem.image_url) {
              const priority: TaskPriority =
                task.pageNumber === this.currentPage
                  ? 'P0'
                  : task.pageNumber === this.currentPage + 1
                    ? 'P1'
                    : 'P2';
              this.queue.push({
                pageNumber: task.pageNumber,
                imageUrl: pageItem.image_url,
                priority,
                abortController: new AbortController(),
                forceRefresh: task.forceRefresh,
                cancelRequeues: (task.cancelRequeues ?? 0) + 1,
              });
              this.queue.sort((a, b) => {
                const weightDiff = PRIORITY_WEIGHT[b.priority] - PRIORITY_WEIGHT[a.priority];
                return weightDiff !== 0 ? weightDiff : a.pageNumber - b.pageNumber;
              });
            }
          }
        }
      }
    } finally {
      this.isProcessing = false;
    }
  }

  /**
   * Dispatches translation task via Chrome runtime IPC.
   */
  private async executeTask(task: PrefetchTask): Promise<TranslationResponse | undefined> {
    if (typeof chrome === 'undefined' || !chrome.runtime?.sendMessage) {
      return undefined;
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
        chapterUrl: this.manifest?.chapter_url,
        forceRefresh: Boolean(task.forceRefresh),
        custom_prompt: this.customPrompt || undefined,
        safe_mask: this.safeMask !== undefined ? this.safeMask : undefined,
        priority: task.priority,
      },
    };

    const res: IPCResponse<TranslationResponse> = await chrome.runtime.sendMessage(msg);
    if (task.abortController.signal.aborted || this.chapterAbortController.signal.aborted) {
      return undefined;
    }
    if (!res.success) {
      if (res.error?.code === 'TRANSLATION_CANCELLED') {
        task.abortController.abort();
        return undefined;
      }
      throw new Error(res.error?.message || 'Prefetch translation rejected');
    }

    if (res.data?.is_fallback) {
      logger.warn(
        `Page #${task.pageNumber} returned untranslated fallback; not caching as completed`,
        { pageNumber: task.pageNumber }
      );
      return res.data;
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
    return res.data;
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
