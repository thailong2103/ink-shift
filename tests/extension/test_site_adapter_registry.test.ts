// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SiteAdapterRegistry, siteAdapterRegistry } from '../../src/extension/adapters/registry';
import { mangaDexAdapter } from '../../src/extension/adapters/mangadex_adapter';
import type { SiteAdapter } from '../../src/extension/adapters/base';

describe('SiteAdapterRegistry & MangaDexAdapter', () => {
  let registry: SiteAdapterRegistry;

  beforeEach(() => {
    vi.restoreAllMocks();
    registry = new SiteAdapterRegistry();
    registry.register(mangaDexAdapter);
  });

  describe('Registry Adapter Resolution', () => {
    it('registers and resolves MangaDexAdapter for mangadex.org URLs', () => {
      const adapter = registry.getAdapter(new URL('https://mangadex.org/chapter/123e4567-e89b-12d3-a456-426614174000/1'));
      expect(adapter).toBeDefined();
      expect(adapter?.id).toBe('mangadex');
      expect(adapter?.name).toBe('MangaDex');
    });

    it('returns null for unregistered domains', () => {
      const adapter = registry.getAdapter(new URL('https://example.com/chapter/1'));
      expect(adapter).toBeNull();
    });

    it('handles string URLs safely', () => {
      const adapter = registry.getAdapter('https://mangadex.org/title/123');
      expect(adapter?.id).toBe('mangadex');
    });

    it('returns null on malformed URLs without throwing', () => {
      const adapter = registry.getAdapter('invalid-url-string');
      expect(adapter).toBeNull();
    });

    it('updates adapter instance when re-registered with same id', () => {
      const customAdapter: SiteAdapter = {
        id: 'mangadex',
        name: 'MangaDex Custom',
        domainPattern: /mangadex\.org$/i,
        matches: () => true,
      };
      registry.register(customAdapter);
      const adapter = registry.getAdapter('https://mangadex.org/test');
      expect(adapter?.name).toBe('MangaDex Custom');
    });
  });

  describe('MangaDex Chapter ID Extraction', () => {
    it('extracts chapter UUID from standard MangaDex chapter URLs', () => {
      const url = new URL('https://mangadex.org/chapter/a1b2c3d4-e5f6-7890-abcd-ef0123456789/1');
      const chapterId = registry.extractChapterId(url);
      expect(chapterId).toBe('a1b2c3d4-e5f6-7890-abcd-ef0123456789');
    });

    it('falls back to hostname:pathname for unknown sites without custom extractors', () => {
      const url = new URL('https://asurascans.com/manga/solo-leveling/chapter-100');
      const chapterId = registry.extractChapterId(url);
      expect(chapterId).toBe('asurascans.com:manga/solo-leveling/chapter-100');
    });
  });

  describe('CDN Fallback Resolution', () => {
    it('resolves MangaDex At-Home node 404/5xx to canonical uploads.mangadex.org', () => {
      const failedNodeUrl = 'https://cmdxd98sb0x3yprd.mangadex.network/data/1b582af9632833a9b0933346e9cb2bdf/1-x.jpg';
      const fallback404 = registry.resolveFallbackUrl(failedNodeUrl, 404);
      expect(fallback404).toBe('https://uploads.mangadex.org/data/1b582af9632833a9b0933346e9cb2bdf/1-x.jpg');

      const fallback500 = registry.resolveFallbackUrl(failedNodeUrl, 502);
      expect(fallback500).toBe('https://uploads.mangadex.org/data/1b582af9632833a9b0933346e9cb2bdf/1-x.jpg');
    });

    it('returns null for non-MangaDex URLs or successful status codes', () => {
      const normalUrl = 'https://cdn.webtoons.com/p1.jpg';
      expect(registry.resolveFallbackUrl(normalUrl, 404)).toBeNull();

      const mdUrl = 'https://cmdxd98sb0x3yprd.mangadex.network/data/h/1.jpg';
      expect(registry.resolveFallbackUrl(mdUrl, 200)).toBeNull();
    });
  });

  describe('Reader Layout Detection', () => {
    it('detects reader mode from MangaDex localStorage settings', () => {
      window.localStorage.setItem('reader-settings', JSON.stringify({ mode: 'long-strip' }));
      const layout = registry.detectReaderLayout(document, new URL('https://mangadex.org/chapter/123/1'));
      expect(layout).toBe('strip');
    });

    it('detects double page mode from MangaDex reader-mode key', () => {
      window.localStorage.removeItem('reader-settings');
      window.localStorage.setItem('reader-mode', 'double');
      const layout = registry.detectReaderLayout(document, new URL('https://mangadex.org/chapter/123/1'));
      expect(layout).toBe('double');
    });

    it('returns null when no localStorage setting exists', () => {
      window.localStorage.clear();
      const layout = registry.detectReaderLayout(document, new URL('https://mangadex.org/chapter/123/1'));
      expect(layout).toBeNull();
    });
  });

  describe('Default Singleton Registry', () => {
    it('siteAdapterRegistry comes pre-registered with MangaDexAdapter', () => {
      const adapter = siteAdapterRegistry.getAdapter('https://mangadex.org/chapter/xyz');
      expect(adapter).toBeDefined();
      expect(adapter?.id).toBe('mangadex');
    });
  });
});

