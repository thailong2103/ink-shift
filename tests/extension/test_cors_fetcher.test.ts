import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  computeSha256Hex,
  ensureHitomiRefererRule,
  uint8ArrayToBase64,
  fetchAndProcessImage,
} from '../../src/extension/background/cors_fetcher';

describe('CORS Fetcher & Binary Processing', () => {
  describe('computeSha256Hex', () => {
    it('computes correct SHA-256 digest for empty buffer', async () => {
      const buffer = new Uint8Array(0).buffer;
      const hash = await computeSha256Hex(buffer);
      expect(hash).toBe('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
    });

    it('computes correct SHA-256 digest for known string', async () => {
      const encoder = new TextEncoder();
      const buffer = encoder.encode('hello world').buffer;
      const hash = await computeSha256Hex(buffer);
      expect(hash).toBe('b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9');
    });
  });

  describe('uint8ArrayToBase64', () => {
    it('correctly converts small byte arrays to Base64', () => {
      const encoder = new TextEncoder();
      const bytes = encoder.encode('InkShift');
      const b64 = uint8ArrayToBase64(bytes);
      expect(b64).toBe('SW5rU2hpZnQ=');
    });

    it('handles large binary data (>64KB) without call stack overflow', () => {
      // 100 KB payload
      const largeBytes = new Uint8Array(100 * 1024);
      for (let i = 0; i < largeBytes.length; i++) {
        largeBytes[i] = i % 256;
      }
      const b64 = uint8ArrayToBase64(largeBytes);
      expect(typeof b64).toBe('string');
      expect(b64.length).toBeGreaterThan(100 * 1024);
    });
  });

  describe('fetchAndProcessImage', () => {
    const originalFetch = globalThis.fetch;

    beforeEach(() => {
      vi.restoreAllMocks();
    });

    afterEach(() => {
      globalThis.fetch = originalFetch;
    });

    it('fetches image, computes hash and converts to Base64 successfully', async () => {
      const mockBytes = new TextEncoder().encode('fake-manga-page-bytes');
      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'image/jpeg' }),
        arrayBuffer: vi.fn().mockResolvedValue(mockBytes.buffer),
      };
      globalThis.fetch = vi.fn().mockResolvedValue(mockResponse as unknown as Response);

      const result = await fetchAndProcessImage('https://cdn.example.com/ch1/01.jpg');
      expect(result.mimeType).toBe('image/jpeg');
      expect(result.sha256Hex).toBeDefined();
      expect(result.sha256Hex.length).toBe(64);
      expect(result.base64).toBe(uint8ArrayToBase64(mockBytes));
    });

    it('throws error when HTTP status is not ok', async () => {
      const mockResponse = {
        ok: false,
        status: 404,
        statusText: 'Not Found',
      };
      globalThis.fetch = vi.fn().mockResolvedValue(mockResponse as unknown as Response);

      await expect(fetchAndProcessImage('https://cdn.example.com/missing.jpg')).rejects.toThrow(
        /Failed to fetch image: 404/
      );
    });

    it('throws error when image exceeds 20MB size limit', async () => {
      const hugeBuffer = new ArrayBuffer(21 * 1024 * 1024); // 21MB
      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'image/png' }),
        arrayBuffer: vi.fn().mockResolvedValue(hugeBuffer),
      };
      globalThis.fetch = vi.fn().mockResolvedValue(mockResponse as unknown as Response);

      await expect(fetchAndProcessImage('https://cdn.example.com/huge.png')).rejects.toThrow(
        /Image size exceeds maximum limit of 20MB/
      );
    });

    it('retries on canonical uploads.mangadex.org origin when MD@H node returns 404', async () => {
      const mockBytes = new TextEncoder().encode('fallback-bytes');
      const nodeFailResponse = {
        ok: false,
        status: 404,
        statusText: 'Not Found',
      };
      const originSuccessResponse = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'image/jpeg' }),
        arrayBuffer: vi.fn().mockResolvedValue(mockBytes.buffer),
      };

      const mockFetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('mangadex.network')) {
          return Promise.resolve(nodeFailResponse as unknown as Response);
        }
        if (url.includes('uploads.mangadex.org')) {
          return Promise.resolve(originSuccessResponse as unknown as Response);
        }
        return Promise.reject(new Error(`Unhandled URL: ${url}`));
      });
      globalThis.fetch = mockFetch;

      const result = await fetchAndProcessImage(
        'https://cmdxd98sb0x3yprd.mangadex.network/data/hash123/1.jpg'
      );
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(mockFetch).toHaveBeenLastCalledWith(
        'https://uploads.mangadex.org/data/hash123/1.jpg',
        expect.any(Object)
      );
      expect(result.mimeType).toBe('image/jpeg');
    });

    it('normalizes Hitomi .webp URLs to Anycast .avif on a subdomain before calling fetch', async () => {
      const mockBytes = new TextEncoder().encode('avif-image-bytes');
      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'image/avif' }),
        arrayBuffer: vi.fn().mockResolvedValue(mockBytes.buffer),
      };
      const mockFetch = vi.fn().mockResolvedValue(mockResponse as unknown as Response);
      globalThis.fetch = mockFetch;

      const hitomiWebp = 'https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp';
      const result = await fetchAndProcessImage(hitomiWebp);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://a2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif',
        expect.any(Object)
      );
      expect(result.mimeType).toBe('image/avif');
    });

    it('retries on w2 WebP origin when a2 AVIF fetch stalls / drops connection (status 0)', async () => {
      const mockBytes = new TextEncoder().encode('webp-fallback-bytes');
      const mockFetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('.avif')) {
          return Promise.reject(new Error('Network connection stall'));
        }
        if (url.includes('.webp')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'image/webp' }),
            arrayBuffer: vi.fn().mockResolvedValue(mockBytes.buffer),
          } as unknown as Response);
        }
        return Promise.reject(new Error('Unhandled URL: ' + url));
      });
      globalThis.fetch = mockFetch;

      const result = await fetchAndProcessImage(
        'https://a2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif'
      );
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(mockFetch).toHaveBeenLastCalledWith(
        'https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp',
        expect.any(Object)
      );
      expect(result.mimeType).toBe('image/webp');
    });

    it('retries on w2 subdomain when Hitomi w1 returns 404', async () => {
      const mockBytes = new TextEncoder().encode('w2-bytes');
      const fail404Response = {
        ok: false,
        status: 404,
        statusText: 'Not Found',
      };
      const w2SuccessResponse = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'image/webp' }),
        arrayBuffer: vi.fn().mockResolvedValue(mockBytes.buffer),
      };

      const mockFetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('//a1.') || url.includes('//a2.')) {
          return Promise.resolve(fail404Response as unknown as Response);
        }
        if (url.includes('//w1.')) {
          return Promise.resolve(fail404Response as unknown as Response);
        }
        if (url.includes('//w2.')) {
          return Promise.resolve(w2SuccessResponse as unknown as Response);
        }
        return Promise.reject(new Error('Unhandled URL: ' + url));
      });
      globalThis.fetch = mockFetch;

      const result = await fetchAndProcessImage(
        'https://w1.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp'
      );
      // Normalized a1 (404) -> fallback a2 (404) -> fallback w2 (200 OK)
      expect(mockFetch).toHaveBeenCalledTimes(3);
      expect(mockFetch).toHaveBeenLastCalledWith(
        'https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp',
        expect.any(Object)
      );
      expect(result.mimeType).toBe('image/webp');
    });

    it('terminates retry loop and throws error when cyclic fallback is detected without infinite loop', async () => {
      const fail404Response = {
        ok: false,
        status: 404,
        statusText: 'Not Found',
      };

      const mockFetch = vi.fn().mockResolvedValue(fail404Response as unknown as Response);
      globalThis.fetch = mockFetch;

      // w1 normalizes to a1, a1 -> a2 -> w2 -> w1 -> cycle detected!
      await expect(
        fetchAndProcessImage('https://w1.gold-usergeneratedcontent.net/1700000001/495/missing.webp')
      ).rejects.toThrow(/Failed to fetch image: 404 Not Found/);

      // Should have attempted: a1 (1), a2 (2), w2 (3), w1 (4 - detected cycle/max reached) -> terminates!
      expect(mockFetch.mock.calls.length).toBeLessThanOrEqual(4);
    });

    it('terminates retry loop within MAX_ADAPTER_FALLBACKS bound even under continuous 500 error', async () => {
      const fail500Response = {
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      };

      const mockFetch = vi.fn().mockResolvedValue(fail500Response as unknown as Response);
      globalThis.fetch = mockFetch;

      await expect(
        fetchAndProcessImage('https://w1.gold-usergeneratedcontent.net/1700000001/495/error.webp')
      ).rejects.toThrow(/Failed to fetch image: 500 Internal Server Error/);

      // Total fetches must be bounded (<= 4: 1 initial + max 3 fallbacks)
      expect(mockFetch.mock.calls.length).toBeLessThanOrEqual(4);
    });

    it('decodes inline Data URLs directly without invoking fetch', async () => {
      const fetchSpy = vi.fn();
      globalThis.fetch = fetchSpy;

      const base64Data = btoa('test-image');
      const dataUrl = `data:image/jpeg;base64,${base64Data}`;

      const result = await fetchAndProcessImage(dataUrl);

      expect(fetchSpy).not.toHaveBeenCalled();
      expect(result.mimeType).toBe('image/jpeg');
      expect(result.base64).toBe(base64Data);
      expect(result.sizeBytes).toBe('test-image'.length);
      expect(result.sha256Hex).toBeTruthy();
    });

    it('allows unnormalized w2 .webp to fall back from normalized a2 .avif to w2 .webp without false loop detection', async () => {
      const mockBytes = new TextEncoder().encode('w2-origin-bytes');
      const mockFetch = vi.fn().mockImplementation((url: string) => {
        if (url.includes('//a2.') && url.endsWith('.avif')) {
          return Promise.resolve({
            ok: false,
            status: 404,
            statusText: 'Not Found',
          } as unknown as Response);
        }
        if (url.includes('//w2.') && url.endsWith('.webp')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'image/webp' }),
            arrayBuffer: vi.fn().mockResolvedValue(mockBytes.buffer),
          } as unknown as Response);
        }
        return Promise.reject(new Error(`Unexpected URL fetched: ${url}`));
      });
      globalThis.fetch = mockFetch;

      const result = await fetchAndProcessImage(
        'https://w2.gold-usergeneratedcontent.net/1700000001/761/0000000000000f92.webp'
      );

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(mockFetch).toHaveBeenNthCalledWith(
        1,
        'https://a2.gold-usergeneratedcontent.net/1700000001/761/0000000000000f92.avif',
        expect.any(Object)
      );
      expect(mockFetch).toHaveBeenNthCalledWith(
        2,
        'https://w2.gold-usergeneratedcontent.net/1700000001/761/0000000000000f92.webp',
        expect.any(Object)
      );
      expect(result.mimeType).toBe('image/webp');
    });
  });

  describe('ensureHitomiRefererRule', () => {
    const originalChrome = (globalThis as unknown as { chrome?: unknown }).chrome;

    afterEach(() => {
      if (originalChrome === undefined) {
        delete (globalThis as unknown as { chrome?: unknown }).chrome;
      } else {
        (globalThis as unknown as { chrome?: unknown }).chrome = originalChrome;
      }
    });

    it('registers Hitomi Referer declarativeNetRequest dynamic rule once', async () => {
      const updateDynamicRules = vi.fn().mockResolvedValue(undefined);
      (globalThis as unknown as { chrome: unknown }).chrome = {
        declarativeNetRequest: {
          RuleActionType: { MODIFY_HEADERS: 'modifyHeaders' },
          HeaderOperation: { SET: 'set' },
          ResourceType: {
            XMLHTTPREQUEST: 'xmlhttprequest',
            IMAGE: 'image',
            OTHER: 'other',
            SCRIPT: 'script',
          },
          updateDynamicRules,
        },
      };

      await ensureHitomiRefererRule();
      await ensureHitomiRefererRule();

      expect(updateDynamicRules).toHaveBeenCalledTimes(1);
      expect(updateDynamicRules).toHaveBeenCalledWith({
        removeRuleIds: [9101],
        addRules: [
          expect.objectContaining({
            id: 9101,
            action: {
              type: 'modifyHeaders',
              requestHeaders: [
                {
                  header: 'Referer',
                  operation: 'set',
                  value: 'https://hitomi.la/',
                },
              ],
            },
            condition: {
              urlFilter: '||gold-usergeneratedcontent.net/',
              resourceTypes: ['xmlhttprequest', 'image', 'other', 'script'],
            },
          }),
        ],
      });
    });
  });
});

