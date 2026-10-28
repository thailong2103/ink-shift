import { describe, it, expect, vi, beforeEach } from 'vitest';
import { handleIPCMessage } from '../../src/extension/background/service_worker';
import type { BackendGateway } from '../../src/extension/background/backend_gateway';
import type { TranslationResponse } from '../../src/types/contract';
import type { IPCMessage, TranslateImagePayload } from '../../src/extension/shared/ipc_types';

describe('Service Worker Message Handling', () => {
  let mockGateway: Partial<BackendGateway>;

  beforeEach(() => {
    vi.restoreAllMocks();
    mockGateway = {
      checkHealth: vi.fn(),
      checkCache: vi.fn(),
      requestTranslation: vi.fn(),
    };

    // Setup global chrome mock
    (globalThis as unknown as { chrome: unknown }).chrome = {
      action: {
        setBadgeText: vi.fn(),
        setBadgeBackgroundColor: vi.fn(),
      },
    };
  });

  it('handles CHECK_BACKEND_HEALTH message successfully', async () => {
    mockGateway.checkHealth = vi.fn().mockResolvedValue({
      status: 'healthy',
      engine: 'cloud',
      version: '0.1.0',
    });

    const msg: IPCMessage = { type: 'CHECK_BACKEND_HEALTH', traceId: 'trace-h1' };
    const response = await handleIPCMessage(msg, undefined, mockGateway as BackendGateway);

    expect(response.success).toBe(true);
    expect(response.traceId).toBe('trace-h1');
    if (response.success) {
      expect(response.data.status).toBe('healthy');
    }
  });

  it('handles TRANSLATE_IMAGE on cache hit without re-translating', async () => {
    const cachedResponse: TranslationResponse = {
      success: true,
      page_hash: 'hash-hit',
      engine_used: 'cloud',
      execution_time_ms: 10,
      from_cache: true,
      blocks: [],
    };

    mockGateway.checkCache = vi.fn().mockResolvedValue(cachedResponse);

    const payload: TranslateImagePayload = {
      traceId: 'trace-img-1',
      imageIndex: 0,
      imageUrl: 'https://example.com/page-1.jpg',
      clientWidth: 800,
      clientHeight: 1200,
    };

    const mockFetcher = vi.fn().mockResolvedValue({
      sha256Hex: 'hash-hit',
      base64: 'fake-base64',
      mimeType: 'image/jpeg',
      buffer: new ArrayBuffer(0),
      sizeBytes: 0,
    });

    const msg: IPCMessage = { type: 'TRANSLATE_IMAGE', payload };
    const response = await handleIPCMessage(msg, undefined, mockGateway as BackendGateway, mockFetcher);

    expect(response.success).toBe(true);
    expect(response.traceId).toBe('trace-img-1');
    expect(mockGateway.checkCache).toHaveBeenCalledWith('hash-hit', undefined, undefined);
    expect(mockGateway.requestTranslation).not.toHaveBeenCalled();
  });

  it('handles TRANSLATE_IMAGE on cache miss by requesting backend translation', async () => {
    const freshResponse: TranslationResponse = {
      success: true,
      page_hash: 'hash-miss',
      engine_used: 'cloud',
      execution_time_ms: 500,
      from_cache: false,
      blocks: [],
    };

    mockGateway.checkCache = vi.fn().mockResolvedValue(null);
    mockGateway.requestTranslation = vi.fn().mockResolvedValue(freshResponse);

    const payload: TranslateImagePayload = {
      traceId: 'trace-img-2',
      imageIndex: 1,
      imageUrl: 'https://example.com/page-2.jpg',
      clientWidth: 800,
      clientHeight: 1200,
      engine: 'cloud',
    };

    const mockFetcher = vi.fn().mockResolvedValue({
      sha256Hex: 'hash-miss',
      base64: 'data:image/jpeg;base64,fresh',
      mimeType: 'image/jpeg',
      buffer: new ArrayBuffer(0),
      sizeBytes: 0,
    });

    const msg: IPCMessage = { type: 'TRANSLATE_IMAGE', payload };
    const response = await handleIPCMessage(msg, undefined, mockGateway as BackendGateway, mockFetcher);

    expect(response.success).toBe(true);
    expect(response.traceId).toBe('trace-img-2');
    expect(mockGateway.requestTranslation).toHaveBeenCalled();
  });

  it('bypasses SQLite cache and forces translation when forceRefresh is true', async () => {
    const forcedResponse: TranslationResponse = {
      success: true,
      page_hash: 'hash-forced',
      engine_used: 'local',
      execution_time_ms: 320,
      from_cache: false,
      blocks: [],
    };

    mockGateway.checkCache = vi.fn().mockResolvedValue({
      success: true,
      page_hash: 'hash-forced',
      engine_used: 'old-engine',
      execution_time_ms: 10,
      from_cache: true,
      blocks: [],
    });
    mockGateway.requestTranslation = vi.fn().mockResolvedValue(forcedResponse);

    const payload: TranslateImagePayload = {
      traceId: 'trace-forced-1',
      imageIndex: 0,
      imageUrl: 'https://example.com/page-rescan.jpg',
      clientWidth: 800,
      clientHeight: 1200,
      engine: 'local',
      forceRefresh: true,
    };

    const mockFetcher = vi.fn().mockResolvedValue({
      sha256Hex: 'hash-forced',
      base64: 'data:image/jpeg;base64,forced',
      mimeType: 'image/jpeg',
      buffer: new ArrayBuffer(0),
      sizeBytes: 0,
    });

    const msg: IPCMessage = { type: 'TRANSLATE_IMAGE', payload };
    const response = await handleIPCMessage(msg, undefined, mockGateway as BackendGateway, mockFetcher);

    expect(response.success).toBe(true);
    expect(response.traceId).toBe('trace-forced-1');
    // checkCache must NOT be called
    expect(mockGateway.checkCache).not.toHaveBeenCalled();
    // requestTranslation must receive force_refresh: true
    expect(mockGateway.requestTranslation).toHaveBeenCalledWith(
      expect.objectContaining({
        force_refresh: true,
        image_hash: 'hash-forced',
      })
    );
  });

  it('updates tab badge on UPDATE_TAB_BADGE message', async () => {
    const msg: IPCMessage = {
      type: 'UPDATE_TAB_BADGE',
      payload: { translated: 3, total: 10 },
    };

    const sender = { tab: { id: 42 } } as chrome.runtime.MessageSender;
    const response = await handleIPCMessage(msg, sender, mockGateway as BackendGateway);

    expect(response.success).toBe(true);
    expect(chrome.action.setBadgeText).toHaveBeenCalledWith({
      text: '3/10',
      tabId: 42,
    });
    expect(chrome.action.setBadgeBackgroundColor).toHaveBeenCalledWith({
      color: '#2563eb',
      tabId: 42,
    });
  });

  it('handles CHECK_BACKEND_HEALTH failure by returning error response', async () => {
    mockGateway.checkHealth = vi.fn().mockRejectedValue(new Error('Connection failed'));

    const msg: IPCMessage = { type: 'CHECK_BACKEND_HEALTH', traceId: 'trace-fail' };
    const response = await handleIPCMessage(msg, undefined, mockGateway as BackendGateway);

    expect(response.success).toBe(false);
    expect(response.traceId).toBe('trace-fail');
    if (!response.success) {
      expect(response.error.code).toBe('HEALTH_CHECK_FAILED');
      expect(response.error.message).toBe('Connection failed');
    }
  });

  it('handles TRANSLATE_IMAGE error by returning error response with traceId', async () => {
    const payload: TranslateImagePayload = {
      traceId: 'trace-err-1',
      imageIndex: 0,
      imageUrl: 'https://example.com/bad.jpg',
      clientWidth: 800,
      clientHeight: 1200,
    };

    const mockFetcher = vi.fn().mockRejectedValue(new Error('Failed to fetch image: 404 Not Found'));
    const msg: IPCMessage = { type: 'TRANSLATE_IMAGE', payload };
    const response = await handleIPCMessage(msg, undefined, mockGateway as BackendGateway, mockFetcher);

    expect(response.success).toBe(false);
    expect(response.traceId).toBe('trace-err-1');
    if (!response.success) {
      expect(response.error.code).toBe('IMAGE_TRANSLATION_FAILED');
    }
  });

  it('handles SPA_NAVIGATION_DETECTED and unsupported message types', async () => {
    const spaMsg: IPCMessage = {
      type: 'SPA_NAVIGATION_DETECTED',
      payload: { url: 'https://example.com/ch2' },
    };
    const spaRes = await handleIPCMessage(spaMsg, undefined, mockGateway as BackendGateway);
    expect(spaRes.success).toBe(true);

    const unknownMsg = { type: 'UNKNOWN_COMMAND' } as unknown as IPCMessage;
    const unknownRes = await handleIPCMessage(unknownMsg, undefined, mockGateway as BackendGateway);
    expect(unknownRes.success).toBe(false);
    if (!unknownRes.success) {
      expect(unknownRes.error.code).toBe('UNSUPPORTED_IPC_TYPE');
    }
  });

  it('deduplicates simultaneous TRANSLATE_IMAGE requests for identical image hash (Singleflight)', async () => {
    const mockTranslation: TranslationResponse = {
      success: true,
      page_hash: 'same-hash-123',
      engine_used: 'cloud',
      execution_time_ms: 100,
      from_cache: false,
      blocks: [],
    };

    mockGateway.checkCache = vi.fn().mockResolvedValue(null);
    let translationResolver: (res: TranslationResponse) => void;
    const slowTranslationPromise = new Promise<TranslationResponse>((resolve) => {
      translationResolver = resolve;
    });
    mockGateway.requestTranslation = vi.fn().mockReturnValue(slowTranslationPromise);

    const mockFetcher = vi.fn().mockResolvedValue({
      sha256Hex: 'same-hash-123',
      base64: 'fake-base64',
      mimeType: 'image/jpeg',
      buffer: new ArrayBuffer(0),
      sizeBytes: 0,
    });

    const payloadA: TranslateImagePayload = {
      traceId: 'trace-a',
      imageIndex: 0,
      imageUrl: 'https://example.com/p1.jpg',
      clientWidth: 800,
      clientHeight: 1200,
    };
    const payloadB: TranslateImagePayload = {
      traceId: 'trace-b',
      imageIndex: 0,
      imageUrl: 'https://example.com/p1.jpg',
      clientWidth: 800,
      clientHeight: 1200,
    };

    // Dispatch both concurrently
    const promiseA = handleIPCMessage(
      { type: 'TRANSLATE_IMAGE', payload: payloadA },
      undefined,
      mockGateway as BackendGateway,
      mockFetcher
    );
    const promiseB = handleIPCMessage(
      { type: 'TRANSLATE_IMAGE', payload: payloadB },
      undefined,
      mockGateway as BackendGateway,
      mockFetcher
    );

    // Resolve in-flight translation
    translationResolver!(mockTranslation);

    const [resA, resB] = await Promise.all([promiseA, promiseB]);

    expect(resA.success).toBe(true);
    expect(resB.success).toBe(true);
    expect(mockGateway.requestTranslation).toHaveBeenCalledTimes(1);
  });

  it('handles REPORT_CHAPTER_CONTEXT and UPDATE_READING_PROGRESS messages', async () => {
    mockGateway.reportContext = vi.fn().mockResolvedValue({
      success: true,
      chapter_id: 'ch-test',
      series_id: 's-test',
      pages_registered: 5,
    });
    mockGateway.updateReadingProgress = vi.fn().mockResolvedValue({
      success: true,
      chapter_id: 'ch-test',
      last_read_page: 2,
      status: 'reading',
    });

    const reportMsg: IPCMessage = {
      type: 'REPORT_CHAPTER_CONTEXT',
      payload: {
        series_id: 's-test',
        series_title: 'Test Series',
        source_domain: 'example.com',
        chapter_id: 'ch-test',
        chapter_ordinal: 1,
        chapter_label: 'Ch. 1',
        chapter_url: 'https://example.com/ch1',
        total_pages: 5,
        pages: [],
      },
    };
    const reportRes = await handleIPCMessage(reportMsg, undefined, mockGateway as BackendGateway);
    expect(reportRes.success).toBe(true);
    expect(mockGateway.reportContext).toHaveBeenCalledTimes(1);

    const progressMsg: IPCMessage = {
      type: 'UPDATE_READING_PROGRESS',
      payload: {
        chapter_id: 'ch-test',
        page_number: 2,
      },
    };
    const progressRes = await handleIPCMessage(progressMsg, undefined, mockGateway as BackendGateway);
    expect(progressRes.success).toBe(true);
    expect(mockGateway.updateReadingProgress).toHaveBeenCalledTimes(1);
  });

  it('handles FORWARD_TELEMETRY and enqueues entry into TelemetryBatcher', async () => {
    const mockBatcher = {
      enqueue: vi.fn(),
      flush: vi.fn().mockResolvedValue(true),
    };

    const telemetryMsg: IPCMessage = {
      type: 'FORWARD_TELEMETRY',
      payload: {
        timestamp_ms: 1730000000123,
        level: 'INFO',
        module: 'CS',
        message: 'Dispatched image #1',
      },
    };

    const res = await handleIPCMessage(
      telemetryMsg,
      undefined,
      mockGateway as BackendGateway,
      undefined,
      mockBatcher as any
    );

    expect(res.success).toBe(true);
    expect(mockBatcher.enqueue).toHaveBeenCalledWith(telemetryMsg.payload);
  });

  it('handles FLUSH_TELEMETRY and triggers TelemetryBatcher flush', async () => {
    const mockBatcher = {
      enqueue: vi.fn(),
      flush: vi.fn().mockResolvedValue(true),
    };

    const flushMsg: IPCMessage = {
      type: 'FLUSH_TELEMETRY',
    };

    const res = await handleIPCMessage(
      flushMsg,
      undefined,
      mockGateway as BackendGateway,
      undefined,
      mockBatcher as any
    );

    expect(res.success).toBe(true);
    expect(mockBatcher.flush).toHaveBeenCalledTimes(1);
  });

  it('handles CLEAR_CACHE IPC message and calls gateway.clearCache', async () => {
    mockGateway.clearCache = vi.fn().mockResolvedValue({
      success: true,
      deleted: 15,
      scope: 'all',
    });

    const clearMsg: IPCMessage = {
      type: 'CLEAR_CACHE',
      payload: { all: true },
    };

    const res = await handleIPCMessage(clearMsg, undefined, mockGateway as BackendGateway);

    expect(res.success).toBe(true);
    expect(mockGateway.clearCache).toHaveBeenCalledWith(true, undefined, undefined, undefined);
    if (res.success) {
      expect((res.data as any).deleted).toBe(15);
    }
  });
});

