/**
 * Service Worker In-Memory Ring Buffer & Debounced Telemetry Batcher.
 *
 * Collects log entries from content scripts, service worker, and popups,
 * buffers them with an upper memory limit, and dispatches batched HTTP payloads
 * to the FastAPI backend with sub-millisecond precision.
 */

import type { BackendGateway } from './backend_gateway';
import type { TelemetryLogEntry } from '../shared/telemetry_types';

export interface TelemetryBatcherOptions {
  /**
   * Maximum entries held in-memory before dropping the oldest logs (ring buffer).
   * Default: 100.
   */
  maxCapacity?: number;
  /**
   * Milliseconds of inactivity or buffer accumulation before auto-flush.
   * Default: 1500 ms.
   */
  flushDebounceMs?: number;
  /**
   * Number of queued items that triggers an immediate flush without waiting for timer.
   * Default: 10.
   */
  batchSizeThreshold?: number;
}

export class TelemetryBatcher {
  private readonly buffer: TelemetryLogEntry[] = [];
  private readonly maxCapacity: number;
  private readonly flushDebounceMs: number;
  private readonly batchSizeThreshold: number;
  private timerId: ReturnType<typeof setTimeout> | null = null;
  private isFlushing: boolean = false;

  constructor(
    private readonly gateway: BackendGateway,
    options?: TelemetryBatcherOptions
  ) {
    this.maxCapacity = options?.maxCapacity ?? 100;
    this.flushDebounceMs = options?.flushDebounceMs ?? 1500;
    this.batchSizeThreshold = options?.batchSizeThreshold ?? 10;
  }

  /**
   * Enqueues a structured telemetry log entry into the ring buffer.
   *
   * - If buffer exceeds maxCapacity, drops oldest entries.
   * - If entry level is 'ERROR', flushes immediately without debouncing.
   * - If buffer length reaches batchSizeThreshold, flushes immediately.
   * - Otherwise, resets/schedules the debounced timer.
   */
  enqueue(entry: TelemetryLogEntry): void {
    if (this.buffer.length >= this.maxCapacity) {
      this.buffer.shift(); // Ring buffer drop oldest
    }
    this.buffer.push(entry);

    if (entry.level === 'ERROR' || this.buffer.length >= this.batchSizeThreshold) {
      this.clearTimer();
      void this.flush();
      return;
    }

    this.scheduleDebounce();
  }

  /**
   * Dispatches all buffered telemetry logs to the backend gateway.
   */
  async flush(): Promise<boolean> {
    this.clearTimer();

    if (this.buffer.length === 0) {
      return true;
    }

    // Drain buffer
    const batch = this.buffer.splice(0, this.buffer.length);
    this.isFlushing = true;

    try {
      return await this.gateway.postTelemetryLogs({ logs: batch });
    } catch {
      // Fire-and-forget: gateway handles internal silencing, but safeguard here
      return false;
    } finally {
      this.isFlushing = false;
    }
  }

  /**
   * Returns current count of queued items awaiting flush.
   */
  getPendingCount(): number {
    return this.buffer.length;
  }

  /**
   * Cleans up pending timers and flushes remaining items.
   */
  async destroy(): Promise<void> {
    this.clearTimer();
    if (this.buffer.length > 0) {
      await this.flush();
    }
  }

  private scheduleDebounce(): void {
    if (this.timerId !== null) {
      return; // Already scheduled
    }

    this.timerId = setTimeout(() => {
      this.timerId = null;
      void this.flush();
    }, this.flushDebounceMs);
  }

  private clearTimer(): void {
    if (this.timerId !== null) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
  }
}
