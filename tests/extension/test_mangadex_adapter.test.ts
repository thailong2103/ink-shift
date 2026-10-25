import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchMangaDexChapterManifest,
  getAtHomeServer,
  getChapterMetadata,
  invalidateMangaDexServerCache,
} from '../../src/extension/background/adapters/mangadex_adapter';

describe('MangaDex API Adapter', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    invalidateMangaDexServerCache('ch-uuid-1');
  });

  const mockAtHomePayload = {
    result: 'ok',
    baseUrl: 'https://cmdxd98sb0x3yprd.mangadex.network',
    chapter: {
      hash: '1b582af9632833a9b0933346e9cb2bdf',
      data: ['1-x.jpg', '2-x.jpg', '3-x.jpg'],
      dataSaver: ['1-s.jpg', '2-s.jpg', '3-s.jpg'],
    },
  };

  const mockChapterMetadataPayload = {
    result: 'ok',
    data: {
      id: 'ch-uuid-1',
      attributes: {
        volume: '10',
        chapter: '102.5',
        title: 'Omake Extra',
        translatedLanguage: 'en',
      },
      relationships: [
        {
          id: 'series-frieren',
          type: 'manga',
          attributes: {
            title: {
              en: 'Frieren: Beyond Journey\'s End',
              ja: '葬送のフリーレン',
            },
          },
        },
      ],
    },
  };

  it('fetches and parses At-Home server response', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(mockAtHomePayload),
    });

    const res = await getAtHomeServer('ch-uuid-1', mockFetch as unknown as typeof fetch);
    expect(res.baseUrl).toBe('https://cmdxd98sb0x3yprd.mangadex.network');
    expect(res.chapter.hash).toBe('1b582af9632833a9b0933346e9cb2bdf');
    expect(res.chapter.data.length).toBe(3);
  });

  it('fetches chapter metadata and extracts series title and ordinal', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(mockChapterMetadataPayload),
    });

    const res = await getChapterMetadata('ch-uuid-1', mockFetch as unknown as typeof fetch);
    expect(res.seriesId).toBe('mangadex:series-frieren');
    expect(res.seriesTitle).toBe('Frieren: Beyond Journey\'s End');
    expect(res.ordinal).toBe(102.5);
    expect(res.label).toBe('Ch. 102.5 - Omake Extra');
  });

  it('constructs full chapter manifest with data quality by default', async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/at-home/server/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockAtHomePayload),
        });
      }
      if (url.includes('/chapter/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockChapterMetadataPayload),
        });
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    const manifest = await fetchMangaDexChapterManifest(
      'ch-uuid-1',
      'data',
      'https://mangadex.org/chapter/ch-uuid-1/1',
      mockFetch as unknown as typeof fetch
    );

    expect(manifest.series_id).toBe('mangadex:series-frieren');
    expect(manifest.chapter_id).toBe('ch-uuid-1');
    expect(manifest.total_pages).toBe(3);
    expect(manifest.pages.length).toBe(3);
    expect(manifest.pages[0].page_number).toBe(1);
    expect(manifest.pages[0].image_url).toBe(
      'https://cmdxd98sb0x3yprd.mangadex.network/data/1b582af9632833a9b0933346e9cb2bdf/1-x.jpg'
    );
  });

  it('constructs full chapter manifest with data-saver quality when requested', async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/at-home/server/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockAtHomePayload),
        });
      }
      if (url.includes('/chapter/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockChapterMetadataPayload),
        });
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    const manifest = await fetchMangaDexChapterManifest(
      'ch-uuid-1',
      'dataSaver',
      'https://mangadex.org/chapter/ch-uuid-1/1',
      mockFetch as unknown as typeof fetch
    );

    expect(manifest.pages[0].image_url).toBe(
      'https://cmdxd98sb0x3yprd.mangadex.network/data-saver/1b582af9632833a9b0933346e9cb2bdf/1-s.jpg'
    );
  });

  it('throws error when At-Home server request fails', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
    });

    await expect(
      getAtHomeServer('ch-uuid-error', mockFetch as unknown as typeof fetch)
    ).rejects.toThrow('HTTP 403');
  });

  it('falls back to data quality when preferredQuality is dataSaver but dataSaver is empty', async () => {
    const payloadWithoutDataSaver = {
      result: 'ok',
      baseUrl: 'https://cmdxd98sb0x3yprd.mangadex.network',
      chapter: {
        hash: 'hash-only-data',
        data: ['orig-1.png'],
        dataSaver: [],
      },
    };

    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/at-home/server/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(payloadWithoutDataSaver),
        });
      }
      if (url.includes('/chapter/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockChapterMetadataPayload),
        });
      }
      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    const manifest = await fetchMangaDexChapterManifest(
      'ch-uuid-no-saver',
      'dataSaver',
      'https://mangadex.org/chapter/ch-uuid-no-saver/1',
      mockFetch as unknown as typeof fetch
    );

    // Must use /data/ not /data-saver/ because dataSaver was empty
    expect(manifest.pages[0].image_url).toBe(
      'https://cmdxd98sb0x3yprd.mangadex.network/data/hash-only-data/orig-1.png'
    );
  });
});
