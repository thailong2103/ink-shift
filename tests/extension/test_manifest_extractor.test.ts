// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  extractChapterManifest,
  extractImageSourceUrl,
  sanitizeSeriesTitle,
} from '../../src/extension/content/page_manifest_extractor';
import type { ChapterContextReport } from '../../src/extension/shared/context_types';

describe('Page Manifest Extractor', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  describe('sanitizeSeriesTitle', () => {
    it('removes common SEO suffixes and cleaning brackets', () => {
      expect(
        sanitizeSeriesTitle('Solo Leveling - Chapter 100 - Read Manga Online Free')
      ).toBe('Solo Leveling');

      expect(
        sanitizeSeriesTitle('Frieren: Beyond Journey\'s End Manga Online')
      ).toBe('Frieren: Beyond Journey\'s End');

      expect(
        sanitizeSeriesTitle('[RAW] Tower of God - Chap 500 - NetTruyen')
      ).toBe('Tower of God');
    });
  });

  describe('extractImageSourceUrl', () => {
    it('respects dataset attribute cascade (data-url > data-src > data-original > src)', () => {
      const img = document.createElement('img');
      img.src = 'https://cdn/fallback.jpg';
      img.setAttribute('data-original', 'https://cdn/original.jpg');
      img.setAttribute('data-src', 'https://cdn/datasrc.jpg');
      img.setAttribute('data-url', 'https://cdn/dataurl.jpg');

      expect(extractImageSourceUrl(img)).toBe('https://cdn/dataurl.jpg');

      img.removeAttribute('data-url');
      expect(extractImageSourceUrl(img)).toBe('https://cdn/datasrc.jpg');

      img.removeAttribute('data-src');
      expect(extractImageSourceUrl(img)).toBe('https://cdn/original.jpg');

      img.removeAttribute('data-original');
      expect(extractImageSourceUrl(img)).toBe('https://cdn/fallback.jpg');
    });

    it('ignores SVG data URL placeholders', () => {
      const img = document.createElement('img');
      img.src = 'data:image/svg+xml;base64,...';
      img.setAttribute('data-src', 'https://cdn/real-manga.jpg');

      expect(extractImageSourceUrl(img)).toBe('https://cdn/real-manga.jpg');
    });
  });

  describe('extractChapterManifest', () => {
    it('delegates to Service Worker on MangaDex URLs', async () => {
      const mockReport: ChapterContextReport = {
        series_id: 'mangadex:uuid-s1',
        series_title: 'Oshi no Ko',
        source_domain: 'mangadex.org',
        chapter_id: 'ch-md-1',
        chapter_ordinal: 1.0,
        chapter_label: 'Ch. 1',
        chapter_url: 'https://mangadex.org/chapter/ch-md-1/1',
        total_pages: 2,
        pages: [
          { page_number: 1, image_url: 'https://cmdxd.network/data/h/1.jpg' },
          { page_number: 2, image_url: 'https://cmdxd.network/data/h/2.jpg' },
        ],
      };

      (globalThis as unknown as { chrome: unknown }).chrome = {
        runtime: {
          sendMessage: vi.fn().mockResolvedValue({
            success: true,
            data: mockReport,
          }),
        },
      };

      const url = new URL('https://mangadex.org/chapter/ch-md-1/1');
      const manifest = await extractChapterManifest(document, url);

      expect(manifest.series_id).toBe('mangadex:uuid-s1');
      expect(manifest.chapter_id).toBe('ch-md-1');
      expect(manifest.pages.length).toBe(2);
    });

    it('extracts vertical webtoon DOM images using waterfall scanning', async () => {
      const container = document.createElement('div');
      container.className = 'reading-content';

      for (let i = 1; i <= 3; i++) {
        const img = document.createElement('img');
        img.className = 'page-img';
        img.setAttribute('data-src', `https://cdn.webtoons.com/p${i}.jpg`);
        // Mimic manga dimensions
        Object.defineProperty(img, 'naturalWidth', { value: 800 });
        Object.defineProperty(img, 'naturalHeight', { value: 1200 });
        container.appendChild(img);
      }
      document.body.appendChild(container);
      document.title = 'Omniscient Reader - Chapter 50 - Webtoon Online';

      const url = new URL('https://asurascans.com/manga/omniscient-reader/chapter-50');
      const manifest = await extractChapterManifest(document, url);

      expect(manifest.series_title).toBe('Omniscient Reader');
      expect(manifest.chapter_ordinal).toBe(50);
      expect(manifest.pages.length).toBe(3);
      expect(manifest.pages[0].page_number).toBe(1);
      expect(manifest.pages[0].image_url).toBe('https://cdn.webtoons.com/p1.jpg');
      expect(manifest.pages[2].page_number).toBe(3);
    });
  });
});
