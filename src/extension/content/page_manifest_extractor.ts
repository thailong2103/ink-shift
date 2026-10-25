/**
 * Hybrid Chapter Page Manifest Extractor.
 *
 * Coordinates MangaDex API delegation via Service Worker and client-side
 * DOM waterfall scanning for vertical strip CMS readers (Madara, Webtoons, Bato).
 */

import type { ChapterContextReport, PageItem } from '../shared/context_types';
import type { ReaderDetectionResult } from './reader_detector';
import { isMangaImage } from './dom_scanner';
import type { IPCMessage, IPCResponse } from '../shared/ipc_types';
import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('Manifest');

const SEO_PATTERNS = [
  /\s*-\s*Read\s+Manga.*$/i,
  /\s*-\s*MangaDex.*$/i,
  /\s*\|\s*Webtoon.*$/i,
  /\s*-\s*Bato.*$/i,
  /\s*-\s*NetTruyen.*$/i,
  /\s*-\s*Chap(ter)?\s*\d+.*$/i,
  /\s*Manga\s+Online.*$/i,
  /\s*Free\s+Manga.*$/i,
  /\[.*?\]|\(.*?\)/g,
];

/**
 * Clean raw web page titles into canonical series display titles by removing SEO noise.
 */
export function sanitizeSeriesTitle(rawTitle: string): string {
  let title = rawTitle;
  for (const pattern of SEO_PATTERNS) {
    title = title.replace(pattern, ' ');
  }
  title = title.replace(/[-|_]+/g, ' ').replace(/\s+/g, ' ').trim();
  return title || 'Unknown Series';
}

/**
 * Extract image source URL respecting dataset attribute cascade for lazy-loading.
 */
export function extractImageSourceUrl(img: HTMLImageElement): string {
  const candidates = [
    img.getAttribute('data-url'),
    img.getAttribute('data-src'),
    img.getAttribute('data-original'),
    img.getAttribute('data-lazy-src'),
    img.currentSrc,
    img.src,
  ];

  for (const src of candidates) {
    if (src && typeof src === 'string' && !src.startsWith('data:image/svg') && src.trim().length > 0) {
      return src.trim();
    }
  }

  return '';
}

/**
 * Extract numeric chapter ordinal from title or URL.
 */
export function extractChapterOrdinal(text: string): number {
  const match = text.match(/chap(?:ter)?\s*[:.-]?\s*(\d+(?:\.\d+)?)/i);
  if (match && match[1]) {
    return parseFloat(match[1]);
  }
  return 1.0;
}

/**
 * Extract full chapter manifest using MangaDex API or DOM waterfall cascade.
 */
export async function extractChapterManifest(
  doc: Document = document,
  url: URL = new URL(window.location.href),
  detection?: ReaderDetectionResult
): Promise<ChapterContextReport> {
  const hostname = url.hostname.toLowerCase();

  // 1. MangaDex Specific Extraction: Delegate to Service Worker
  if (hostname.includes('mangadex.org')) {
    const chapterMatch = url.pathname.match(/\/chapter\/([a-f0-9-]+)/i);
    if (chapterMatch && chapterMatch[1]) {
      const chapterUuid = chapterMatch[1];

      // Detect quality parity preference from active DOM
      let preferredQuality: 'data' | 'dataSaver' = 'data';
      const domImages = Array.from(doc.querySelectorAll<HTMLImageElement>('img'));
      if (domImages.some((img) => (img.currentSrc || img.src || '').includes('/data-saver/'))) {
        preferredQuality = 'dataSaver';
      }

      if (typeof chrome !== 'undefined' && chrome.runtime?.sendMessage) {
        logger.info(`Delegating MangaDex manifest extraction to Service Worker (chapter: ${chapterUuid})`, {
          chapterUuid,
        });
        const msg: IPCMessage = {
          type: 'FETCH_MANGADEX_MANIFEST',
          payload: { chapterUuid, preferredQuality },
        };
        const response: IPCResponse<ChapterContextReport> = await chrome.runtime.sendMessage(msg);
        if (response && response.success && response.data) {
          return response.data;
        }
      }
    }
  }

  // 2. Generic CMS / Vertical Webtoon Scanner (DOM Waterfall)
  const container = detection?.readerContainer || doc.body;
  const rawImages = Array.from(container.querySelectorAll<HTMLImageElement>('img'));

  // Filter valid manga images
  const validImages = rawImages.filter((img) => isMangaImage(img));

  const pages: PageItem[] = [];
  for (let idx = 0; idx < validImages.length; idx++) {
    const img = validImages[idx];
    const src = extractImageSourceUrl(img);
    if (src) {
      pages.push({
        page_number: idx + 1,
        image_url: src,
        status: 'discovered',
      });
    }
  }

  // Metadata Resolution
  const rawTitle = detection?.chapterMeta?.seriesSlug || doc.title;
  const seriesTitle = sanitizeSeriesTitle(rawTitle);
  const chapterOrdinal =
    detection?.chapterMeta?.chapterNumber ?? extractChapterOrdinal(`${doc.title} ${url.pathname}`);
  const chapterLabel = `Ch. ${chapterOrdinal}`;

  const cleanSlug = seriesTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const seriesId = `${hostname}:${cleanSlug || 'manga'}`;
  const chapterId = `${hostname}:${url.pathname.replace(/^\/|\/$/g, '') || 'ch'}`;

  logger.info(`Extracted ${pages.length} chapter pages from DOM waterfall (series: "${seriesTitle}")`, {
    pagesCount: pages.length,
    seriesTitle,
  });

  return {
    series_id: seriesId,
    series_title: seriesTitle,
    source_domain: hostname,
    chapter_id: chapterId,
    chapter_ordinal: chapterOrdinal,
    chapter_label: chapterLabel,
    chapter_url: url.href,
    total_pages: pages.length,
    pages,
  };
}
