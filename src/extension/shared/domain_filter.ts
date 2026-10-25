/**
 * InkShift Unified Domain Whitelist & Blacklist Filter.
 *
 * Fast-path domain gating ($<0.05ms) preventing unwarranted DOM scans,
 * translation calls, and resource consumption on non-manga websites.
 */

export interface DomainFilterSettings {
  blacklist: string[];
  whitelist: string[];
}

export const STORAGE_KEY_DOMAIN_FILTER = 'inkshift_domain_filter';

export const DEFAULT_PRESEEDED_BLACKLIST: string[] = [
  // Search engines & Portals
  'google.com',
  'bing.com',
  'duckduckgo.com',
  'yahoo.com',
  'baidu.com',
  'wikipedia.org',

  // Social media & Video
  'youtube.com',
  'facebook.com',
  'twitter.com',
  'x.com',
  'instagram.com',
  'tiktok.com',
  'reddit.com',
  'linkedin.com',
  'twitch.tv',
  'discord.com',

  // E-commerce
  'amazon.com',
  'ebay.com',
  'aliexpress.com',
  'shopee.vn',
  'lazada.vn',
  'tiki.vn',

  // News & Media
  'vnexpress.net',
  'dantri.com.vn',
  'tuoitre.vn',
  'thanhnien.vn',
  'bbc.com',
  'cnn.com',
  'medium.com',

  // Tech, Developer & Productivity
  'github.com',
  'gitlab.com',
  'stackoverflow.com',
  'npmjs.com',
  'notion.so',
  'figma.com',
  'docs.google.com',
  'canva.com',
];

/**
 * Normalizes a hostname string, removing protocol, port, or leading/trailing slashes.
 */
export function normalizeHostname(input: string): string {
  if (!input) return '';
  let host = input.trim().toLowerCase();

  // If a full URL is passed, parse the hostname
  if (host.includes('://')) {
    try {
      const url = new URL(host);
      host = url.hostname;
    } catch {
      // Fallback manual regex strip
      host = host.replace(/^[a-z]+:\/\//i, '').split('/')[0];
    }
  } else {
    // Strip possible path or port
    host = host.split('/')[0].split(':')[0];
  }

  // Strip leading www. if needed, or keep for exact matching
  return host.replace(/^\.+|\.+$/g, '');
}

/**
 * Checks if a candidate hostname matches or is a subdomain of target domain.
 * e.g., "m.facebook.com" matches "facebook.com", "sub.news.vnexpress.net" matches "vnexpress.net".
 */
export function matchesDomain(hostname: string, targetDomain: string): boolean {
  const normHost = normalizeHostname(hostname);
  const normTarget = normalizeHostname(targetDomain);

  if (!normHost || !normTarget) {
    return false;
  }

  if (normHost === normTarget) {
    return true;
  }

  return normHost.endsWith('.' + normTarget);
}

/**
 * Determines whether a domain is allowed to run reader detection and translation.
 * - 'whitelisted': User explicitly forced translation on this domain (overrides blacklist).
 * - 'blacklisted': Domain matches blacklist (pre-seeded or user-added) -> immediate fast skip.
 * - 'allowed': Domain is neither whitelisted nor blacklisted -> proceeds to heuristic detection.
 */
export function isDomainAllowed(
  hostname: string,
  settings?: DomainFilterSettings
): 'allowed' | 'blacklisted' | 'whitelisted' {
  const normHost = normalizeHostname(hostname);
  if (!normHost) {
    return 'allowed';
  }

  const whitelist = settings?.whitelist ?? [];
  if (whitelist.some((w) => matchesDomain(normHost, w))) {
    return 'whitelisted';
  }

  const blacklist = settings?.blacklist ?? DEFAULT_PRESEEDED_BLACKLIST;
  if (blacklist.some((b) => matchesDomain(normHost, b))) {
    return 'blacklisted';
  }

  return 'allowed';
}

/**
 * Loads domain filter settings from chrome.storage.local, initializing with pre-seeded values if empty.
 */
export async function loadDomainFilterSettings(): Promise<DomainFilterSettings> {
  if (typeof chrome !== 'undefined' && chrome.storage?.local) {
    try {
      const data = await chrome.storage.local.get([STORAGE_KEY_DOMAIN_FILTER]);
      const stored = data?.[STORAGE_KEY_DOMAIN_FILTER] as DomainFilterSettings | undefined;
      if (stored && Array.isArray(stored.blacklist) && Array.isArray(stored.whitelist)) {
        return {
          blacklist: Array.from(new Set(stored.blacklist.map(normalizeHostname).filter(Boolean))),
          whitelist: Array.from(new Set(stored.whitelist.map(normalizeHostname).filter(Boolean))),
        };
      }
    } catch {
      // Fall through to default
    }
  }

  return {
    blacklist: [...DEFAULT_PRESEEDED_BLACKLIST],
    whitelist: [],
  };
}

/**
 * Saves domain filter settings into chrome.storage.local.
 */
export async function saveDomainFilterSettings(settings: DomainFilterSettings): Promise<void> {
  const cleanSettings: DomainFilterSettings = {
    blacklist: Array.from(new Set(settings.blacklist.map(normalizeHostname).filter(Boolean))),
    whitelist: Array.from(new Set(settings.whitelist.map(normalizeHostname).filter(Boolean))),
  };

  if (typeof chrome !== 'undefined' && chrome.storage?.local) {
    await chrome.storage.local.set({ [STORAGE_KEY_DOMAIN_FILTER]: cleanSettings });
  }
}

/**
 * Resets domain filter settings to factory default (pre-seeded blacklist, empty whitelist).
 */
export async function resetToDefaultFilterSettings(): Promise<DomainFilterSettings> {
  const defaultSettings: DomainFilterSettings = {
    blacklist: [...DEFAULT_PRESEEDED_BLACKLIST],
    whitelist: [],
  };
  await saveDomainFilterSettings(defaultSettings);
  return defaultSettings;
}
