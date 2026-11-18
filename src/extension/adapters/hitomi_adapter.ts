/**
 * Hitomi.la Reader & CDN Protocol Adapter.
 *
 * Implements SiteAdapter interface to encapsulate Hitomi-specific logic:
 * - Gallery/Chapter ID extraction from /reader/{id}.html
 * - Reading layout preference from body class (spread1 = single, spread2 = double)
 * - Safe Main-World DOM bridge for window.galleryinfo and url_from_url_from_hash resolution
 * - WebP format prioritization for lossless native Python backend decoding
 * - Fallback CDN url rewriter (avif -> webp)
 */

import type { ChapterContextReport, PageItem } from '../shared/context_types';
import type { SiteAdapter } from './base';
import { siteAdapterRegistry } from './registry';
import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('Hitomi');

export interface HitomiBridgePayload {
  id: string;
  title: string;
  pages: PageItem[];
}

/**
 * Safely bridges into Main-World JavaScript context to read window.galleryinfo
 * and resolve full CDN URLs via Hitomi's native url_from_url_from_hash function.
 */
export async function queryHitomiMainWorldManifest(
  doc: Document = document,
  timeoutMs: number = 800
): Promise<HitomiBridgePayload | null> {
  // Guard for Node/JSDOM test environments where script elements don't execute JS
  if (typeof window === 'undefined' || !doc.defaultView) {
    return null;
  }

  return new Promise((resolve) => {
    const eventName = `__inkshift_hitomi_bridge_${Math.random().toString(36).slice(2)}`;
    let resolved = false;

    const timer = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        doc.removeEventListener(eventName, handler as EventListener);
        resolve(null);
      }
    }, timeoutMs);

    const handler = (event: Event) => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timer);
      doc.removeEventListener(eventName, handler as EventListener);

      const customEvent = event as CustomEvent<string>;
      try {
        if (!customEvent.detail || customEvent.detail === 'null') {
          resolve(null);
          return;
        }
        const data = JSON.parse(customEvent.detail) as HitomiBridgePayload;
        resolve(data);
      } catch {
        resolve(null);
      }
    };

    doc.addEventListener(eventName, handler as EventListener);

    try {
      const script = doc.createElement('script');
      script.textContent = `
        (function() {
          try {
            var gi = window.galleryinfo;
            if (!gi || !Array.isArray(gi.files)) {
              document.dispatchEvent(new CustomEvent('${eventName}', { detail: 'null' }));
              return;
            }
            var id = String(gi.id || '');
            var title = String(gi.title || 'Hitomi Gallery ' + id);
            var pages = [];
            for (var i = 0; i < gi.files.length; i++) {
              var file = gi.files[i];
              var imgUrl = '';
              if (typeof window.url_from_url_from_hash === 'function') {
                imgUrl = window.url_from_url_from_hash(id, file, 'avif');
              }
              if (imgUrl) {
                pages.push({
                  page_number: i + 1,
                  image_url: imgUrl,
                  status: 'discovered'
                });
              }
            }
            document.dispatchEvent(new CustomEvent('${eventName}', {
              detail: JSON.stringify({ id: id, title: title, pages: pages })
            }));
          } catch (e) {
            document.dispatchEvent(new CustomEvent('${eventName}', { detail: 'null' }));
          }
        })();
      `;
      (doc.head || doc.documentElement).appendChild(script);
      script.remove();
    } catch {
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);
        doc.removeEventListener(eventName, handler as EventListener);
        resolve(null);
      }
    }
  });
}

/**
 * Unified Hitomi Site Adapter implementing SiteAdapter contract.
 */
export class HitomiAdapter implements SiteAdapter {
  public readonly id = 'hitomi';
  public readonly name = 'Hitomi';
  public readonly domainPattern = /hitomi\.la$/i;

  private _cachedRootPrefix: string | null = null;
  private _cachedPrefixTimestamp: number = 0;
  private _shardDefaultO: number = 0;
  private _shardOverrides: Map<string, number> = new Map();
  private readonly PREFIX_TTL_MS = 60 * 60 * 1000; // 1 hour

  /**
   * Parses Hitomi's gg.js script for the folder-to-shard mapping (`gg.m(g)`)
   * and returns the resolved root prefix (`gg.b`) if present.
   */
  private parseGgScript(ggText: string): string | null {
    const defaultMatch = ggText.match(/var\s+o\s*=\s*(\d+)/);
    const defaultO = defaultMatch ? parseInt(defaultMatch[1], 10) : 0;
    const overrides = new Map<string, number>();

    const switchMatch = ggText.match(/switch\s*\([^)]*\)\s*\{([\s\S]*?)\}/);
    if (switchMatch && switchMatch[1]) {
      const tokenRegex = /case\s+(\d+)\s*:|o\s*=\s*(\d+)\s*;|break\s*;/g;
      let pendingCases: string[] = [];
      let match: RegExpExecArray | null;
      while ((match = tokenRegex.exec(switchMatch[1])) !== null) {
        if (match[1] !== undefined) {
          pendingCases.push(match[1]);
        } else if (match[2] !== undefined) {
          const val = parseInt(match[2], 10);
          for (const folderId of pendingCases) {
            overrides.set(folderId, val);
          }
        } else {
          pendingCases = [];
        }
      }
    }

    this._shardDefaultO = Number.isNaN(defaultO) ? 0 : defaultO;
    this._shardOverrides = overrides;

    const bMatch = ggText.match(/(?:var\s+b\s*=\s*|b\s*:\s*|gg\.b\s*=\s*)['"](\d+)\/?['"]/i);
    return bMatch && bMatch[1] ? `${bMatch[1]}/` : null;
  }

  private resolveAvifSubdomain(folder: string): string {
    const o = folder && this._shardOverrides.has(folder)
      ? (this._shardOverrides.get(folder) ?? this._shardDefaultO)
      : this._shardDefaultO;
    return `a${1 + o}`;
  }

  /**
   * Resolves Hitomi CDN rootPrefix (gg.b partition) through multi-tiered sources:
   * 1. In-memory TTL cache (valid for 1 hour)
   * 2. Active DOM images in #comicImages / #preload / picture source
   * 3. Direct fetch of Hitomi's dynamic gg.js script (https://ltn.gold-usergeneratedcontent.net/gg.js)
   */
  public async resolveRootPrefix(doc: Document = document): Promise<string | null> {
    const now = Date.now();
    if (this._cachedRootPrefix && (now - this._cachedPrefixTimestamp) < this.PREFIX_TTL_MS) {
      return this._cachedRootPrefix;
    }

    // 1. Try DOM images first (fastest, zero network overhead)
    try {
      const domImages = Array.from(
        doc.querySelectorAll<HTMLImageElement>('#comicImages img, #preload img, picture source, img')
      );
      for (const img of domImages) {
        const raw = img.currentSrc || img.src || img.getAttribute('srcset') || img.getAttribute('data-src') || '';
        const m = raw.match(/gold-usergeneratedcontent\.net\/([^/]+)\//);
        if (m && m[1] && /^\d+$/.test(m[1])) {
          const prefix = `${m[1]}/`;
          this._cachedRootPrefix = prefix;
          this._cachedPrefixTimestamp = now;
          return prefix;
        }
      }
    } catch {
      // Ignore DOM query errors in non-browser environments
    }

    // 2. Fetch Hitomi's official gg.js directly from CDN
    try {
      const ggResp = await fetch('https://ltn.gold-usergeneratedcontent.net/gg.js');
      if (ggResp.ok) {
        const ggText = await ggResp.text();
        const prefix = this.parseGgScript(ggText);
        if (prefix) {
          this._cachedRootPrefix = prefix;
          this._cachedPrefixTimestamp = now;
          logger.info(`Resolved Hitomi rootPrefix from gg.js: ${prefix}`);
          return prefix;
        }
      }
    } catch (err) {
      logger.debug(`Failed to fetch gg.js: ${err instanceof Error ? err.message : String(err)}`);
    }

    return null;
  }

  public matches(url: URL | string): boolean {
    try {
      const hostname = typeof url === 'string' ? new URL(url).hostname : url.hostname;
      return this.domainPattern.test(hostname) || hostname.toLowerCase().includes('hitomi.la');
    } catch {
      return false;
    }
  }

  public extractChapterId(url: URL): string | null {
    const match = url.pathname.match(/\/reader\/(\d+)\.html/i);
    return match && match[1] ? match[1] : null;
  }

  public extractPageNumber(url: URL): number | null {
    const hashMatch = url.hash.match(/^#(\d+)/);
    if (hashMatch && hashMatch[1]) {
      return parseInt(hashMatch[1], 10);
    }
    return null;
  }

  public detectReaderLayout(doc: Document): 'single' | 'double' | 'strip' | null {
    const bodyClass = doc.body?.className || '';
    if (bodyClass.includes('spread2')) return 'double';
    if (bodyClass.includes('spread1')) return 'single';
    if (bodyClass.includes('scroll') || bodyClass.includes('webtoon')) return 'strip';
    return 'single'; // Hitomi default reading layout
  }

  public normalizeImageUrl(url: string): string {
    if (url.includes('.gold-usergeneratedcontent.net/')) {
      // Prioritize high-performance Anycast AVIF cluster (a1/a2) over brittle dedicated WebP (w1/w2)
      return url
        .replace(/\.webp(?=[?#]|$)/i, '.avif')
        .replace(/(https?:\/\/|\/\/)w(\d+)\.gold-usergeneratedcontent\.net\//i, '$1a$2.gold-usergeneratedcontent.net/');
    }
    return url;
  }

  public resolveFallbackUrl(failedUrl: string, status: number): string | null {
    // Catch HTTP 404/5xx OR connection abort/timeout (status === 0)
    if ((status === 0 || status === 404 || status >= 500) && failedUrl.includes('.gold-usergeneratedcontent.net/')) {
      // 1. If Anycast a1.avif fails (e.g. page is sharded on a2), failover first to a2.avif on Cloudflare Anycast
      if (failedUrl.includes('/a1.') && (failedUrl.endsWith('.avif') || failedUrl.includes('.avif?'))) {
        return failedUrl.replace(/\/a1\./, '/a2.');
      }

      // 2. If Anycast .avif fails on a2, fallback to .webp on w[1-9] subdomain
      if (failedUrl.endsWith('.avif') || failedUrl.includes('.avif?')) {
        return failedUrl.replace(/\.avif(?=[?#]|$)/i, '.webp').replace(/\/a(\d+)\./, '/w$1.');
      }

      // 3. If w1 fails with 404, fallback to w2; if w2 fails, fallback to w1
      const subMatch = failedUrl.match(/\/\/w(\d+)\.gold-usergeneratedcontent\.net\//);
      if (subMatch && subMatch[1]) {
        const currentSub = subMatch[1];
        const nextSub = currentSub === '1' ? '2' : '1';
        return failedUrl.replace(`//w${currentSub}.`, `//w${nextSub}.`);
      }
    }
    return null;
  }

  public async extractManifest(doc: Document = document, url: URL = new URL(window.location.href)): Promise<ChapterContextReport | null> {
    const chapterId = this.extractChapterId(url);
    if (!chapterId) {
      return null;
    }

    // 1. Fetch complete gallery metadata from Hitomi JSON endpoint
    try {
      const metaUrl = `https://ltn.gold-usergeneratedcontent.net/galleries/${chapterId}.js`;
      const resp = await fetch(metaUrl);
      if (resp.ok) {
        const text = await resp.text();
        const jsonStr = text.replace(/^[^{]+/, '').replace(/;?\s*$/, '');
        const info = JSON.parse(jsonStr) as {
          title?: string;
          files?: Array<{ hash: string; name: string; width?: number; height?: number; haswebp?: number }>;
        };
        if (info && Array.isArray(info.files) && info.files.length > 0) {
          const rootPrefix = await this.resolveRootPrefix(doc);
          if (rootPrefix) {
            const pages: PageItem[] = info.files.map((file, idx) => {
              const hash = file.hash;
              let folder = '';
              if (hash && hash.length >= 3) {
                const m = /(..)(.)$/.exec(hash);
                if (m) {
                  folder = parseInt(m[2] + m[1], 16).toString(10);
                }
              }

              const subdomain = this.resolveAvifSubdomain(folder);
              const avifUrl = folder
                ? `https://${subdomain}.gold-usergeneratedcontent.net/${rootPrefix}${folder}/${hash}.avif`
                : `https://${subdomain}.gold-usergeneratedcontent.net/${rootPrefix}${hash}.avif`;

              return {
                page_number: idx + 1,
                image_url: avifUrl,
                status: 'discovered',
              };
            });

            const seriesTitle =
              info.title || (doc.title ? doc.title.replace(/\s*\|.*$/, '').trim() : `Hitomi Gallery ${chapterId}`);

            logger.info(`Extracted ${pages.length} pages via Hitomi metadata endpoint (id: ${chapterId})`, {
              chapterId,
              pagesCount: pages.length,
            });

            return {
              series_id: `hitomi:${chapterId}`,
              series_title: seriesTitle,
              source_domain: 'hitomi.la',
              chapter_id: chapterId,
              chapter_ordinal: 1.0,
              chapter_label: 'Gallery',
              chapter_url: url.href,
              total_pages: pages.length,
              pages,
            };
          }
          // Do NOT emit truncated URLs lacking rootPrefix! Fall through to DOM bridge or fallback
          logger.warn(`Hitomi rootPrefix unresolvable for gallery ${chapterId}; deferring extraction.`);
        }
      }
    } catch {
      // Fall through to DOM bridge / fallback
    }

    // 2. Try Main-World DOM bridge if metadata fetch failed
    const bridged = await queryHitomiMainWorldManifest(doc, 400);
    if (bridged && bridged.pages.length > 0) {
      logger.info(`Extracted ${bridged.pages.length} pages via Hitomi Main-World bridge (id: ${chapterId})`, {
        chapterId,
        pagesCount: bridged.pages.length,
      });

      return {
        series_id: `hitomi:${chapterId}`,
        series_title: bridged.title || `Hitomi Gallery ${chapterId}`,
        source_domain: 'hitomi.la',
        chapter_id: chapterId,
        chapter_ordinal: 1.0,
        chapter_label: 'Gallery',
        chapter_url: url.href,
        total_pages: bridged.pages.length,
        pages: bridged.pages.map((p) => ({
          ...p,
          image_url: this.normalizeImageUrl(p.image_url),
        })),
      };
    }

    // 3. Fallback: Extract currently loaded DOM images in #comicImages and #preload
    const domImages = Array.from(doc.querySelectorAll<HTMLImageElement>('#comicImages img, #preload img'));
    const pages: PageItem[] = [];

    for (let i = 0; i < domImages.length; i++) {
      const img = domImages[i];
      const rawSrc = img.currentSrc || img.src || img.getAttribute('data-src');
      if (rawSrc && !rawSrc.startsWith('data:image/svg')) {
        const src = this.normalizeImageUrl(rawSrc);
        pages.push({
          page_number: i + 1,
          image_url: src,
          status: 'discovered',
        });
      }
    }

    if (pages.length === 0) {
      return null;
    }

    const seriesTitle = doc.title ? doc.title.replace(/\s*\|.*$/, '').trim() : `Hitomi Gallery ${chapterId}`;

    logger.info(`Extracted ${pages.length} pages from Hitomi DOM container fallback`, {
      chapterId,
      pagesCount: pages.length,
    });

    return {
      series_id: `hitomi:${chapterId}`,
      series_title: seriesTitle || `Hitomi Gallery ${chapterId}`,
      source_domain: 'hitomi.la',
      chapter_id: chapterId,
      chapter_ordinal: 1.0,
      chapter_label: 'Gallery',
      chapter_url: url.href,
      total_pages: pages.length,
      pages,
    };
  }
}

export const hitomiAdapter = new HitomiAdapter();
siteAdapterRegistry.register(hitomiAdapter);

