import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { TelemetryBatcher } from '../../src/extension/background/telemetry_batcher';
import type { BackendGateway } from '../../src/extension/background/backend_gateway';
import type { TelemetryLogEntry } from '../../src/extension/shared/telemetry_types';

describe('TelemetryBatcher', () => {
  let mockGateway: BackendGateway;
  let postLogsSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    postLogsSpy = vi.fn().mockResolvedValue(true);
    mockGateway = {
      postTelemetryLogs: postLogsSpy,
    } as unknown as BackendGateway;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('debounces log flush after flushDebounceMs interval', async () => {
    const batcher = new TelemetryBatcher(mockGateway, {
      flushDebounceMs: 1500,
      batchSizeThreshold: 10,
    });

    const entry: TelemetryLogEntry = {
      timestamp_ms: 1730000000001,
      level: 'INFO',
      module: 'CS',
      message: 'Image detected',
    };

    batcher.enqueue(entry);
    expect(batcher.getPendingCount()).toBe(1);
    expect(postLogsSpy).not.toHaveBeenCalled();

    // Advance halfway: should still be buffered
    vi.advanceTimersByTime(1000);
    expect(postLogsSpy).not.toHaveBeenCalled();
    expect(batcher.getPendingCount()).toBe(1);

    // Advance past 1500ms debounce
    vi.advanceTimersByTime(501);
    await Promise.resolve(); // Allow microtasks to complete

    expect(postLogsSpy).toHaveBeenCalledTimes(1);
    expect(postLogsSpy).toHaveBeenCalledWith({
      logs: [entry],
    });
    expect(batcher.getPendingCount()).toBe(0);
  });

  it('triggers immediate flush when batch reaches size threshold', async () => {
    const batcher = new TelemetryBatcher(mockGateway, {
      flushDebounceMs: 1500,
      batchSizeThreshold: 5,
    });

    for (let i = 1; i <= 4; i++) {
      batcher.enqueue({
        timestamp_ms: 1730000000000 + i,
        level: 'DEBUG',
        module: 'Prefetch',
        message: `Step ${i}`,
      });
    }

    expect(postLogsSpy).not.toHaveBeenCalled();
    expect(batcher.getPendingCount()).toBe(4);

    // 5th item hits batchSizeThreshold=5
    batcher.enqueue({
      timestamp_ms: 1730000000005,
      level: 'DEBUG',
      module: 'Prefetch',
      message: 'Step 5',
    });

    await Promise.resolve();
    expect(postLogsSpy).toHaveBeenCalledTimes(1);
    const sentBatch = postLogsSpy.mock.calls[0][0];
    expect(sentBatch.logs).toHaveLength(5);
    expect(batcher.getPendingCount()).toBe(0);
  });

  it('immediately flushes when an ERROR level log is enqueued', async () => {
    const batcher = new TelemetryBatcher(mockGateway, {
      flushDebounceMs: 1500,
      batchSizeThreshold: 10,
    });

    batcher.enqueue({
      timestamp_ms: 1730000000001,
      level: 'INFO',
      module: 'CS',
      message: 'Scanning DOM',
    });
    expect(postLogsSpy).not.toHaveBeenCalled();

    // Enqueue an ERROR
    const errorEntry: TelemetryLogEntry = {
      timestamp_ms: 1730000000002,
      level: 'ERROR',
      module: 'CS',
      message: 'Overlay injection failed',
    };
    batcher.enqueue(errorEntry);

    await Promise.resolve();
    expect(postLogsSpy).toHaveBeenCalledTimes(1);
    const sentBatch = postLogsSpy.mock.calls[0][0];
    expect(sentBatch.logs).toHaveLength(2);
    expect(sentBatch.logs[1]).toEqual(errorEntry);
    expect(batcher.getPendingCount()).toBe(0);
  });

  it('drops oldest entries when exceeding maxCapacity (ring buffer)', () => {
    const batcher = new TelemetryBatcher(mockGateway, {
      maxCapacity: 3,
      flushDebounceMs: 10000,
      batchSizeThreshold: 100, // Do not threshold flush
    });

    batcher.enqueue({ timestamp_ms: 1, level: 'INFO', module: 'M', message: 'First' });
    batcher.enqueue({ timestamp_ms: 2, level: 'INFO', module: 'M', message: 'Second' });
    batcher.enqueue({ timestamp_ms: 3, level: 'INFO', module: 'M', message: 'Third' });
    expect(batcher.getPendingCount()).toBe(3);

    // 4th item pushes out First
    batcher.enqueue({ timestamp_ms: 4, level: 'INFO', module: 'M', message: 'Fourth' });
    expect(batcher.getPendingCount()).toBe(3);

    void batcher.flush();
    const sentBatch = postLogsSpy.mock.calls[0][0];
    expect(sentBatch.logs).toHaveLength(3);
    expect(sentBatch.logs[0].message).toBe('Second');
    expect(sentBatch.logs[1].message).toBe('Third');
    expect(sentBatch.logs[2].message).toBe('Fourth');
  });

  it('handles manual flush and empty buffer gracefully', async () => {
    const batcher = new TelemetryBatcher(mockGateway);
    const result = await batcher.flush();
    expect(result).toBe(true);
    expect(postLogsSpy).not.toHaveBeenCalled();
  });

  it('destroy flushes pending logs and clears active timers', async () => {
    const batcher = new TelemetryBatcher(mockGateway, {
      flushDebounceMs: 5000,
    });

    batcher.enqueue({
      timestamp_ms: 100,
      level: 'INFO',
      module: 'SW',
      message: 'Worker stopping',
    });

    await batcher.destroy();
    expect(postLogsSpy).toHaveBeenCalledTimes(1);
    expect(batcher.getPendingCount()).toBe(0);

    // Timers should not fire again
    vi.advanceTimersByTime(6000);
    expect(postLogsSpy).toHaveBeenCalledTimes(1);
  });

  it('tolerates gateway network rejection without throwing', async () => {
    postLogsSpy.mockRejectedValueOnce(new Error('Network dead'));
    const batcher = new TelemetryBatcher(mockGateway, {
      flushDebounceMs: 10000,
    });

    batcher.enqueue({
      timestamp_ms: 100,
      level: 'INFO',
      module: 'CS',
      message: 'Some info',
    });

    await expect(batcher.flush()).resolves.toBe(false);
  });
});
