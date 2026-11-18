/**
 * Centralized Site Adapter Registry.
 *
 * Coordinates domain-specific adapters for manifest extraction,
 * chapter ID resolution, reader layout detection, and CDN fallback routing.
 */

import type { SiteAdapter } from './base';
import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('AdapterRegistry');

export class SiteAdapterRegistry {
  private adapters: SiteAdapter[] = [];

  public register(adapter: SiteAdapter): void {
    const existingIdx = this.adapters.findIndex((a) => a.id === adapter.id);
    if (existingIdx !== -1) {
      this.adapters[existingIdx] = adapter;
    } else {
      this.adapters.push(adapter);
    }
    logger.debug(`Registered adapter '${adapter.name}' (${adapter.id})`);
  }

  public getAdapter(url: URL | string): SiteAdapter | null {
    try {
      const urlObj = typeof url === 'string' ? new URL(url) : url;
      for (const adapter of this.adapters) {
        if (adapter.matches(urlObj)) {
          return adapter;
        }
      }
    } catch {
      // Return null on malformed URLs
    }
    return null;
  }

  public getAdapters(): readonly SiteAdapter[] {
    return this.adapters;
  }

  public normalizeImageUrl(url: string): string {
    for (const adapter of this.adapters) {
      if (adapter.normalizeImageUrl) {
        const normalized = adapter.normalizeImageUrl(url);
        if (normalized && normalized !== url) {
          logger.debug(`Normalized image URL via adapter '${adapter.name}': ${url} -> ${normalized}`, {
            adapter: adapter.name,
            originalUrl: url,
            normalizedUrl: normalized,
          });
          return normalized;
        }
      }
    }
    return url;
  }

  public resolveFallbackUrl(failedUrl: string, status: number): string | null {
    for (const adapter of this.adapters) {
      if (adapter.resolveFallbackUrl) {
        const fallback = adapter.resolveFallbackUrl(failedUrl, status);
        if (fallback) {
          logger.info(`Resolved CDN fallback via adapter '${adapter.name}': ${failedUrl} -> ${fallback}`, {
            adapter: adapter.name,
            failedUrl,
            fallbackUrl: fallback,
            status,
          });
          return fallback;
        }
      }
    }
    return null;
  }

  public extractChapterId(url: URL): string {
    const adapter = this.getAdapter(url);
    if (adapter?.extractChapterId) {
      const id = adapter.extractChapterId(url);
      if (id) {
        return id;
      }
    }
    const hostname = url.hostname.toLowerCase();
    return `${hostname}:${url.pathname.replace(/^\/|\/$/g, '') || 'ch'}`;
  }

  public extractPageNumber(url: URL): number | null {
    const adapter = this.getAdapter(url);
    if (adapter?.extractPageNumber) {
      const page = adapter.extractPageNumber(url);
      if (typeof page === 'number' && page > 0) {
        return page;
      }
    }
    return null;
  }

  public detectReaderLayout(doc: Document, url?: URL): 'single' | 'double' | 'strip' | null {
    const targetUrl =
      url || (typeof window !== 'undefined' && window.location ? new URL(window.location.href) : undefined);
    if (targetUrl) {
      const adapter = this.getAdapter(targetUrl);
      if (adapter?.detectReaderLayout) {
        return adapter.detectReaderLayout(doc);
      }
    }
    return null;
  }

  public clear(): void {
    this.adapters = [];
  }
}

export const siteAdapterRegistry = new SiteAdapterRegistry();

