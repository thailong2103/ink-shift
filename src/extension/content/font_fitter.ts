/**
 * Binary Search Font Sizing Algorithm for Speech Bubbles.
 *
 * Efficiently calculates the optimal font size (in pixels) to fit
 * translated text into manga speech bubbles without clipping or overflow,
 * specifically preserving line-height 1.25 for Vietnamese diacritics.
 */

export interface FontFitOptions {
  /** Minimum allowable font size in pixels (default: 1.0 per user specification). */
  minFontSize?: number;
  /** Maximum allowable font size in pixels (default: dynamic 24-80). */
  maxFontSize?: number;
  /** Maximum binary search iterations (default: 8). */
  maxIterations?: number;
  /** Line-height ratio for vertical accent spacing (default: 1.25 for manga bubbles, 1.4 for paragraphs). */
  lineHeight?: number;
  /** When true, formats as prose paragraph (left-aligned, normal wrapping, capped font size). */
  isParagraph?: boolean;
  /** Custom font family override (e.g. clean system sans-serif for prose). */
  fontFamily?: string;
}

/**
 * Fits font size inside container element via binary search within <= maxIterations.
 *
 * @param element The container HTML element containing the text to size.
 * @param options Sizing constraints and convergence settings.
 * @returns The converged font size in pixels.
 */
export function fitFontSize(element: HTMLElement, options: FontFitOptions = {}): number {
  const maxIterations = options.maxIterations ?? 8;
  const lineHeight = options.lineHeight ?? (options.isParagraph ? 1.4 : 1.25);

  element.style.lineHeight = `${lineHeight}`;
  if (options.isParagraph) {
    element.style.wordBreak = 'normal';
    element.style.overflowWrap = 'break-word';
    element.style.hyphens = 'auto';
  } else {
    element.style.wordBreak = 'keep-all';
    element.style.overflowWrap = 'break-word';
    element.style.hyphens = 'none';
  }

  if (options.fontFamily) {
    element.style.fontFamily = options.fontFamily;
  }

  const clientH = element.clientHeight;
  const clientW = element.clientWidth;

  // Adaptive micro-bubble padding to maximize text area and prevent clipping in cramped balloons
  if (!options.isParagraph) {
    if (clientH > 0 && clientW > 0 && (clientH < 18 || clientW < 24)) {
      element.style.padding = '0px';
    } else if (clientH > 0 && clientW > 0 && (clientH < 30 || clientW < 40)) {
      element.style.padding = '1px 2px';
    }
  }

  // Dynamic max font size based on container height (capped for prose paragraphs to read like a book)
  const defaultMax = options.isParagraph
    ? Math.min(Math.max(16, Math.floor(clientH * 0.4)), 32)
    : Math.min(Math.max(24, Math.floor(clientH * 0.65)), 80);
  const maxFontSize = options.maxFontSize ?? defaultMax;

  // Unbounded min font size floor (lowered to 1.0px for both normal and micro-bubbles)
  const defaultMin = 1.0;
  const minFontSize = options.minFontSize ?? defaultMin;

  // Guard against unattached or zero-dimension containers
  if (clientH <= 0 || clientW <= 0) {
    element.style.fontSize = `${minFontSize}px`;
    return minFontSize;
  }

  // Fast-path: check if maximum allowable font size already fits without overflow
  element.style.fontSize = `${maxFontSize}px`;
  if (element.scrollHeight <= clientH && element.scrollWidth <= clientW) {
    return maxFontSize;
  }

  let low = minFontSize;
  let high = Math.max(minFontSize, maxFontSize);
  let bestFit = minFontSize;

  // One check was already performed at maxFontSize for the fast path
  const remainingIterations = Math.max(1, maxIterations - 1);
  for (let i = 0; i < remainingIterations; i++) {
    const mid = (low + high) / 2;
    element.style.fontSize = `${mid}px`;

    const overflows = element.scrollHeight > clientH || element.scrollWidth > clientW;

    if (overflows) {
      high = mid;
    } else {
      bestFit = mid;
      low = mid;
    }

    if (high - low < 0.5) {
      break;
    }
  }

  const finalSize = Math.max(minFontSize, Math.round(bestFit * 10) / 10);
  element.style.fontSize = `${finalSize}px`;
  return finalSize;
}
