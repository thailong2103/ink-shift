// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  isMangaImage,
  isImageReady,
  waitForImageReady,
  scanForMangaImages,
} from '../../src/extension/content/dom_scanner';

describe('DOM Manga Image Scanner', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  describe('isMangaImage', () => {
    it('accepts images with dimensions >= 300px and standard manga aspect ratios', () => {
      const img = document.createElement('img');
      img.src = 'https://manga.cdn/page1.jpg';
      Object.defineProperty(img, 'clientWidth', { value: 800 });
      Object.defineProperty(img, 'clientHeight', { value: 1200 });
      Object.defineProperty(img, 'naturalWidth', { value: 800 });
      Object.defineProperty(img, 'naturalHeight', { value: 1200 });

      expect(isMangaImage(img)).toBe(true);
    });

    it('allows still-downloading images (!complete and 0x0) through for async decode waiting', () => {
      const loadingImg = document.createElement('img');
      loadingImg.src = 'https://manga.cdn/page2.jpg';
      Object.defineProperty(loadingImg, 'complete', { value: false });
      Object.defineProperty(loadingImg, 'clientWidth', { value: 0 });
      Object.defineProperty(loadingImg, 'clientHeight', { value: 0 });
      Object.defineProperty(loadingImg, 'naturalWidth', { value: 0 });
      Object.defineProperty(loadingImg, 'naturalHeight', { value: 0 });

      expect(isMangaImage(loadingImg)).toBe(true);
    });

    it('rejects small avatars, icons, and thumbnails (< 300px)', () => {
      const avatar = document.createElement('img');
      avatar.src = 'https://site.com/avatar.png';
      Object.defineProperty(avatar, 'clientWidth', { value: 48 });
      Object.defineProperty(avatar, 'clientHeight', { value: 48 });
      Object.defineProperty(avatar, 'naturalWidth', { value: 48 });
      Object.defineProperty(avatar, 'naturalHeight', { value: 48 });

      expect(isMangaImage(avatar)).toBe(false);
    });

    it('rejects advertising banners with extreme aspect ratios (e.g. 728x90)', () => {
      const ad = document.createElement('img');
      ad.src = 'https://ads.com/leaderboard.jpg';
      Object.defineProperty(ad, 'clientWidth', { value: 728 });
      Object.defineProperty(ad, 'clientHeight', { value: 90 });
      Object.defineProperty(ad, 'naturalWidth', { value: 728 });
      Object.defineProperty(ad, 'naturalHeight', { value: 90 });

      expect(isMangaImage(ad)).toBe(false);
    });

    it('rejects images with ad or avatar class/id/attributes', () => {
      const adImg = document.createElement('img');
      adImg.className = 'google-ad-banner sponsor';
      adImg.src = 'https://site.com/promo.jpg';
      Object.defineProperty(adImg, 'clientWidth', { value: 400 });
      Object.defineProperty(adImg, 'clientHeight', { value: 400 });

      expect(isMangaImage(adImg)).toBe(false);
    });

    it('rejects manga catalog covers and thumbnails from /covers/ URLs', () => {
      const coverImg = document.createElement('img');
      coverImg.className = 'manga-cover';
      coverImg.src = 'https://mangadex.org/covers/f9202aa3-2940/cover.jpg';
      Object.defineProperty(coverImg, 'clientWidth', { value: 256 });
      Object.defineProperty(coverImg, 'clientHeight', { value: 358 });
      Object.defineProperty(coverImg, 'naturalWidth', { value: 256 });
      Object.defineProperty(coverImg, 'naturalHeight', { value: 358 });

      expect(isMangaImage(coverImg)).toBe(false);
    });

    it('accepts full-sized manga images even if class or id contains preview or thumb', () => {
      const mangaPreview = document.createElement('img');
      mangaPreview.className = 'chapter-page-preview thumb-image';
      mangaPreview.src = 'https://manga.cdn/ch1/p1.jpg';
      Object.defineProperty(mangaPreview, 'clientWidth', { value: 800 });
      Object.defineProperty(mangaPreview, 'clientHeight', { value: 1200 });
      Object.defineProperty(mangaPreview, 'naturalWidth', { value: 800 });
      Object.defineProperty(mangaPreview, 'naturalHeight', { value: 1200 });

      expect(isMangaImage(mangaPreview)).toBe(true);
    });

    it('rejects genuinely small preview thumbnails (< 300px)', () => {
      const smallThumb = document.createElement('img');
      smallThumb.className = 'preview-thumb';
      smallThumb.src = 'https://manga.cdn/thumb.jpg';
      Object.defineProperty(smallThumb, 'clientWidth', { value: 150 });
      Object.defineProperty(smallThumb, 'clientHeight', { value: 200 });
      Object.defineProperty(smallThumb, 'naturalWidth', { value: 150 });
      Object.defineProperty(smallThumb, 'naturalHeight', { value: 200 });

      expect(isMangaImage(smallThumb)).toBe(false);
    });
  });

  describe('isImageReady and waitForImageReady', () => {
    it('isImageReady returns false when naturalWidth is 0 or complete is false', () => {
      const img = document.createElement('img');
      Object.defineProperty(img, 'complete', { value: false });
      Object.defineProperty(img, 'naturalWidth', { value: 0 });

      expect(isImageReady(img)).toBe(false);
    });

    it('isImageReady returns true when image is complete and naturalWidth > 0', () => {
      const img = document.createElement('img');
      Object.defineProperty(img, 'complete', { value: true });
      Object.defineProperty(img, 'naturalWidth', { value: 800 });
      Object.defineProperty(img, 'naturalHeight', { value: 1200 });

      expect(isImageReady(img)).toBe(true);
    });

    it('waitForImageReady resolves immediately if image is already ready', async () => {
      const img = document.createElement('img');
      Object.defineProperty(img, 'complete', { value: true });
      Object.defineProperty(img, 'naturalWidth', { value: 800 });
      Object.defineProperty(img, 'naturalHeight', { value: 1200 });

      const ready = await waitForImageReady(img, 100);
      expect(ready).toBe(true);
    });

    it('waitForImageReady awaits decode() or load event when image is not yet complete', async () => {
      const img = document.createElement('img');
      let completeVal = false;
      let naturalWidthVal = 0;
      Object.defineProperty(img, 'complete', { get: () => completeVal });
      Object.defineProperty(img, 'naturalWidth', { get: () => naturalWidthVal });
      Object.defineProperty(img, 'naturalHeight', { value: 1200 });

      img.decode = vi.fn().mockImplementation(async () => {
        completeVal = true;
        naturalWidthVal = 800;
      });

      const readyPromise = waitForImageReady(img, 500);
      const result = await readyPromise;

      expect(result).toBe(true);
      expect(img.decode).toHaveBeenCalled();
    });

    it('waitForImageReady resolves on load event fallback when decode is not available', async () => {
      const img = document.createElement('img');
      let completeVal = false;
      let naturalWidthVal = 0;
      Object.defineProperty(img, 'complete', { get: () => completeVal });
      Object.defineProperty(img, 'naturalWidth', { get: () => naturalWidthVal });
      Object.defineProperty(img, 'naturalHeight', { value: 1200 });

      // decode undefined to exercise event listener fallback
      delete (img as any).decode;

      const readyPromise = waitForImageReady(img, 500);

      // Trigger load event
      completeVal = true;
      naturalWidthVal = 800;
      img.dispatchEvent(new Event('load'));

      const result = await readyPromise;
      expect(result).toBe(true);
    });

    it('waitForImageReady resolves false on error event or timeout', async () => {
      const img = document.createElement('img');
      Object.defineProperty(img, 'complete', { value: false });
      Object.defineProperty(img, 'naturalWidth', { value: 0 });
      delete (img as any).decode;

      const readyPromise = waitForImageReady(img, 500);
      img.dispatchEvent(new Event('error'));

      const result = await readyPromise;
      expect(result).toBe(false);
    });
  });

  describe('isMangaImage edge cases', () => {
    it('rejects images with empty src or SVG data urls', () => {
      const emptyImg = document.createElement('img');
      expect(isMangaImage(emptyImg)).toBe(false);

      const svgImg = document.createElement('img');
      svgImg.src = 'data:image/svg+xml;utf8,<svg></svg>';
      expect(isMangaImage(svgImg)).toBe(false);
    });
  });

  describe('scanForMangaImages', () => {
    it('discovers manga pages while filtering out icons and ads from DOM container', () => {
      const container = document.createElement('div');

      const page1 = document.createElement('img');
      page1.className = 'manga-page';
      page1.src = 'https://manga.cdn/ch1/01.jpg';
      Object.defineProperty(page1, 'clientWidth', { value: 800 });
      Object.defineProperty(page1, 'clientHeight', { value: 1200 });

      const page2 = document.createElement('img');
      page2.className = 'manga-page';
      page2.src = 'https://manga.cdn/ch1/02.jpg';
      Object.defineProperty(page2, 'clientWidth', { value: 800 });
      Object.defineProperty(page2, 'clientHeight', { value: 1200 });

      const ad = document.createElement('img');
      ad.className = 'sidebar-ad';
      ad.src = 'https://ads.cdn/promo.jpg';
      Object.defineProperty(ad, 'clientWidth', { value: 728 });
      Object.defineProperty(ad, 'clientHeight', { value: 90 });

      const avatar = document.createElement('img');
      avatar.src = 'https://site.com/user.png';
      Object.defineProperty(avatar, 'clientWidth', { value: 32 });
      Object.defineProperty(avatar, 'clientHeight', { value: 32 });

      container.appendChild(page1);
      container.appendChild(page2);
      container.appendChild(ad);
      container.appendChild(avatar);

      const found = scanForMangaImages(container);
      expect(found.length).toBe(2);
      expect(found).toContain(page1);
      expect(found).toContain(page2);
    });
  });
});
