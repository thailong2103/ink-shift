/**
 * Privileged CORS-Bypass Image Fetcher & Binary Processing Pipeline.
 *
 * Runs inside the Manifest V3 background Service Worker utilizing privileged
 * host_permissions ("<all_urls>") to fetch arbitrary manga CDN images, calculate
 * SHA-256 content digests via Web Crypto, and serialize to Base64 without DOM.
 */

import { createExtensionLogger } from '../shared/extension_logger';

const logger = createExtensionLogger('Fetcher');

/**
 * Maximum permissible image file size in bytes (20 MB per SPEC-api-contract.md).
 */
export const MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024;

/**
 * Default network fetch timeout in milliseconds.
 */
export const DEFAULT_FETCH_TIMEOUT_MS = 25000;

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
  const timeoutMs = options?.timeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    let response = await fetch(imageUrl, {
      method: 'GET',
      signal: controller.signal,
    });

    // Fallback for MangaDex At-Home nodes returning 404 or transient 5xx:
    // Route directly to canonical MangaDex origin per MD@H client specification
    if (!response.ok && (response.status === 404 || response.status >= 500) && imageUrl.includes('.mangadex.network/')) {
      const fallbackUrl = imageUrl.replace(/https:\/\/[^/]+\.mangadex\.network/, 'https://uploads.mangadex.org');
      logger.warn(`MD@H node error HTTP ${response.status}. Retrying on canonical origin: ${fallbackUrl}`, {
        status: response.status,
        fallbackUrl,
      });
      response = await fetch(fallbackUrl, {
        method: 'GET',
        signal: controller.signal,
      });
    }

    if (!response.ok) {
      throw new Error(`Failed to fetch image: ${response.status} ${response.statusText}`);
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
