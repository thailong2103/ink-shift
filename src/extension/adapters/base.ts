/**
 * Site Manifest & Reader Protocol Adapter Interface.
 *
 * Defines the contract for domain-specific adapters handling chapter discovery,
 * custom URL parsing, CDN fallback resolution, and layout preferences.
 */

import type { ChapterContextReport } from '../shared/context_types';

export interface SiteAdapter {
  /**
   * Unique identifier for this adapter (e.g., 'mangadex', 'hitomi').
   */
  readonly id: string;

  /**
   * Human-readable label for diagnostics and telemetry.
   */
  readonly name: string;

  /**
   * Regular expression pattern matched against hostname.
   */
  readonly domainPattern: RegExp;

  /**
   * Checks whether this adapter should handle the given URL.
   */
  matches(url: URL | string): boolean;

  /**
   * Extracts canonical chapter ID from URL if site has a specific pattern.
   * If omitted or returns null, caller falls back to standard hostname:pathname slug.
   */
  extractChapterId?(url: URL): string | null;

  /**
   * Extracts page number from URL if site has a specific pattern (e.g. hash or query param).
   */
  extractPageNumber?(url: URL): number | null;

  /**
   * Inspects site-specific DOM markers or localStorage for reader layout mode
   * (e.g., 'single', 'double', 'strip').
   */
  detectReaderLayout?(doc: Document): 'single' | 'double' | 'strip' | null;

  /**
   * Rewrites or normalizes CDN image URLs to a format supported by backend AI models
   * (e.g. converting AVIF to WebP format or pointing to a reliable edge origin).
   */
  normalizeImageUrl?(url: string): string;

  /**
   * Resolves an alternate CDN image URL when a transient network error (404/5xx) occurs.
   * Return null if no fallback applies.
   */
  resolveFallbackUrl?(failedUrl: string, status: number): string | null;

  /**
   * Extracts full chapter manifest. Can delegate to Service Worker or inspect local DOM.
   */
  extractManifest?(doc: Document, url: URL): Promise<ChapterContextReport | null>;
}

