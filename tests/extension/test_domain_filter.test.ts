import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  normalizeHostname,
  matchesDomain,
  isDomainAllowed,
  loadDomainFilterSettings,
  saveDomainFilterSettings,
  resetToDefaultFilterSettings,
  DEFAULT_PRESEEDED_BLACKLIST,
  STORAGE_KEY_DOMAIN_FILTER,
  type DomainFilterSettings,
} from '../../src/extension/shared/domain_filter';

describe('Domain Filter Engine', () => {
  describe('normalizeHostname', () => {
    it('normalizes full URLs to lower-cased hostnames', () => {
      expect(normalizeHostname('https://sub.Example.com/reading/chap-1?page=2')).toBe('sub.example.com');
      expect(normalizeHostname('http://manga.site.vn:8080/path')).toBe('manga.site.vn');
    });

    it('handles raw hostnames with trailing slashes or ports', () => {
      expect(normalizeHostname('vnexpress.net/')).toBe('vnexpress.net');
      expect(normalizeHostname('localhost:3000')).toBe('localhost');
      expect(normalizeHostname('   YouTube.COM   ')).toBe('youtube.com');
    });

    it('returns empty string on empty input', () => {
      expect(normalizeHostname('')).toBe('');
    });
  });

  describe('matchesDomain', () => {
    it('matches exact domain', () => {
      expect(matchesDomain('google.com', 'google.com')).toBe(true);
      expect(matchesDomain('https://google.com', 'google.com')).toBe(true);
    });

    it('matches subdomains correctly', () => {
      expect(matchesDomain('m.facebook.com', 'facebook.com')).toBe(true);
      expect(matchesDomain('touch.vnexpress.net', 'vnexpress.net')).toBe(true);
      expect(matchesDomain('sub.level2.github.com', 'github.com')).toBe(true);
    });

    it('does not false-match similar names', () => {
      expect(matchesDomain('fakebook.com', 'facebook.com')).toBe(false);
      expect(matchesDomain('notgoogle.com', 'google.com')).toBe(false);
      expect(matchesDomain('myvnexpress.net', 'vnexpress.net')).toBe(false);
    });
  });

  describe('isDomainAllowed', () => {
    it('rejects pre-seeded blacklist domains by default', () => {
      expect(isDomainAllowed('google.com')).toBe('blacklisted');
      expect(isDomainAllowed('www.facebook.com')).toBe('blacklisted');
      expect(isDomainAllowed('vnexpress.net')).toBe('blacklisted');
      expect(isDomainAllowed('shopee.vn')).toBe('blacklisted');
    });

    it('allows unknown manga reading domains by default', () => {
      expect(isDomainAllowed('nettruyen.org')).toBe('allowed');
      expect(isDomainAllowed('mangadex.org')).toBe('allowed');
      expect(isDomainAllowed('cuutruyen.net')).toBe('allowed');
    });

    it('prioritizes whitelist over blacklist', () => {
      const settings: DomainFilterSettings = {
        blacklist: ['reddit.com', 'facebook.com'],
        whitelist: ['reddit.com'],
      };
      expect(isDomainAllowed('reddit.com', settings)).toBe('whitelisted');
      expect(isDomainAllowed('old.reddit.com', settings)).toBe('whitelisted');
      expect(isDomainAllowed('facebook.com', settings)).toBe('blacklisted');
    });

    it('respects user-defined blacklist', () => {
      const settings: DomainFilterSettings = {
        blacklist: ['my-internal-wiki.com'],
        whitelist: [],
      };
      expect(isDomainAllowed('my-internal-wiki.com', settings)).toBe('blacklisted');
      expect(isDomainAllowed('google.com', settings)).toBe('allowed'); // Overridden custom settings
    });
  });

  describe('Storage Helpers (chrome.storage.local)', () => {
    let mockStorage: Record<string, any> = {};

    beforeEach(() => {
      mockStorage = {};
      (globalThis as any).chrome = {
        storage: {
          local: {
            get: vi.fn(async (keys: string[]) => {
              const res: Record<string, any> = {};
              for (const k of keys) {
                if (k in mockStorage) {
                  res[k] = mockStorage[k];
                }
              }
              return res;
            }),
            set: vi.fn(async (items: Record<string, any>) => {
              Object.assign(mockStorage, items);
            }),
          },
        },
      };
    });

    it('loads default pre-seeded settings when storage is empty', async () => {
      const settings = await loadDomainFilterSettings();
      expect(settings.blacklist).toEqual(DEFAULT_PRESEEDED_BLACKLIST);
      expect(settings.whitelist).toEqual([]);
    });

    it('saves and loads customized settings', async () => {
      const custom: DomainFilterSettings = {
        blacklist: ['site1.com', 'site2.com'],
        whitelist: ['mangadex.org'],
      };
      await saveDomainFilterSettings(custom);
      expect(mockStorage[STORAGE_KEY_DOMAIN_FILTER]).toEqual(custom);

      const loaded = await loadDomainFilterSettings();
      expect(loaded).toEqual(custom);
    });

    it('resets to factory default settings', async () => {
      mockStorage[STORAGE_KEY_DOMAIN_FILTER] = {
        blacklist: ['custom.com'],
        whitelist: ['other.com'],
      };

      const reset = await resetToDefaultFilterSettings();
      expect(reset.blacklist).toEqual(DEFAULT_PRESEEDED_BLACKLIST);
      expect(reset.whitelist).toEqual([]);
      expect(mockStorage[STORAGE_KEY_DOMAIN_FILTER].blacklist).toEqual(DEFAULT_PRESEEDED_BLACKLIST);
    });
  });
});
