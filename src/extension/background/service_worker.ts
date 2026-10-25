/**
 * InkShift Chromium Service Worker Entry Point.
 *
 * Ephemeral privileged background gateway coordinating CORS-privileged image fetches,
 * Web Crypto SHA-256 caching, FastAPI translation routing, and per-tab badge status.
 * Dispatches requests concurrently without artificial client-side throttling.
 */

import {
  isIPCMessage,
  createSuccessResponse,
  createErrorResponse,
  type IPCMessage,
  type IPCResponse,
} from '../shared/ipc_types';
import { BackendGateway, BackendGatewayError } from './backend_gateway';
import { fetchAndProcessImage, type ProcessedImageResult } from './cors_fetcher';
import { initNavigationTracker } from './navigation_tracker';
import { fetchMangaDexChapterManifest } from './adapters/mangadex_adapter';
import { TelemetryBatcher } from './telemetry_batcher';
import {
  createExtensionLogger,
  registerServiceWorkerTelemetryHandler,
} from '../shared/extension_logger';
import type { TranslationResponse, APIErrorDetail } from '../../types/contract';


// Default backend gateway instance pointing to local FastAPI server
export const defaultGateway = new BackendGateway('http://127.0.0.1:8000');

// Service worker telemetry batcher
export const telemetryBatcher = new TelemetryBatcher(defaultGateway);
registerServiceWorkerTelemetryHandler((entry) => telemetryBatcher.enqueue(entry));

export const logger = createExtensionLogger('SW');
logger.info('Service Worker initializing');

// In-flight translation task deduplication map keyed by SHA-256 hash (Singleflight pattern)
export const inFlightRequests = new Map<string, Promise<IPCResponse<TranslationResponse>>>();

// Initialize SPA web navigation tracker
initNavigationTracker();

/**
 * Pure handler function processing typed IPC messages.
 * Exported for clean, deterministic unit testing.
 */
export async function handleIPCMessage(
  msg: IPCMessage,
  sender?: chrome.runtime.MessageSender,
  gateway: BackendGateway = defaultGateway,
  imageFetcher: (url: string) => Promise<ProcessedImageResult> = fetchAndProcessImage,
  batcher: TelemetryBatcher = telemetryBatcher
): Promise<IPCResponse<any>> {
  switch (msg.type) {
    case 'CHECK_BACKEND_HEALTH': {
      try {
        const health = await gateway.checkHealth();
        return createSuccessResponse(health, msg.traceId);
      } catch (err: unknown) {
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'HEALTH_CHECK_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail, msg.traceId);
      }
    }

    case 'TRANSLATE_IMAGE': {
      const { traceId, imageIndex, imageUrl, engine, provider, model, translator, sourceLang, chapterUrl, forceRefresh } = msg.payload;
      logger.info(`[${traceId}] Translating image #${imageIndex}: ${imageUrl} (lang: ${sourceLang || 'auto'}, forceRefresh: ${Boolean(forceRefresh)})`, { traceId, imageIndex, imageUrl });

      try {
        // Step 1: Fetch binary image and compute SHA-256
        const processed = await imageFetcher(imageUrl);

        // Step 2: Singleflight Deduplication Check
        const dedupeKey = processed.sha256Hex || imageUrl;
        const existingPromise = inFlightRequests.get(dedupeKey);
        if (existingPromise) {
          logger.info(`[${traceId}] In-flight singleflight hit for key ${dedupeKey}`, { traceId, dedupeKey });
          return await existingPromise;
        }


        const translationTask = async (): Promise<IPCResponse<TranslationResponse>> => {
          // Step 3: Check SQLite translation cache on backend unless forceRefresh is true
          if (!forceRefresh) {
            const cached = await gateway.checkCache(processed.sha256Hex, engine);
            if (cached !== null) {
              logger.info(`[${traceId}] Cache HIT for hash ${processed.sha256Hex}`, { traceId, sha256Hex: processed.sha256Hex });
              return createSuccessResponse<TranslationResponse>(cached, traceId);
            }
          } else {
            logger.info(`[${traceId}] Force refresh active. Bypassing cache for hash ${processed.sha256Hex}`, { traceId, sha256Hex: processed.sha256Hex });
          }

          // Step 4: Dispatch directly to FastAPI translate endpoint
          logger.info(`[${traceId}] ${forceRefresh ? 'Force refreshing' : 'Cache MISS'}. Requesting translation...`, { traceId, sha256Hex: processed.sha256Hex });
          const translated = await gateway.requestTranslation({
            image: processed.base64,
            image_hash: processed.sha256Hex,
            engine,
            provider,
            model,
            translator,
            source_lang: sourceLang,
            chapter_url: chapterUrl,
            force_refresh: forceRefresh,
          });

          return createSuccessResponse<TranslationResponse>(translated, traceId);
        };

        const promise = translationTask();
        inFlightRequests.set(dedupeKey, promise);
        try {
          return await promise;
        } finally {
          inFlightRequests.delete(dedupeKey);
        }

      } catch (err: unknown) {
        logger.error(`[${traceId}] Translation error: ${err instanceof Error ? err.message : String(err)}`, { traceId });
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'IMAGE_TRANSLATION_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail, traceId);
      }
    }


    case 'UPDATE_TAB_BADGE': {
      const { translated, total } = msg.payload;
      const tabId = sender?.tab?.id;
      const badgeText =
        total > 0
          ? translated === total
            ? `${translated}`
            : `${translated}/${total}`
          : '';

      if (typeof chrome !== 'undefined' && chrome.action) {
        chrome.action.setBadgeText({
          text: badgeText,
          ...(tabId !== undefined ? { tabId } : {}),
        });
        chrome.action.setBadgeBackgroundColor({
          color: '#2563eb', // InkShift blue
          ...(tabId !== undefined ? { tabId } : {}),
        });
      }

      return createSuccessResponse({ badge: badgeText });
    }

    case 'SPA_NAVIGATION_DETECTED': {
      logger.info(`Route change detected: ${msg.payload.url}`, { url: msg.payload.url });
      return createSuccessResponse({ acknowledged: true });
    }

    case 'FORWARD_TELEMETRY': {
      batcher.enqueue(msg.payload);
      return createSuccessResponse({ acknowledged: true });
    }

    case 'FLUSH_TELEMETRY': {
      await batcher.flush();
      return createSuccessResponse({ acknowledged: true });
    }

    case 'REPORT_CHAPTER_CONTEXT': {
      try {
        const res = await gateway.reportContext(msg.payload);
        return createSuccessResponse(res);
      } catch (err: unknown) {
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'CONTEXT_REPORT_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail);
      }
    }

    case 'UPDATE_READING_PROGRESS': {
      try {
        const res = await gateway.updateReadingProgress(msg.payload);
        return createSuccessResponse(res);
      } catch (err: unknown) {
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'PROGRESS_UPDATE_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail);
      }
    }

    case 'FETCH_MANGADEX_MANIFEST': {
      try {
        const manifest = await fetchMangaDexChapterManifest(
          msg.payload.chapterUuid,
          msg.payload.preferredQuality
        );
        return createSuccessResponse(manifest);
      } catch (err: unknown) {
        const detail: APIErrorDetail = {
          code: 'MANGADEX_MANIFEST_FAILED',
          message: err instanceof Error ? err.message : String(err),
        };
        return createErrorResponse(detail);
      }
    }

    case 'FETCH_PROVIDER_MODELS': {
      try {
        const { provider, apiKey, baseUrl } = msg.payload;
        const result = await gateway.discoverModels(provider, apiKey, baseUrl);
        return createSuccessResponse(result);
      } catch (err: unknown) {
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'MODEL_DISCOVERY_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail);
      }
    }

    case 'GET_PROVIDER_SETTINGS': {
      try {
        const settings = await gateway.getProviderSettings();
        return createSuccessResponse(settings);
      } catch (err: unknown) {
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'SETTINGS_FETCH_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail);
      }
    }

    case 'SAVE_PROVIDER_SETTINGS': {
      try {
        const { provider, apiKey, baseUrl } = msg.payload;
        const result = await gateway.saveProviderSettings(provider, apiKey, baseUrl);
        return createSuccessResponse(result);
      } catch (err: unknown) {
        const detail: APIErrorDetail =
          err instanceof BackendGatewayError
            ? err.toDetail()
            : { code: 'SETTINGS_SAVE_FAILED', message: err instanceof Error ? err.message : String(err) };
        return createErrorResponse(detail);
      }
    }

    default:
      return createErrorResponse({ code: 'UNSUPPORTED_IPC_TYPE', message: 'Unknown IPC message type' });
  }
}



// Register top-level listener synchronously upon Service Worker startup
if (typeof chrome !== 'undefined' && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener(
    (
      message: unknown,
      sender: chrome.runtime.MessageSender,
      sendResponse: (response?: unknown) => void
    ) => {
      if (isIPCMessage(message)) {
        handleIPCMessage(message, sender, defaultGateway, fetchAndProcessImage, telemetryBatcher)
          .then((res) => sendResponse(res))
          .catch((err) => {
            logger.error(`Unhandled IPC exception: ${err instanceof Error ? err.message : String(err)}`);
            sendResponse(
              createErrorResponse({
                code: 'INTERNAL_SW_ERROR',
                message: err instanceof Error ? err.message : String(err),
              })
            );
          });
        return true; // CRITICAL: Holds the channel open for asynchronous reply
      }
      return false;
    }
  );
}
