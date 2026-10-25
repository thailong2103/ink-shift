/**
 * InkShift Profile-Assisted Heuristic Engine (PAHE).
 *
 * Evaluates whether the current DOM & URL context represents a genuine
 * manga reading page (either vertical long-strip or horizontal single-page).
 * Eliminates false-positive auto-translations on catalogs, blogs, and stores.
 */

export type ReaderLayoutType = 'profile-matched' | 'long-strip' | 'single-page' | 'none';

export interface ReaderSignal {
  name: string;
  weight: number;
  details?: string;
}

export interface MangaChapterMeta {
  seriesSlug: string;
  chapterNumber?: number;
  sourceDomain: string;
  chapterUrl: string;
}

export interface ReaderDetectionResult {
  isReaderPage: boolean;
  confidence: number; // 0.0 to 1.0
  layoutType: ReaderLayoutType;
  readerContainer?: Element;
  chapterMeta?: MangaChapterMeta;
  signals: ReaderSignal[];
}

export interface SiteProfile {
  name: string;
  domainPattern?: RegExp;
  urlPattern?: RegExp;
  containerSelectors: string[];
  imageSelector?: string;
}

export const KNOWN_PROFILES: SiteProfile[] = [
  {
    name: 'Madara / WP-Manga CMS',
    containerSelectors: ['.reading-content', '.read-container', '#manga-reading-nav-head'],
    imageSelector: '.page-break img, .reading-content img, .wp-manga-chapter-img',
  },
  {
    name: 'NetTruyen Network',
    containerSelectors: ['.reading-detail', '.page-chapter'],
    imageSelector: '.page-chapter img, .reading-detail img',
  },
  {
    name: 'MangaDex',
    domainPattern: /mangadex\.org$/i,
    urlPattern: /\/chapter\/[a-zA-Z0-9_-]+/i,
    containerSelectors: [
      '.reader--container',
      '.reader--main',
      '.pages-container',
      '#reader',
    ],
    imageSelector: 'img.md-image, .page img, img',
  },
  {
    name: 'Webtoons',
    domainPattern: /webtoons\.com$/i,
    urlPattern: /\/viewer(?:\/|$)/i,
    containerSelectors: ['#_imageList', '.viewer_lst'],
    imageSelector: 'img._images',
  },
  {
    name: 'CuuTruyen',
    domainPattern: /cuutruyen\.net$/i,
    urlPattern: /\/manga\/.*\/reader\//i,
    containerSelectors: ['.reader-content', '.reader-container'],
    imageSelector: '.reader-content img, img',
  },
];

const CHAPTER_URL_REGEX =
  /(?:chapter|chap|ch|ep|tap|reading|read)[-_/]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d+(?:\.\d+)?)(?=[/._-]|$)/i;
const NEGATIVE_URL_REGEX =
  /\/(the-loai|genre|genres|search|author|tag|tags|danh-muc|browse|titles|title|manga|series|latest|updates|random|recently-added|feed|follows|library|history|mdlist|community|forum|forums|group|groups|news|about|contact|login|signup|register|settings|notifications)(\/|$)/i;

/**
 * Extracts series slug, chapter number, and canonical URL.
 */
export function extractMangaMetadata(url: URL, doc: Document): MangaChapterMeta {
  const path = url.pathname;
  let chapterNumber: number | undefined;

  // 1. Extract chapter number from URL path (must not be part of a UUID or word)
  const chapMatch = path.match(CHAPTER_URL_REGEX);
  if (chapMatch && chapMatch[1] && !chapMatch[1].includes('-')) {
    chapterNumber = parseFloat(chapMatch[1]);
  }

  // 2. Fallback chapter number from document title (e.g. "One Piece Chapter 1050")
  if (chapterNumber === undefined && doc.title) {
    const titleMatch = doc.title.match(/(?:chapter|chap|ch|tập)\s*(\d+(?:\.\d+)?)/i);
    if (titleMatch && titleMatch[1]) {
      chapterNumber = parseFloat(titleMatch[1]);
    }
  }

  // 3. Fallback to trailing page/chap number in URL (e.g. /chapter/{uuid}/14)
  const segments = path.split('/').filter(Boolean);
  if (chapterNumber === undefined && segments.length >= 2) {
    const lastSeg = segments[segments.length - 1];
    if (lastSeg && /^\d+$/.test(lastSeg)) {
      chapterNumber = parseFloat(lastSeg);
    }
  }

  // 4. Extract series slug from URL path
  let seriesSlug = 'unknown-series';
  const chapIdx = segments.findIndex((s) => CHAPTER_URL_REGEX.test(s));

  if (chapIdx > 0) {
    seriesSlug = segments[chapIdx - 1];
  } else if (segments.length >= 2) {
    seriesSlug = segments[segments.length - 2];
  } else if (segments.length === 1) {
    seriesSlug = segments[0];
  }

  // If seriesSlug is a UUID or generic, extract clean series name from doc.title
  if (
    doc.title &&
    (seriesSlug === 'unknown-series' ||
      /^[0-9a-f]{8}-[0-9a-f]{4}/i.test(seriesSlug) ||
      seriesSlug === 'chapter')
  ) {
    const titleParts = doc.title
      .split(/[-|–•]/)
      .map((p) => p.trim())
      .filter(Boolean);
    for (const part of titleParts) {
      if (
        !/(?:chapter|chap|ch|tập|mangadex|read online|truyện)/i.test(part) &&
        part.length >= 2
      ) {
        seriesSlug = part
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '');
        break;
      }
    }
  }

  // Sanitize series slug
  seriesSlug = seriesSlug.replace(/[^a-zA-Z0-9-_]/g, '').toLowerCase() || 'unknown-series';

  return {
    seriesSlug,
    chapterNumber,
    sourceDomain: url.hostname,
    chapterUrl: url.origin + url.pathname,
  };
}

/**
 * Detects whether the current document is a manga reader page using the PAHE engine.
 */
export function detectReaderContext(
  loc: Location | URL = window.location,
  doc: Document = document
): ReaderDetectionResult {
  const url = loc instanceof URL ? loc : new URL(loc.href);
  const signals: ReaderSignal[] = [];
  const hostname = url.hostname.toLowerCase();
  const pathname = url.pathname;

  // Homepage & Root URL guard: Real site root URLs are never chapter readers unless on localhost / 127.0.0.1
  const isHomepage =
    (pathname === '/' || pathname === '' || /^\/(index|home|default)(\.[a-z]+)?$/i.test(pathname)) &&
    hostname !== 'localhost' &&
    hostname !== '127.0.0.1';

  if (isHomepage) {
    return {
      isReaderPage: false,
      confidence: 0,
      layoutType: 'none',
      signals: [{ name: 'homepage_root', weight: -1, details: pathname }],
    };
  }

  // Negative URL guard: Catalog / Genre / Search listing
  if (NEGATIVE_URL_REGEX.test(pathname) && !CHAPTER_URL_REGEX.test(pathname)) {
    return {
      isReaderPage: false,
      confidence: 0.05,
      layoutType: 'none',
      signals: [{ name: 'negative_url_pattern', weight: -1, details: pathname }],
    };
  }

  // --- Tier 1: Fast-Path Known Profiles ---
  for (const profile of KNOWN_PROFILES) {
    if (profile.domainPattern && !profile.domainPattern.test(hostname)) {
      continue;
    }

    // If profile defines urlPattern, URL must match to be considered a reader for this profile
    if (profile.urlPattern && !profile.urlPattern.test(pathname)) {
      continue;
    }

    const isUrlMatch = profile.urlPattern && profile.urlPattern.test(pathname);

    for (const selector of profile.containerSelectors) {
      const containerEl = doc.querySelector(selector);
      if (containerEl) {
        const imageCount = containerEl.querySelectorAll('img').length;
        if (imageCount > 0) {
          signals.push({
            name: `profile_match:${profile.name}`,
            weight: 1.0,
            details: `Container: ${selector}, images: ${imageCount}`,
          });

          return {
            isReaderPage: true,
            confidence: 1.0,
            layoutType: 'profile-matched',
            readerContainer: containerEl,
            chapterMeta: extractMangaMetadata(url, doc),
            signals,
          };
        }
      }
    }

    if (isUrlMatch) {
      signals.push({
        name: `profile_url_match:${profile.name}`,
        weight: 1.0,
        details: `URL: ${pathname}`,
      });

      return {
        isReaderPage: true,
        confidence: 1.0,
        layoutType: 'profile-matched',
        readerContainer: doc.body,
        chapterMeta: extractMangaMetadata(url, doc),
        signals,
      };
    }
  }

  // --- Tier 2: Homogeneous Dimension Clustering (Long-Strip) ---
  const allImages = Array.from(doc.querySelectorAll('img'));
  const candidateImages = allImages.filter((img) => {
    const w = img.clientWidth || img.naturalWidth || 0;
    const h = img.clientHeight || img.naturalHeight || 0;
    return w >= 250 || h >= 300;
  });

  // Group candidate images by direct parent or grandparent container
  const containerMap = new Map<Element, HTMLImageElement[]>();
  for (const img of candidateImages) {
    const parent = img.parentElement;
    if (!parent || parent === doc.body || parent === doc.documentElement) {
      continue;
    }
    // Check direct parent or grand-parent (to handle <div class="page-break"><img/></div>)
    const container = parent.querySelectorAll('img').length >= 3 ? parent : parent.parentElement ?? parent;
    const list = containerMap.get(container) ?? [];
    list.push(img);
    containerMap.set(container, list);
  }

  // Check dimension clustering across containers
  for (const [container, images] of containerMap.entries()) {
    if (images.length >= 3) {
      const widths = images.map((img) => img.clientWidth || img.naturalWidth || 0).filter((w) => w > 0);
      if (widths.length >= 3) {
        const meanW = widths.reduce((sum, w) => sum + w, 0) / widths.length;
        const varianceW =
          widths.reduce((sum, w) => sum + Math.pow(w - meanW, 2), 0) / widths.length;
        const stdW = Math.sqrt(varianceW);
        const cvW = meanW > 0 ? stdW / meanW : 1.0;

        // Check text density inside candidate container
        const textContent = container.textContent || '';
        const isLowText = textContent.trim().length < 800;

        // In a vertical long-strip, images must be vertically aligned in a column, not in a multi-column card grid
        let isMultiColumnGrid = false;
        if (images.length >= 2) {
          const firstLeft =
            typeof images[0].getBoundingClientRect === 'function'
              ? images[0].getBoundingClientRect().left
              : 0;
          isMultiColumnGrid = images.some((im) => {
            if (typeof im.getBoundingClientRect !== 'function') return false;
            return Math.abs(im.getBoundingClientRect().left - firstLeft) > 120;
          });
        }

        const hasChapterContext =
          CHAPTER_URL_REGEX.test(pathname) || (doc.title ? CHAPTER_URL_REGEX.test(doc.title) : false);

        if (cvW <= 0.18 && isLowText && !isMultiColumnGrid && hasChapterContext) {
          signals.push({
            name: 'dimension_clustering_match',
            weight: 0.95,
            details: `Images: ${images.length}, CV_w: ${cvW.toFixed(3)}, meanW: ${meanW.toFixed(0)}px`,
          });

          return {
            isReaderPage: true,
            confidence: 0.95,
            layoutType: 'long-strip',
            readerContainer: container,
            chapterMeta: extractMangaMetadata(url, doc),
            signals,
          };
        }
      }
    }
  }

  // --- Tier 3: Viewport Prominence & Centrality (Single-Page Reader) ---
  const vpWidth = typeof window !== 'undefined' && window.innerWidth ? window.innerWidth : 1280;
  const vpHeight = typeof window !== 'undefined' && window.innerHeight ? window.innerHeight : 800;
  const vpArea = vpWidth * vpHeight;

  if (candidateImages.length >= 1 && candidateImages.length <= 3) {
    for (const img of candidateImages) {
      const rect = img.getBoundingClientRect ? img.getBoundingClientRect() : null;
      const w = rect ? rect.width : img.clientWidth || img.naturalWidth || 0;
      const h = rect ? rect.height : img.clientHeight || img.naturalHeight || 0;
      const imgArea = w * h;

      if (vpArea > 0 && imgArea > 0) {
        const vcr = imgArea / vpArea;
        const imgCenterX = rect ? rect.left + rect.width / 2 : vpWidth / 2;
        const offsetFromCenter = Math.abs(imgCenterX - vpWidth / 2);

        // Aspect ratio: portrait manga page typically 0.5 to 1.8
        const aspect = h > 0 ? w / h : 1.0;
        const isPortraitOrSquare = aspect >= 0.45 && aspect <= 1.8;

        const hasChapterUrl = CHAPTER_URL_REGEX.test(pathname) || CHAPTER_URL_REGEX.test(url.search);

        if (vcr >= 0.35 && offsetFromCenter <= 120 && isPortraitOrSquare) {
          const confidence = hasChapterUrl ? 0.9 : 0.85;
          signals.push({
            name: 'single_page_viewport_prominence',
            weight: confidence,
            details: `VCR: ${(vcr * 100).toFixed(1)}%, centerOffset: ${offsetFromCenter.toFixed(0)}px`,
          });

          return {
            isReaderPage: true,
            confidence,
            layoutType: 'single-page',
            readerContainer: img.parentElement ?? undefined,
            chapterMeta: extractMangaMetadata(url, doc),
            signals,
          };
        }
      }
    }
  }

  // --- Default: Not a recognized reader page ---
  return {
    isReaderPage: false,
    confidence: 0.2,
    layoutType: 'none',
    signals,
  };
}
