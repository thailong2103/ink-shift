/**
 * MangaDex v5 API and MangaDex@Home (MD@H) Protocol Adapter.
 *
 * Runs inside privileged Service Worker context to resolve full chapter
 * page manifests and build deterministic CDN image URLs.
 */

import type { ChapterContextReport, PageItem } from '../../shared/context_types';
import { createExtensionLogger } from '../../shared/extension_logger';

const logger = createExtensionLogger('MDX');

export interface MangaDexAtHomeServerResponse {
  result: string;
  baseUrl: string;
  chapter: {
    hash: string;
    data: string[];
    dataSaver: string[];
  };
}

export interface MangaDexChapterMetadataResponse {
  result: string;
  data: {
    id: string;
    attributes: {
      volume?: string | null;
      chapter?: string | null;
      title?: string | null;
      translatedLanguage: string;
    };
    relationships?: Array<{
      id: string;
      type: string;
      attributes?: {
        title?: Record<string, string>;
      };
    }>;
  };
}

// In-memory cache for At-Home server endpoints (15-minute token TTL)
interface CachedServerInfo {
  baseUrl: string;
  hash: string;
  data: string[];
  dataSaver: string[];
  expiresAt: number;
}

const serverCache = new Map<string, CachedServerInfo>();
const CACHE_TTL_MS = 14 * 60 * 1000; // 14 minutes (MangaDex guarantees 15 mins)

/**
 * Invalidate cached At-Home node URL for a chapter (e.g. upon HTTP 403 Forbidden).
 */
export function invalidateMangaDexServerCache(chapterUuid: string): void {
  logger.info(`Cache invalidated for chapter ${chapterUuid}`, { chapterUuid });
  serverCache.delete(chapterUuid);
}

/**
 * Fetch server info from MangaDex At-Home endpoint.
 */
export async function getAtHomeServer(
  chapterUuid: string,
  fetcher: typeof fetch = fetch
): Promise<MangaDexAtHomeServerResponse> {
  const cached = serverCache.get(chapterUuid);
  if (cached && Date.now() < cached.expiresAt) {
    logger.info(`At-Home cache HIT for chapter ${chapterUuid}`, { chapterUuid });
    return {
      result: 'ok',
      baseUrl: cached.baseUrl,
      chapter: {
        hash: cached.hash,
        data: cached.data,
        dataSaver: cached.dataSaver,
      },
    };
  }

  logger.info(`Fetching At-Home server node for chapter ${chapterUuid}`, { chapterUuid });
  const res = await fetcher(`https://api.mangadex.org/at-home/server/${encodeURIComponent(chapterUuid)}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch MangaDex At-Home server: HTTP ${res.status}`);
  }

  const data = (await res.json()) as MangaDexAtHomeServerResponse;
  if (data.result !== 'ok' || !data.baseUrl || !data.chapter) {
    throw new Error('Malformed MangaDex At-Home server response payload');
  }

  serverCache.set(chapterUuid, {
    baseUrl: data.baseUrl,
    hash: data.chapter.hash,
    data: data.chapter.data,
    dataSaver: data.chapter.dataSaver,
    expiresAt: Date.now() + CACHE_TTL_MS,
  });

  return data;
}

/**
 * Fetch chapter metadata and parent manga series title from MangaDex API.
 */
export async function getChapterMetadata(
  chapterUuid: string,
  fetcher: typeof fetch = fetch
): Promise<{ seriesId: string; seriesTitle: string; ordinal: number; label: string }> {
  const res = await fetcher(`https://api.mangadex.org/chapter/${encodeURIComponent(chapterUuid)}?includes[]=manga`);
  if (!res.ok) {
    throw new Error(`Failed to fetch MangaDex chapter metadata: HTTP ${res.status}`);
  }

  const json = (await res.json()) as MangaDexChapterMetadataResponse;
  const attr = json.data?.attributes;
  const rawChapter = attr?.chapter ?? '1';
  const ordinal = parseFloat(rawChapter) || 1.0;
  const label = rawChapter ? `Ch. ${rawChapter}${attr?.title ? ` - ${attr.title}` : ''}` : (attr?.title || 'Chapter');

  // Extract parent manga series title
  let seriesId = 'mangadex:unknown';
  let seriesTitle = 'Unknown Manga';

  const mangaRel = json.data?.relationships?.find((r) => r.type === 'manga');
  if (mangaRel) {
    seriesId = `mangadex:${mangaRel.id}`;
    if (mangaRel.attributes?.title) {
      const titles = mangaRel.attributes.title;
      seriesTitle = titles.en || titles.ja || titles['ja-ro'] || Object.values(titles)[0] || seriesTitle;
    }
  }

  return { seriesId, seriesTitle, ordinal, label };
}

/**
 * Construct full chapter manifest and ordered page URLs for MangaDex.
 */
export async function fetchMangaDexChapterManifest(
  chapterUuid: string,
  preferredQuality: 'data' | 'dataSaver' = 'data',
  chapterUrl?: string,
  fetcher: typeof fetch = fetch
): Promise<ChapterContextReport> {
  const [serverInfo, metadata] = await Promise.all([
    getAtHomeServer(chapterUuid, fetcher),
    getChapterMetadata(chapterUuid, fetcher).catch(() => ({
      seriesId: 'mangadex:series',
      seriesTitle: 'MangaDex Manga',
      ordinal: 1.0,
      label: 'Chapter',
    })),
  ]);

  const { baseUrl, chapter } = serverInfo;
  const hasDataSaver = Boolean(chapter.dataSaver && chapter.dataSaver.length > 0);
  const qualityPath = preferredQuality === 'dataSaver' && hasDataSaver ? 'data-saver' : 'data';
  const fileList = qualityPath === 'data-saver' && chapter.dataSaver ? chapter.dataSaver : chapter.data;

  const pages: PageItem[] = fileList.map((filename, idx) => ({
    page_number: idx + 1,
    image_url: `${baseUrl}/${qualityPath}/${chapter.hash}/${filename}`,
    status: 'discovered',
  }));

  logger.info(
    `Resolved manifest for chapter ${chapterUuid}: ${pages.length} pages (${preferredQuality})`,
    { chapterUuid, pagesCount: pages.length, preferredQuality }
  );

  return {
    series_id: metadata.seriesId,
    series_title: metadata.seriesTitle,
    source_domain: 'mangadex.org',
    chapter_id: chapterUuid,
    chapter_ordinal: metadata.ordinal,
    chapter_label: metadata.label,
    chapter_url: chapterUrl || `https://mangadex.org/chapter/${chapterUuid}/1`,
    total_pages: pages.length,
    pages,
  };
}
