// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { hitomiAdapter, HitomiAdapter } from '../../src/extension/adapters/hitomi_adapter';
import { siteAdapterRegistry } from '../../src/extension/adapters/registry';

describe('HitomiAdapter & Protocol Integration', () => {
  let adapter: HitomiAdapter;

  beforeEach(() => {
    document.body.innerHTML = '';
    document.body.className = '';
    vi.restoreAllMocks();
    adapter = new HitomiAdapter();
  });

  describe('Domain & URL Matching', () => {
    it('matches hitomi.la reader URLs', () => {
      expect(adapter.matches(new URL('https://hitomi.la/reader/1000001.html#1-'))).toBe(true);
      expect(adapter.matches('https://hitomi.la/reader/1000001.html')).toBe(true);
    });

    it('rejects non-hitomi URLs', () => {
      expect(adapter.matches(new URL('https://mangadex.org/chapter/123/1'))).toBe(false);
      expect(adapter.matches('https://google.com')).toBe(false);
    });
  });

  describe('Chapter ID & Page Number Extraction', () => {
    it('extracts numerical gallery ID from /reader/{id}.html', () => {
      const url = new URL('https://hitomi.la/reader/1000001.html#1-');
      expect(adapter.extractChapterId(url)).toBe('1000001');
    });

    it('returns null when URL does not contain valid reader pattern', () => {
      const url = new URL('https://hitomi.la/index-all.html');
      expect(adapter.extractChapterId(url)).toBeNull();
    });

    it('extracts page number from URL hash (#1-, #12-)', () => {
      expect(adapter.extractPageNumber(new URL('https://hitomi.la/reader/1000001.html#1-'))).toBe(1);
      expect(adapter.extractPageNumber(new URL('https://hitomi.la/reader/1000001.html#45-'))).toBe(45);
      expect(adapter.extractPageNumber(new URL('https://hitomi.la/reader/1000001.html'))).toBeNull();
    });
  });

  describe('Reader Layout Detection', () => {
    it('detects single page mode from spread1 body class', () => {
      document.body.className = 'spread1 fitVertical';
      expect(adapter.detectReaderLayout(document)).toBe('single');
    });

    it('detects double page mode from spread2 body class', () => {
      document.body.className = 'spread2';
      expect(adapter.detectReaderLayout(document)).toBe('double');
    });

    it('detects strip mode from scroll/webtoon body class', () => {
      document.body.className = 'scroll';
      expect(adapter.detectReaderLayout(document)).toBe('strip');
    });

    it('defaults to single mode if no known class present', () => {
      document.body.className = '';
      expect(adapter.detectReaderLayout(document)).toBe('single');
    });
  });

  describe('Image URL Normalization', () => {
    it('normalizes Hitomi .webp URLs to Anycast .avif on corresponding a subdomain', () => {
      const webpUrl = 'https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp';
      expect(adapter.normalizeImageUrl(webpUrl)).toBe('https://a2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif');

      const w1Url = 'https://w1.gold-usergeneratedcontent.net/1700000002/1054/000001e4.webp';
      expect(adapter.normalizeImageUrl(w1Url)).toBe('https://a1.gold-usergeneratedcontent.net/1700000002/1054/000001e4.avif');
    });

    it('leaves non-Hitomi URLs unchanged', () => {
      const normal = 'https://uploads.mangadex.org/data/hash/page.jpg';
      expect(adapter.normalizeImageUrl(normal)).toBe(normal);
    });
  });

  describe('CDN Fallback Resolution', () => {
    it('fails over from a1 .avif to a2 .avif on Anycast CDN upon 404 or network stall (status 0)', () => {
      const failedA1 = 'https://a1.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif';
      expect(adapter.resolveFallbackUrl(failedA1, 404)).toBe('https://a2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif');
      expect(adapter.resolveFallbackUrl(failedA1, 0)).toBe('https://a2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif');
    });

    it('converts failed .avif URLs to .webp on w subdomain upon 404/5xx or timeout stall (status 0)', () => {
      const failedAvif = 'https://a2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.avif';
      const fallback404 = adapter.resolveFallbackUrl(failedAvif, 404);
      expect(fallback404).toBe('https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp');

      const fallbackStall = adapter.resolveFallbackUrl(failedAvif, 0);
      expect(fallbackStall).toBe('https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp');
    });

    it('alternates between w1 and w2 subdomains on 404', () => {
      const failedW1 = 'https://w1.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp';
      expect(adapter.resolveFallbackUrl(failedW1, 404)).toBe('https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp');

      const failedW2 = 'https://w2.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp';
      expect(adapter.resolveFallbackUrl(failedW2, 404)).toBe('https://w1.gold-usergeneratedcontent.net/1700000001/495/0000000000000ef1.webp');
    });

    it('returns null for non-Hitomi URLs', () => {
      const externalUrl = 'https://cdn.other.com/image.avif';
      expect(adapter.resolveFallbackUrl(externalUrl, 404)).toBeNull();
    });
  });

  describe('Manifest Extraction', () => {
    it('extracts complete manifest via metadata endpoint with mathematical hash folder', async () => {
      const mockGalleryInfo = `var galleryinfo = {"id": 1000001, "title": "Demo Artist", "files": [{"hash": "0000000000000000000000000000000000000000000000000000000000000ef1", "name": "001.jpg"}, {"hash": "00000000000000000000000000000000000000000000000000000000000001e4", "name": "002.jpg"}]};`;

      const dummyImg = document.createElement('img');
      dummyImg.src = 'https://a2.gold-usergeneratedcontent.net/1700000001/495/dummy.avif';
      document.body.appendChild(dummyImg);

      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        text: async () => mockGalleryInfo,
      } as Response);

      const url = new URL('https://hitomi.la/reader/1000001.html#1-');
      const manifest = await adapter.extractManifest(document, url);

      expect(manifest).not.toBeNull();
      expect(manifest?.chapter_id).toBe('1000001');
      expect(manifest?.series_title).toBe('Demo Artist');
      expect(manifest?.pages.length).toBe(2);
      // Hash ...ef1 -> folder 495
      expect(manifest?.pages[0].image_url).toBe('https://a1.gold-usergeneratedcontent.net/1700000001/495/0000000000000000000000000000000000000000000000000000000000000ef1.avif');
      // Hash ...1e4 -> folder 1054
      expect(manifest?.pages[1].image_url).toBe('https://a1.gold-usergeneratedcontent.net/1700000002/1054/00000000000000000000000000000000000000000000000000000000000001e4.avif'.replace('1700000002', '1700000001'));
    });

    it('falls back to DOM elements when metadata endpoint fails', async () => {
      vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('Network error'));

      const comicDiv = document.createElement('div');
      comicDiv.id = 'comicImages';
      const mainImg = document.createElement('img');
      mainImg.src = 'https://w2.gold-usergeneratedcontent.net/img1.webp';
      comicDiv.appendChild(mainImg);

      const preloadDiv = document.createElement('div');
      preloadDiv.id = 'preload';
      const preloadImg1 = document.createElement('img');
      preloadImg1.src = 'https://w1.gold-usergeneratedcontent.net/img2.webp';
      const preloadImg2 = document.createElement('img');
      preloadImg2.src = 'https://w1.gold-usergeneratedcontent.net/img3.webp';
      preloadDiv.appendChild(preloadImg1);
      preloadDiv.appendChild(preloadImg2);

      document.body.appendChild(comicDiv);
      document.body.appendChild(preloadDiv);
      document.title = 'Demo Artist | Hitomi.la';

      const url = new URL('https://hitomi.la/reader/1000001.html#1-');
      const manifest = await adapter.extractManifest(document, url);

      expect(manifest).not.toBeNull();
      expect(manifest?.chapter_id).toBe('1000001');
      expect(manifest?.source_domain).toBe('hitomi.la');
      expect(manifest?.pages.length).toBe(3);
      expect(manifest?.pages[0].image_url).toBe('https://a2.gold-usergeneratedcontent.net/img1.avif');
      expect(manifest?.pages[1].image_url).toBe('https://a1.gold-usergeneratedcontent.net/img2.avif');
      expect(manifest?.pages[2].image_url).toBe('https://a1.gold-usergeneratedcontent.net/img3.avif');
    });

    it('resolves rootPrefix from gg.js fetch when DOM has no images', async () => {
      const mockGalleryInfo = `var galleryinfo = {"id": 1000001, "title": "Demo Artist", "files": [{"hash": "0000000000000000000000000000000000000000000000000000000000000ef1", "name": "001.jpg"}]};`;
      const mockGgJs = `var b = '1899999901/'; function gg() {}`;

      vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
        const urlStr = String(input);
        if (urlStr.includes('galleries/1000001.js')) {
          return Promise.resolve({
            ok: true,
            text: async () => mockGalleryInfo,
          } as Response);
        }
        if (urlStr.includes('gg.js')) {
          return Promise.resolve({
            ok: true,
            text: async () => mockGgJs,
          } as Response);
        }
        return Promise.reject(new Error('Unknown fetch: ' + urlStr));
      });

      const url = new URL('https://hitomi.la/reader/1000001.html#1-');
      const manifest = await adapter.extractManifest(document, url);

      expect(manifest).not.toBeNull();
      expect(manifest?.pages.length).toBe(1);
      // Valid prefix from gg.js without DOM images!
      expect(manifest?.pages[0].image_url).toBe(
        'https://a1.gold-usergeneratedcontent.net/1899999901/495/0000000000000000000000000000000000000000000000000000000000000ef1.avif'
      );
    });

    it('returns null and defers when rootPrefix cannot be resolved and DOM has no images', async () => {
      const mockGalleryInfo = `var galleryinfo = {"id": 1000001, "title": "Demo Artist", "files": [{"hash": "0000000000000000000000000000000000000000000000000000000000000ef1", "name": "001.jpg"}]};`;

      vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
        const urlStr = String(input);
        if (urlStr.includes('galleries/1000001.js')) {
          return Promise.resolve({
            ok: true,
            text: async () => mockGalleryInfo,
          } as Response);
        }
        if (urlStr.includes('gg.js')) {
          return Promise.resolve({
            ok: false,
            status: 500,
          } as Response);
        }
        return Promise.reject(new Error('Unknown fetch: ' + urlStr));
      });

      const url = new URL('https://hitomi.la/reader/1000001.html#1-');
      const manifest = await adapter.extractManifest(document, url);

      // Must NOT produce broken truncated URLs like a1.../hash.avif
      expect(manifest).toBeNull();
    });

    it('resolves a1 vs a2 shard subdomains from gg.js switch(g) mapping', async () => {
      const mockGalleryInfo = `var galleryinfo = {"id": 1000001, "title": "Demo Artist", "files": [{"hash": "0000000000000000000000000000000000000000000000000000000000000f92", "name": "001.jpg"}, {"hash": "00000000000000000000000000000000000000000000000000000000000001e4", "name": "002.jpg"}]};`;
      const mockGgJs = `'use strict';\ngg = { m: function(g) {\nvar o = 0;\nswitch (g) {\ncase 761:\no = 1; break;\n}\nreturn o;\n},\nb: '1899999901/'\n};`;

      vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
        const urlStr = String(input);
        if (urlStr.includes('galleries/1000001.js')) {
          return Promise.resolve({
            ok: true,
            text: async () => mockGalleryInfo,
          } as Response);
        }
        if (urlStr.includes('gg.js')) {
          return Promise.resolve({
            ok: true,
            text: async () => mockGgJs,
          } as Response);
        }
        return Promise.reject(new Error('Unknown fetch: ' + urlStr));
      });

      const url = new URL('https://hitomi.la/reader/1000001.html#1-');
      const manifest = await adapter.extractManifest(document, url);

      expect(manifest).not.toBeNull();
      expect(manifest?.pages.length).toBe(2);
      // ...f92 -> folder 761 (case 761 => o = 1 => a2)
      expect(manifest?.pages[0].image_url).toBe(
        'https://a2.gold-usergeneratedcontent.net/1899999901/761/0000000000000000000000000000000000000000000000000000000000000f92.avif'
      );
      // ...1e4 -> folder 1054 (default o = 0 => a1)
      expect(manifest?.pages[1].image_url).toBe(
        'https://a1.gold-usergeneratedcontent.net/1899999901/1054/00000000000000000000000000000000000000000000000000000000000001e4.avif'
      );
    });
  });

  describe('Registry Integration', () => {
    it('is registered in default siteAdapterRegistry', () => {
      const registered = siteAdapterRegistry.getAdapter('https://hitomi.la/reader/1000001.html#1-');
      expect(registered).toBeDefined();
      expect(registered?.id).toBe('hitomi');
      expect(registered?.name).toBe('Hitomi');
    });
  });
});

