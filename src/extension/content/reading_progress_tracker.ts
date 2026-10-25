/**
 * Reading Progress Tracker & Observer Debounce.
 *
 * Tracks reading position across single-page flip readers (via URL monitoring)
 * and vertical webtoon readers (via IntersectionObserver with threshold 0.5).
 * Enforces a 2-second dwell debounce before dispatching UPDATE_READING_PROGRESS IPC.
 */

import type { IPCMessage } from '../shared/ipc_types';
import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('Tracker');

export interface ProgressTrackerOptions {
  debounceMs?: number;
  onProgressUpdate?: (pageNumber: number) => void;
}

export class ReadingProgressTracker {
  private chapterId: string;
  private debounceMs: number;
  private onProgressUpdate?: (pageNumber: number) => void;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private intersectionObserver: IntersectionObserver | null = null;
  private lastReportedPage: number = 0;
  private activeCandidatePage: number = 0;

  constructor(chapterId: string, options?: ProgressTrackerOptions) {
    this.chapterId = chapterId;
    this.debounceMs = options?.debounceMs ?? 2000;
    this.onProgressUpdate = options?.onProgressUpdate;
  }

  /**
   * Record page view event and schedule debounced IPC sync.
   */
  trackPage(pageNumber: number): void {
    if (pageNumber <= 0 || pageNumber === this.lastReportedPage) {
      return;
    }

    this.activeCandidatePage = pageNumber;

    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
    }

    this.debounceTimer = setTimeout(() => {
      this.flushProgress();
    }, this.debounceMs);
  }

  /**
   * Immediately dispatch pending progress to backend without waiting for timer.
   */
  async flushProgress(): Promise<void> {
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }

    const targetPage = this.activeCandidatePage;
    if (targetPage <= 0 || targetPage === this.lastReportedPage) {
      return;
    }

    this.lastReportedPage = targetPage;
    if (this.onProgressUpdate) {
      this.onProgressUpdate(targetPage);
    }

    if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
      const msg: IPCMessage = {
        type: 'UPDATE_READING_PROGRESS',
        payload: {
          chapter_id: this.chapterId,
          page_number: targetPage,
        },
      };
      try {
        await chrome.runtime.sendMessage(msg);
      } catch (err) {
        logger.warn(`Failed to dispatch reading progress: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }

  /**
   * Attach IntersectionObserver to vertical strip manga images.
   */
  observeStripImages(images: HTMLImageElement[]): void {
    this.disconnectObserver();

    if (typeof IntersectionObserver === 'undefined') {
      return;
    }

    const imageMap = new Map<Element, number>();
    this.intersectionObserver = new IntersectionObserver(
      (entries) => {
        let maxRatio = 0;
        let mostVisiblePage = 0;

        for (const entry of entries) {
          if (entry.isIntersecting && entry.intersectionRatio > maxRatio) {
            maxRatio = entry.intersectionRatio;
            const pageNum = imageMap.get(entry.target);
            if (pageNum) {
              mostVisiblePage = pageNum;
            }
          }
        }

        if (mostVisiblePage > 0 && maxRatio >= 0.5) {
          this.trackPage(mostVisiblePage);
        }
      },
      { threshold: [0.5] }
    );

    images.forEach((img, idx) => {
      const pageNum = idx + 1;
      imageMap.set(img, pageNum);
      this.intersectionObserver?.observe(img);
    });
  }

  /**
   * Hook into single-page URL changes (e.g. MangaDex /chapter/{id}/{page}).
   */
  handleUrlChange(url: URL): void {
    const parts = url.pathname.split('/').filter(Boolean);
    if (parts.length >= 3 && parts[parts.length - 2] === this.chapterId) {
      const pageNum = parseInt(parts[parts.length - 1], 10);
      if (!isNaN(pageNum) && pageNum > 0) {
        this.trackPage(pageNum);
      }
    }
  }

  private disconnectObserver(): void {
    if (this.intersectionObserver) {
      this.intersectionObserver.disconnect();
      this.intersectionObserver = null;
    }
  }

  /**
   * Clean up observers and timers.
   */
  destroy(): void {
    if (this.debounceTimer !== null) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
    this.disconnectObserver();
  }
}
