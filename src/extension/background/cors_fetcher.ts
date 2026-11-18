/**
 * Privileged CORS-Bypass Image Fetcher & Binary Processing Pipeline.
 *
 * Runs inside the Manifest V3 background Service Worker utilizing privileged
 * host_permissions ("<all_urls>") to fetch arbitrary manga CDN images, calculate
 * SHA-256 content digests via Web Crypto, and serialize to Base64 without DOM.
 */

import { createExtensionLogger } from '../shared/extension_logger';
import { siteAdapterRegistry } from '../adapters';

const logger = createExtensionLogger('Fetcher');

/**
 * Maximum permissible image file size in bytes (20 MB per SPEC-api-contract.md).
 */
export const MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024;

/**
 * Default network fetch timeout in milliseconds.
 * Lowered to 8,000ms to fail fast and trigger CDN origin failover on stalls.
 */
export const DEFAULT_FETCH_TIMEOUT_MS = 8000;

const HITOMI_REFERER_RULE_ID = 9101;
let hitomiRefererRulePromise: Promise<void> | null = null;

/**
 * Registers the Manifest V3 declarativeNetRequest rule attaching Hitomi's required
 * Referer header on outgoing CDN requests (gold-usergeneratedcontent.net).
 * Without this header, Hitomi CDN nodes reject extension Service Worker fetches with HTTP 404.
 */
export function ensureHitomiRefererRule(): Promise<void> {
  if (
    typeof chrome === 'undefined' ||
    !chrome.declarativeNetRequest ||
    typeof chrome.declarativeNetRequest.updateDynamicRules !== 'function'
  ) {
    return Promise.resolve();
  }

  if (hitomiRefererRulePromise) {
    return hitomiRefererRulePromise;
  }

  const dnr = chrome.declarativeNetRequest;
  const modifyHeadersType = (dnr.RuleActionType?.MODIFY_HEADERS ?? 'modifyHeaders') as chrome.declarativeNetRequest.RuleActionType;
  const setOperation = (dnr.HeaderOperation?.SET ?? 'set') as chrome.declarativeNetRequest.HeaderOperation;
  const resourceTypes = (
    dnr.ResourceType
      ? [
          dnr.ResourceType.XMLHTTPREQUEST,
          dnr.ResourceType.IMAGE,
          dnr.ResourceType.OTHER,
          dnr.ResourceType.SCRIPT,
        ]
      : ['xmlhttprequest', 'image', 'other', 'script']
  ) as chrome.declarativeNetRequest.ResourceType[];

  hitomiRefererRulePromise = Promise.resolve(
    dnr.updateDynamicRules({
      removeRuleIds: [HITOMI_REFERER_RULE_ID],
      addRules: [
        {
          id: HITOMI_REFERER_RULE_ID,
          priority: 1,
          action: {
            type: modifyHeadersType,
            requestHeaders: [
              {
                header: 'Referer',
                operation: setOperation,
                value: 'https://hitomi.la/',
              },
            ],
          },
          condition: {
            urlFilter: '||gold-usergeneratedcontent.net/',
            resourceTypes,
          },
        },
      ],
    })
  ).catch((err: unknown) => {
    hitomiRefererRulePromise = null;
    logger.warn(
      `Failed to register Hitomi Referer DNR rule: ${err instanceof Error ? err.message : String(err)}`
    );
  });

  return hitomiRefererRulePromise;
}

export interface ProcessedImageResult {
  buffer: ArrayBuffer;
  sha256Hex: string;
  base64: string;
  mimeType: string;
  sizeBytes: number;
}

/**
 * Computes a lowercase hex SHA-256 digest of an ArrayBuffer using Web Crypto.
 */
export async function computeSha256Hex(buffer: ArrayBuffer): Promise<string> {
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * Encodes a Uint8Array into a standard Base64 string without DOM dependencies.
 * Employs ECMAScript Uint8Array.prototype.toBase64 if available, otherwise
 * uses chunked String.fromCharCode to prevent call stack overflow on large images.
 */
export function uint8ArrayToBase64(bytes: Uint8Array): string {
  // Check for native ECMAScript Uint8Array toBase64 support (Chromium 126+)
  const maybeNative = bytes as Uint8Array & { toBase64?: () => string };
  if (typeof maybeNative.toBase64 === 'function') {
    return maybeNative.toBase64();
  }

  // 32 KB chunking to stay well within JS engine argument limits
  const CHUNK_SIZE = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK_SIZE) {
    const chunk = bytes.subarray(i, i + CHUNK_SIZE);
    binary += String.fromCharCode.apply(null, chunk as unknown as number[]);
  }

  // btoa is globally available in modern Service Workers and Node 18+
  return btoa(binary);
}

/**
 * Fetches an image from a remote URL, validates size constraints,
 * computes SHA-256, and returns Base64 encoded payload.
 */
export async function fetchAndProcessImage(
  imageUrl: string,
  options?: { timeoutMs?: number }
): Promise<ProcessedImageResult> {
  // Direct fast path for inline Data URLs (e.g. Base64 canvas serializations)
  if (imageUrl.startsWith('data:')) {
    const commaIdx = imageUrl.indexOf(',');
    if (commaIdx !== -1) {
      const meta = imageUrl.substring(0, commaIdx);
      const rawBase64 = imageUrl.substring(commaIdx + 1);
      const mimeMatch = meta.match(/data:([^;]+)/);
      const mimeType = mimeMatch ? mimeMatch[1] : 'image/jpeg';
      const binary = atob(rawBase64);
      const len = binary.length;
      if (len > MAX_IMAGE_SIZE_BYTES) {
        throw new Error(
          `Image size exceeds maximum limit of 20MB: got ${(len / (1024 * 1024)).toFixed(2)}MB`
        );
      }
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      const buffer = bytes.buffer;
      const sha256Hex = await computeSha256Hex(buffer);
      return {
        buffer,
        sha256Hex,
        base64: rawBase64,
        mimeType,
        sizeBytes: len,
      };
    }
  }

  const timeoutMs = options?.timeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS;
  const targetUrl = siteAdapterRegistry.normalizeImageUrl(imageUrl);
  if (targetUrl !== imageUrl) {
    logger.info(`Normalized image URL via site adapter: ${imageUrl} -> ${targetUrl}`, {
      originalUrl: imageUrl,
      normalizedUrl: targetUrl,
    });
  }

  if (
    targetUrl.includes('.gold-usergeneratedcontent.net/') ||
    imageUrl.includes('.gold-usergeneratedcontent.net/')
  ) {
    await ensureHitomiRefererRule();
  }

  const MAX_ADAPTER_FALLBACKS = 4;
  const visitedUrls = new Set<string>([targetUrl]);
  let fallbackAttempts = 0;

  let currentUrl = targetUrl;
  let response: Response | null = null;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    try {
      response = await fetch(currentUrl, {
        method: 'GET',
        signal: controller.signal,
      });
    } catch (fetchErr) {
      // Catch connection timeout, abort, or network drop (status === 0)
      const fallbackUrl = siteAdapterRegistry.resolveFallbackUrl(currentUrl, 0);
      if (fallbackUrl && !visitedUrls.has(fallbackUrl) && fallbackAttempts < MAX_ADAPTER_FALLBACKS) {
        visitedUrls.add(fallbackUrl);
        fallbackAttempts++;
        logger.warn(
          `Primary fetch failed (${fetchErr instanceof Error ? fetchErr.message : String(fetchErr)}). Retrying on fallback origin: ${fallbackUrl}`,
          { fallbackUrl, attempt: fallbackAttempts }
        );
        currentUrl = fallbackUrl;
        clearTimeout(timeoutId);
        const fallbackController = new AbortController();
        const fallbackTimeoutId = setTimeout(() => fallbackController.abort(), timeoutMs);
        try {
          response = await fetch(currentUrl, {
            method: 'GET',
            signal: fallbackController.signal,
          });
        } finally {
          clearTimeout(fallbackTimeoutId);
        }
      } else {
        throw fetchErr;
      }
    }

    // Delegate CDN fallback resolution to registered site adapters if response is not OK (404/5xx)
    while (response && !response.ok && fallbackAttempts < MAX_ADAPTER_FALLBACKS) {
      const fallbackUrl = siteAdapterRegistry.resolveFallbackUrl(currentUrl, response.status);
      if (fallbackUrl && !visitedUrls.has(fallbackUrl)) {
        visitedUrls.add(fallbackUrl);
        fallbackAttempts++;
        logger.warn(
          `Site adapter fallback for HTTP ${response.status}. Retrying on fallback origin: ${fallbackUrl} (attempt ${fallbackAttempts}/${MAX_ADAPTER_FALLBACKS})`,
          {
            status: response.status,
            fallbackUrl,
            attempt: fallbackAttempts,
          }
        );
        currentUrl = fallbackUrl;
        clearTimeout(timeoutId);
        const fallbackController = new AbortController();
        const fallbackTimeoutId = setTimeout(() => fallbackController.abort(), timeoutMs);
        try {
          response = await fetch(currentUrl, {
            method: 'GET',
            signal: fallbackController.signal,
          });
        } finally {
          clearTimeout(fallbackTimeoutId);
        }
      } else {
        if (fallbackUrl && visitedUrls.has(fallbackUrl)) {
          logger.warn(
            `Site adapter fallback detected cyclic URL loop: ${fallbackUrl}. Terminating retry loop.`,
            { fallbackUrl }
          );
        }
        break;
      }
    }

    if (!response || !response.ok) {
      throw new Error(`Failed to fetch image: ${response ? `${response.status} ${response.statusText}` : 'No response'}`);
    }

    const buffer = await response.arrayBuffer();
    if (buffer.byteLength > MAX_IMAGE_SIZE_BYTES) {
      throw new Error(
        `Image size exceeds maximum limit of 20MB: got ${(buffer.byteLength / (1024 * 1024)).toFixed(2)}MB`
      );
    }

    const mimeType = response.headers.get('content-type') || 'image/jpeg';
    const sha256Hex = await computeSha256Hex(buffer);
    const bytes = new Uint8Array(buffer);
    const base64 = uint8ArrayToBase64(bytes);

    return {
      buffer,
      sha256Hex,
      base64,
      mimeType,
      sizeBytes: buffer.byteLength,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}
