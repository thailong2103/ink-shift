/**
 * DOM Manga Page Scanner & Lazy-Load Dimension Guard.
 *
 * Scans manga reader pages for active manga image elements while filtering
 * avatars, icons, advertising banners, and sponsor widgets. Ensures lazy-loaded
 * images have completed network loading and decoding before geometry math.
 */

export const MIN_MANGA_DIMENSION = 300;
export const MIN_ASPECT_RATIO = 0.15; // Vertical webtoon strips
export const MAX_ASPECT_RATIO = 4.0; // Two-page wide spreads
export const DEFAULT_DECODE_TIMEOUT_MS = 5000;

const EXPLICIT_AD_PATTERNS =
  /(avatar|icon|logo|banner|sponsor|ad-|advertisement|ad_|promo|widget)/i;
const PREVIEW_PATTERNS = /(thumb|preview|badge)/i;

/**
 * Checks if an image element has finished downloading and has positive natural dimensions.
 */
export function isImageReady(img: HTMLImageElement): boolean {
  return img.complete === true && img.naturalWidth > 0 && img.naturalHeight > 0;
}

/**
 * Asynchronously waits for an image to complete and decode, avoiding race
 * conditions where geometry calculations run on placeholder dimensions.
 */
export async function waitForImageReady(
  img: HTMLImageElement,
  timeoutMs: number = DEFAULT_DECODE_TIMEOUT_MS
): Promise<boolean> {
  if (isImageReady(img)) {
    return true;
  }

  // Attempt HTMLImageElement.prototype.decode() if supported
  if (typeof img.decode === 'function') {
    let decodeTimer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        img.decode(),
        new Promise((_, reject) => {
          decodeTimer = setTimeout(() => reject(new Error('decode timeout')), timeoutMs);
        }),
      ]);
      if (isImageReady(img)) {
        return true;
      }
    } catch {
      // Fall through to event listener fallback
    } finally {
      if (decodeTimer) {
        clearTimeout(decodeTimer);
      }
    }
  }

  // Fallback to one-shot load event listener
  return new Promise<boolean>((resolve) => {
    let resolved = false;

    const timer = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        cleanup();
        resolve(isImageReady(img));
      }
    }, timeoutMs);

    const onLoad = () => {
      if (!resolved) {
        resolved = true;
        cleanup();
        resolve(isImageReady(img));
      }
    };

    const onError = () => {
      if (!resolved) {
        resolved = true;
        cleanup();
        resolve(false);
      }
    };

    const cleanup = () => {
      clearTimeout(timer);
      img.removeEventListener('load', onLoad);
      img.removeEventListener('error', onError);
    };

    img.addEventListener('load', onLoad, { once: true });
    img.addEventListener('error', onError, { once: true });
  });
}

/**
 * Determines whether a given <img> element represents a valid manga page.
 */
export function isMangaImage(img: HTMLImageElement): boolean {
  const src =
    img.currentSrc ||
    img.src ||
    img.getAttribute('data-src') ||
    img.getAttribute('data-original') ||
    img.getAttribute('data-lazy-src') ||
    '';

  if (!src || src.startsWith('data:image/svg')) {
    return false;
  }

  // Filter out explicit advertising, avatars, icons, or sponsor widgets
  const identity = `${img.className} ${img.id} ${img.alt || ''} ${img.getAttribute('data-role') || ''}`;
  if (EXPLICIT_AD_PATTERNS.test(identity)) {
    return false;
  }

  // Filter out catalog cover thumbnails and posters (manga chapters are not covers)
  if (
    /\/covers\//i.test(src) ||
    /cover\.(jpg|jpeg|png|webp)/i.test(src) ||
    /(manga-cover|title-cover|book-cover)/i.test(identity)
  ) {
    return false;
  }

  const width = img.clientWidth || img.naturalWidth || 0;
  const height = img.clientHeight || img.naturalHeight || 0;

  // If image is still downloading (!complete), allow it through for decode waiting if not an ad
  if (!img.complete && width === 0 && height === 0) {
    return true;
  }

  // Filter out tracking pixels and tiny icons
  if (width < 50 || height < 50) {
    return false;
  }

  // Must satisfy minimum size threshold in at least one dimension
  if (width < MIN_MANGA_DIMENSION && height < MIN_MANGA_DIMENSION) {
    return false;
  }

  // If identity matches preview/thumb patterns, only reject if it is genuinely small
  if (PREVIEW_PATTERNS.test(identity)) {
    if (width < MIN_MANGA_DIMENSION || height < MIN_MANGA_DIMENSION) {
      return false;
    }
  }

  // Filter out banner ads with extreme horizontal or vertical aspect ratios
  if (width > 0 && height > 0) {
    const aspect = width / height;
    if (aspect < MIN_ASPECT_RATIO || aspect > MAX_ASPECT_RATIO) {
      return false;
    }
  }

  return true;
}

/**
 * Scans a DOM container (default document) and returns all detected manga images.
 */
export function scanForMangaImages(root?: Element | Document): HTMLImageElement[] {
  const container = root ?? document;
  const allImages = Array.from(container.querySelectorAll('img'));
  return allImages.filter(isMangaImage);
}

export const findMangaImages = scanForMangaImages;
