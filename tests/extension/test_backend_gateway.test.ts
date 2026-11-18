import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { BackendGateway } from '../../src/extension/background/backend_gateway';
import type { TranslationResponse } from '../../src/types/contract';

describe('Backend Gateway & API Client', () => {
  const originalFetch = globalThis.fetch;
  let gateway: BackendGateway;

  beforeEach(() => {
    vi.restoreAllMocks();
    gateway = new BackendGateway('http://127.0.0.1:8000', {
      initialRetryDelayMs: 10, // Fast retries for testing
      maxRetries: 2,
    });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  describe('checkHealth', () => {
    it('returns healthy status when backend endpoint responds 200', async () => {
      const mockHealth = { status: 'healthy', engine: 'cloud', version: '0.1.0' };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(mockHealth),
      } as unknown as Response);

      const result = await gateway.checkHealth();
      expect(result.status).toBe('healthy');
      expect(result.engine).toBe('cloud');
    });

    it('throws structured error when health check fails', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('Connection refused'));

      await expect(gateway.checkHealth()).rejects.toThrow(/Connection refused/);
    });
  });

  describe('checkCache', () => {
    it('returns cached translation response on HTTP 200', async () => {
      const mockResponse: TranslationResponse = {
        success: true,
        page_hash: 'hash-abc',
        engine_used: 'cloud',
        execution_time_ms: 120,
        from_cache: true,
        blocks: [
          {
            id: 'b1',
            box: [100, 100, 200, 200],
            translated_text: 'Xin chào',
          },
        ],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(mockResponse),
      } as unknown as Response);

      const result = await gateway.checkCache('hash-abc');
      expect(result).not.toBeNull();
      expect(result?.page_hash).toBe('hash-abc');
      expect(result?.from_cache).toBe(true);
    });

    it('returns null on cache miss HTTP 404', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: vi.fn().mockResolvedValue({ error: { code: 'NOT_FOUND', message: 'Not in cache' } }),
      } as unknown as Response);

      const result = await gateway.checkCache('missing-hash');
      expect(result).toBeNull();
    });

    it('passes engine query parameter when specified', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          success: true,
          page_hash: 'hash-cloud',
          engine_used: 'cloud',
          execution_time_ms: 10,
          from_cache: true,
          blocks: [],
        }),
      } as unknown as Response);

      await gateway.checkCache('hash-cloud', 'cloud');
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/cache/hash-cloud?engine=cloud'),
        expect.any(Object)
      );
    });

    it('passes translator query parameter when specified', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          success: true,
          page_hash: 'hash-local',
          engine_used: 'local',
          execution_time_ms: 10,
          from_cache: true,
          blocks: [],
        }),
      } as unknown as Response);

      await gateway.checkCache('hash-local', 'local', 'llm-custom');
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/cache/hash-local?engine=local&translator=llm-custom'),
        expect.any(Object)
      );
    });
  });

  describe('clearCache', () => {
    it('sends DELETE /api/v1/cache?all=true when wiping cache', async () => {
      const mockResult = { success: true, deleted: 5, scope: 'all' };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(mockResult),
      } as unknown as Response);

      const result = await gateway.clearCache(true);
      expect(result.success).toBe(true);
      expect(result.deleted).toBe(5);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/cache?all=true'),
        expect.objectContaining({ method: 'DELETE' })
      );
    });

    it('sends DELETE /api/v1/cache?image_hash=... when deleting single entry', async () => {
      const mockResult = { success: true, deleted: 1, scope: 'single' };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(mockResult),
      } as unknown as Response);

      const result = await gateway.clearCache(false, 'hash-to-delete');
      expect(result.deleted).toBe(1);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/cache?image_hash=hash-to-delete'),
        expect.objectContaining({ method: 'DELETE' })
      );
    });
  });


  describe('requestTranslation', () => {
    it('returns TranslationResponse on HTTP 200', async () => {
      const mockResponse: TranslationResponse = {
        success: true,
        page_hash: 'hash-xyz',
        engine_used: 'cloud',
        execution_time_ms: 450,
        from_cache: false,
        blocks: [],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(mockResponse),
      } as unknown as Response);

      const result = await gateway.requestTranslation({
        image: 'base64data',
        image_hash: 'hash-xyz',
      });
      expect(result.page_hash).toBe('hash-xyz');
    });

    it('transmits provider and translator in POST request body', async () => {
      const mockResponse: TranslationResponse = {
        success: true,
        page_hash: 'hash-xyz',
        engine_used: 'cloud',
        execution_time_ms: 100,
        from_cache: false,
        blocks: [],
      };

      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue(mockResponse),
      } as unknown as Response);
      globalThis.fetch = fetchSpy;

      await gateway.requestTranslation({
        image: 'base64data',
        engine: 'cloud',
        provider: 'gemini',
        translator: 'google-free',
        target_lang: 'vi',
      });

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const [url, requestInit] = fetchSpy.mock.calls[0];
      expect(url).toBe('http://127.0.0.1:8000/api/v1/translate');
      const body = JSON.parse(requestInit.body);
      expect(body.provider).toBe('gemini');
      expect(body.translator).toBe('google-free');
      expect(body.engine).toBe('cloud');
    });

    it('fails immediately without retry on non-retryable 422 error', async () => {
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: vi.fn().mockResolvedValue({
          error: { code: 'CONTENT_SAFETY_BLOCKED', message: 'Flagged for safety' },
        }),
      } as unknown as Response);
      globalThis.fetch = fetchSpy;

      await expect(
        gateway.requestTranslation({ image: 'base64data', image_hash: 'hash-bad' })
      ).rejects.toThrow(/Flagged for safety/);

      // Must NOT retry 422
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });

    it('retries on 429 rate limit and succeeds on second attempt', async () => {
      const mockSuccess: TranslationResponse = {
        success: true,
        page_hash: 'hash-retry',
        engine_used: 'cloud',
        execution_time_ms: 300,
        from_cache: false,
        blocks: [],
      };

      const fetchSpy = vi
        .fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 429,
          headers: new Headers({ 'Retry-After': '0' }),
          json: vi.fn().mockResolvedValue({
            error: { code: 'RATE_LIMITED', message: 'Too many requests' },
          }),
        } as unknown as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: vi.fn().mockResolvedValue(mockSuccess),
        } as unknown as Response);

      globalThis.fetch = fetchSpy;

      const result = await gateway.requestTranslation({
        image: 'base64data',
        image_hash: 'hash-retry',
      });
      expect(result.page_hash).toBe('hash-retry');
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });

    it('exhausts retries and throws structured error when transient failures persist', async () => {
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: vi.fn().mockResolvedValue({
          error: { code: 'SERVICE_UNAVAILABLE', message: 'Backend restarting' },
        }),
      } as unknown as Response);
      globalThis.fetch = fetchSpy;

      await expect(
        gateway.requestTranslation({ image: 'base64data', image_hash: 'hash-503' })
      ).rejects.toThrow(/Backend restarting/);

      // Initial attempt + 2 retries = 3 total attempts
      expect(fetchSpy).toHaveBeenCalledTimes(3);
    });
  });

  describe('postTelemetryLogs', () => {
    it('returns true immediately for empty batch without fetching', async () => {
      const fetchSpy = vi.fn();
      globalThis.fetch = fetchSpy;

      const result = await gateway.postTelemetryLogs({ logs: [] });
      expect(result).toBe(true);
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('transmits telemetry batch with appropriate headers and body', async () => {
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ success: true, count: 1 }),
      } as unknown as Response);
      globalThis.fetch = fetchSpy;

      const batch = {
        logs: [
          {
            timestamp_ms: 1730000000000,
            level: 'INFO' as const,
            module: 'Prefetch',
            message: 'Window advanced',
          },
        ],
      };

      const result = await gateway.postTelemetryLogs(batch);
      expect(result).toBe(true);
      expect(fetchSpy).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/api/v1/telemetry/logs',
        expect.objectContaining({
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-InkShift-Client': 'extension',
          },
          body: JSON.stringify(batch),
        })
      );
    });

    it('returns false without throwing when server responds with error status', async () => {
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      } as unknown as Response);
      globalThis.fetch = fetchSpy;

      const result = await gateway.postTelemetryLogs({
        logs: [
          {
            timestamp_ms: 1730000000000,
            level: 'ERROR' as const,
            module: 'CS',
            message: 'Failed to render',
          },
        ],
      });
      expect(result).toBe(false);
    });

    it('returns false without throwing when network connection is refused', async () => {
      const fetchSpy = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
      globalThis.fetch = fetchSpy;

      const result = await gateway.postTelemetryLogs({
        logs: [
          {
            timestamp_ms: 1730000000000,
            level: 'INFO' as const,
            module: 'SW',
            message: 'Background worker activated',
          },
        ],
      });
      expect(result).toBe(false);
    });
  });
});
