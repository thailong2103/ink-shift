import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  computeSha256Hex,
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
  });
});

