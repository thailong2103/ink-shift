// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest';
import {
  detectReaderContext,
  extractMangaMetadata,
  type ReaderDetectionResult,
} from '../../src/extension/content/reader_detector';

describe('Reader Detector Engine (PAHE)', () => {
  let doc: Document;

  beforeEach(() => {
    doc = document.implementation.createHTMLDocument('Test Document');
  });

  describe('extractMangaMetadata', () => {
    it('extracts seriesSlug and integer chapterNumber from URL', () => {
      const url = new URL('https://mangadex.org/title/one-piece/chapter-1050');
      const meta = extractMangaMetadata(url, doc);
      expect(meta.seriesSlug).toBe('one-piece');
      expect(meta.chapterNumber).toBe(1050);
      expect(meta.sourceDomain).toBe('mangadex.org');
    });

    it('extracts decimal chapter numbers', () => {
      const url = new URL('https://site.com/read/chainsaw-man/chap-12.5');
      const meta = extractMangaMetadata(url, doc);
      expect(meta.seriesSlug).toBe('chainsaw-man');
      expect(meta.chapterNumber).toBe(12.5);
    });

    it('falls back to document title if URL contains UUID or hash only', () => {
      doc.title = 'Jujutsu Kaisen - Chapter 236 Online';
      const url = new URL('https://mangadex.org/chapter/5a7d-8e9f-uuid');
      const meta = extractMangaMetadata(url, doc);
      expect(meta.chapterNumber).toBe(236);
    });
  });

  describe('detectReaderContext: Negative URL Patterns', () => {
    it('rejects catalog and genre listing pages', () => {
      const url = new URL('https://nettruyen.org/the-loai/action');
      const result = detectReaderContext(url, doc);
      expect(result.isReaderPage).toBe(false);
      expect(result.confidence).toBeLessThan(0.1);
    });

    it('rejects homepage and root domain', () => {
      const url = new URL('https://mangadex.org/');
      const result = detectReaderContext(url, doc);
      expect(result.isReaderPage).toBe(false);
      expect(result.confidence).toBe(0);
    });

    it('rejects title/manga details pages', () => {
      const url = new URL('https://mangadex.org/title/90a3b8cf-34a4-4497-9b80-56502cbac2ab/onii-chan');
      const result = detectReaderContext(url, doc);
      expect(result.isReaderPage).toBe(false);
      expect(result.confidence).toBeLessThan(0.1);
    });

    it('rejects search pages', () => {
      const url = new URL('https://manganato.com/search/story/naruto');
      const result = detectReaderContext(url, doc);
      expect(result.isReaderPage).toBe(false);
    });
  });

  describe('detectReaderContext: Tier 1 Fast-Path Known Profiles', () => {
    it('detects WP-Manga Madara reader container', () => {
      const container = doc.createElement('div');
      container.className = 'reading-content';
      const img = doc.createElement('img');
      img.src = 'https://site.com/001.jpg';
      container.appendChild(img);
      doc.body.appendChild(container);

      const url = new URL('https://asuracomic.net/series/solo-leveling/chapter-10');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(true);
      expect(result.confidence).toBe(1.0);
      expect(result.layoutType).toBe('profile-matched');
      expect(result.readerContainer).toBe(container);
      expect(result.chapterMeta?.chapterNumber).toBe(10);
    });

    it('detects NetTruyen reader container', () => {
      const container = doc.createElement('div');
      container.className = 'reading-detail';
      const page = doc.createElement('div');
      page.className = 'page-chapter';
      const img = doc.createElement('img');
      img.src = 'https://img.nettruyen.org/c1/p1.jpg';
      page.appendChild(img);
      container.appendChild(page);
      doc.body.appendChild(container);

      const url = new URL('https://nettruyen.org/truyen-tranh/one-piece/chap-100');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(true);
      expect(result.confidence).toBe(1.0);
      expect(result.layoutType).toBe('profile-matched');
      expect(result.readerContainer).toBe(container);
    });

    it('detects MangaDex reader container with domain check', () => {
      const container = doc.createElement('div');
      container.id = 'reader';
      const img = doc.createElement('img');
      img.className = 'md-image';
      img.src = 'https://uploads.mangadex.org/data/p1.jpg';
      container.appendChild(img);
      doc.body.appendChild(container);

      const url = new URL('https://mangadex.org/chapter/uuid-1234');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(true);
      expect(result.confidence).toBe(1.0);
      expect(result.readerContainer).toBe(container);
    });

    it('does not select empty container even if URL matches profile, falling back to body', () => {
      const emptyHeader = doc.createElement('div');
      emptyHeader.className = 'reader--container';
      doc.body.appendChild(emptyHeader);

      const url = new URL('https://mangadex.org/chapter/90a3b8cf-34a4-4497-9b80-56502cbac2ab/14');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(true);
      expect(result.confidence).toBe(1.0);
      expect(result.readerContainer).toBe(doc.body);
    });
  });

  describe('detectReaderContext: Tier 2 Homogeneous Dimension Clustering', () => {
    it('detects long-strip reader on unknown CMS with uniform image widths', () => {
      const wrapper = doc.createElement('div');
      wrapper.id = 'arbitrary-comic-viewer';

      // Create 4 images with uniform 800px width
      for (let i = 0; i < 4; i++) {
        const img = doc.createElement('img');
        img.src = `https://unknownsite.com/page_${i}.jpg`;
        Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
        Object.defineProperty(img, 'clientHeight', { value: 1200, configurable: true });
        wrapper.appendChild(img);
      }
      doc.body.appendChild(wrapper);

      const url = new URL('https://unknownsite.com/series/comic/chapter-5');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(true);
      expect(result.confidence).toBe(0.95);
      expect(result.layoutType).toBe('long-strip');
      expect(result.readerContainer).toBe(wrapper);
    });

    it('rejects heterogeneous image galleries (e-commerce or photo blog)', () => {
      const gallery = doc.createElement('div');
      gallery.className = 'product-gallery';

      const widths = [250, 750, 400, 150];
      for (const w of widths) {
        const img = doc.createElement('img');
        img.src = `https://shop.com/prod_${w}.jpg`;
        Object.defineProperty(img, 'clientWidth', { value: w, configurable: true });
        Object.defineProperty(img, 'clientHeight', { value: 300, configurable: true });
        gallery.appendChild(img);
      }
      doc.body.appendChild(gallery);

      const url = new URL('https://shop.com/products/shoes');
      const result = detectReaderContext(url, doc);

      // Heterogeneous widths have CV > 0.35, should not match long-strip
      expect(result.layoutType).not.toBe('long-strip');
    });

    it('rejects uniform image grids when URL and title have no chapter context', () => {
      const cardGrid = doc.createElement('div');
      cardGrid.className = 'latest-updates-grid';

      for (let i = 0; i < 4; i++) {
        const img = doc.createElement('img');
        img.src = `https://mangadex.org/covers/manga_${i}.jpg`;
        Object.defineProperty(img, 'clientWidth', { value: 256, configurable: true });
        Object.defineProperty(img, 'clientHeight', { value: 358, configurable: true });
        cardGrid.appendChild(img);
      }
      doc.body.appendChild(cardGrid);

      const url = new URL('https://mangadex.org/');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(false);
      expect(result.layoutType).toBe('none');
    });
  });

  describe('detectReaderContext: Tier 3 Viewport Prominence & Centrality', () => {
    it('detects single-page reader with centered large image and chapter URL', () => {
      const img = doc.createElement('img');
      img.src = 'https://batoto.com/p1.jpg';
      Object.defineProperty(img, 'clientWidth', { value: 800, configurable: true });
      Object.defineProperty(img, 'clientHeight', { value: 1100, configurable: true });
      img.getBoundingClientRect = () => ({
        top: 50,
        left: 240,
        width: 800,
        height: 1100,
        right: 1040,
        bottom: 1150,
        x: 240,
        y: 50,
        toJSON: () => {},
      });
      doc.body.appendChild(img);

      // Window dimensions: 1280x800 -> center is 640. Image center: 240 + 400 = 640 (offset 0!)
      Object.defineProperty(window, 'innerWidth', { value: 1280, configurable: true });
      Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });

      const url = new URL('https://batoto.com/read/naruto/chapter-50?page=1');
      const result = detectReaderContext(url, doc);

      expect(result.isReaderPage).toBe(true);
      expect(result.confidence).toBeGreaterThanOrEqual(0.85);
      expect(result.layoutType).toBe('single-page');
    });
  });
});
