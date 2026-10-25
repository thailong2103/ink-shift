/**
 * Strongly-typed IPC Contracts for Chromium Extension Communication.
 *
 * Defines message envelopes and response shapes exchanged across
 * Content Script <-> Service Worker <-> Popup boundaries, linking
 * with canonical types in src/types/contract.ts.
 */

import type {
  TranslationResponse,
  APIErrorDetail,
  EngineMode,
} from '../../types/contract';
import type {
  ChapterContextReport,
  ProgressUpdateRequest,
} from './context_types';
import type { TelemetryLogEntry } from './telemetry_types';


/**
 * Payload required for in-page manga image translation request.
 */
export interface TranslateImagePayload {
  /**
   * Deterministic correlation trace identifier for request-response matching.
   */
  traceId: string;
  /**
   * 0-based page/image index within the current reader chapter.
   */
  imageIndex: number;
  /**
   * Absolute URL of the manga page image to fetch and translate.
   */
  imageUrl: string;
  /**
   * Rendered DOM client width in physical pixels.
   */
  clientWidth: number;
  /**
   * Rendered DOM client height in physical pixels.
   */
  clientHeight: number;
  /**
   * Optional engine override ('cloud' | 'local' | 'mock' | 'auto').
   */
  engine?: EngineMode;
  /**
   * Optional cloud provider override ('gemini' | 'openai' | 'xkiro').
   */
  provider?: string;
  /**
   * Optional local text translator override ('google-free' | 'llm-gemini' | 'llm-qwen' | 'llm-text').
   */
  translator?: string;
  /**
   * Optional LLM model override (e.g. 'gemini-2.5-flash', 'gpt-4o', 'claude-3-5-sonnet').
   */
  model?: string;
  /**
   * Optional source language override ('auto' | 'ja' | 'en' | 'ko' | 'zh').
   */
  sourceLang?: string;
  /**
   * Optional chapter URL or page URL context for chapter-level language caching.
   */
  chapterUrl?: string;
  /**
   * Optional flag to force cache bypass and re-translate fresh.
   */
  forceRefresh?: boolean;
}

export interface DiscoveredModel {
  id: string;
  display_name: string;
  supports_vision: boolean;
}

export interface DiscoveredModelsData {
  success: true;
  provider: string;
  models: DiscoveredModel[];
}

export interface ProviderSettingStatus {
  configured: boolean;
  masked_key?: string | null;
  base_url?: string | null;
}

export interface ProviderSettingsData {
  success: true;
  providers: Record<string, ProviderSettingStatus>;
}

export interface SaveProviderSettingsData {
  success: true;
  provider: string;
  status: ProviderSettingStatus;
}

/**
 * Discriminated union of all messages transmitted via chrome.runtime.sendMessage.
 */
export type IPCMessage =
  | { type: 'CHECK_BACKEND_HEALTH'; traceId?: string }
  | { type: 'TRANSLATE_IMAGE'; payload: TranslateImagePayload }
  | { type: 'SPA_NAVIGATION_DETECTED'; payload: { url: string } }
  | { type: 'UPDATE_TAB_BADGE'; payload: { translated: number; total: number } }
  | { type: 'REPORT_CHAPTER_CONTEXT'; payload: ChapterContextReport }
  | { type: 'UPDATE_READING_PROGRESS'; payload: ProgressUpdateRequest }
  | { type: 'FETCH_MANGADEX_MANIFEST'; payload: { chapterUuid: string; preferredQuality?: 'data' | 'dataSaver' } }
  | { type: 'FORWARD_TELEMETRY'; payload: TelemetryLogEntry }
  | { type: 'FLUSH_TELEMETRY' }
  | { type: 'RESCAN_PAGE' }
  | { type: 'GET_PAGE_READER_STATUS' }
  | {
      type: 'FETCH_PROVIDER_MODELS';
      payload: {
        provider: 'google' | 'openai' | 'anthropic' | 'custom' | string;
        apiKey?: string;
        baseUrl?: string;
      };
    }
  | { type: 'GET_PROVIDER_SETTINGS' }
  | {
      type: 'SAVE_PROVIDER_SETTINGS';
      payload: {
        provider: 'google' | 'openai' | 'anthropic' | 'custom' | string;
        apiKey?: string;
        baseUrl?: string;
      };
    };


export interface PageReaderStatusData {
  hostname: string;
  domainStatus: 'allowed' | 'blacklisted' | 'whitelisted';
  isReaderPage: boolean;
  confidence: number;
  layoutType: string;
  chapterMeta?: {
    seriesSlug: string;
    chapterNumber?: number;
    sourceDomain: string;
    chapterUrl: string;
  };
}

/**
 * Specific success envelope.
 */
export interface IPCSuccessResponse<T = unknown> {
  success: true;
  traceId?: string;
  data: T;
}

/**
 * Specific error envelope.
 */
export interface IPCErrorResponse {
  success: false;
  traceId?: string;
  error: APIErrorDetail;
}

/**
 * Standardized typed envelope returned across IPC message handlers.
 */
export type IPCResponse<T = unknown> = IPCSuccessResponse<T> | IPCErrorResponse;

/**
 * Specific typed response returned when TRANSLATE_IMAGE resolves.
 */
export type TranslateImageResponse = IPCResponse<TranslationResponse>;

/**
 * Specific typed response returned when CHECK_BACKEND_HEALTH resolves.
 */
export type BackendHealthResponse = IPCResponse<{
  status: 'healthy' | 'degraded';
  engine: string;
  version: string;
}>;

/**
 * Type guard verifying if an unknown value satisfies the IPCMessage structure.
 */
export function isIPCMessage(value: unknown): value is IPCMessage {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  const msg = value as Record<string, unknown>;
  if (typeof msg.type !== 'string') {
    return false;
  }

  switch (msg.type) {
    case 'CHECK_BACKEND_HEALTH':
      return msg.traceId === undefined || typeof msg.traceId === 'string';

    case 'TRANSLATE_IMAGE': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return (
        typeof p === 'object' &&
        p !== null &&
        typeof p.traceId === 'string' &&
        typeof p.imageIndex === 'number' &&
        typeof p.imageUrl === 'string' &&
        typeof p.clientWidth === 'number' &&
        typeof p.clientHeight === 'number'
      );
    }

    case 'SPA_NAVIGATION_DETECTED': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return typeof p === 'object' && p !== null && typeof p.url === 'string';
    }

    case 'UPDATE_TAB_BADGE': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return (
        typeof p === 'object' &&
        p !== null &&
        typeof p.translated === 'number' &&
        typeof p.total === 'number'
      );
    }

    case 'REPORT_CHAPTER_CONTEXT': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return typeof p === 'object' && p !== null && typeof p.chapter_id === 'string' && Array.isArray(p.pages);
    }

    case 'UPDATE_READING_PROGRESS': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return typeof p === 'object' && p !== null && typeof p.chapter_id === 'string' && typeof p.page_number === 'number';
    }

    case 'FETCH_MANGADEX_MANIFEST': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return typeof p === 'object' && p !== null && typeof p.chapterUuid === 'string';
    }

    case 'FORWARD_TELEMETRY': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return (
        typeof p === 'object' &&
        p !== null &&
        typeof p.timestamp_ms === 'number' &&
        typeof p.level === 'string' &&
        typeof p.module === 'string' &&
        typeof p.message === 'string'
      );
    }

    case 'FLUSH_TELEMETRY':
    case 'GET_PAGE_READER_STATUS':
    case 'RESCAN_PAGE':
    case 'GET_PROVIDER_SETTINGS':
      return true;

    case 'FETCH_PROVIDER_MODELS': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return typeof p === 'object' && p !== null && typeof p.provider === 'string';
    }

    case 'SAVE_PROVIDER_SETTINGS': {
      const p = msg.payload as Record<string, unknown> | undefined;
      return typeof p === 'object' && p !== null && typeof p.provider === 'string';
    }

    default:
      return false;
  }
}


/**
 * Type guard verifying if an unknown value satisfies the IPCResponse structure.
 */
export function isIPCResponse<T = unknown>(value: unknown): value is IPCResponse<T> {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  const res = value as Record<string, unknown>;
  if (typeof res.success !== 'boolean') {
    return false;
  }

  if (res.traceId !== undefined && typeof res.traceId !== 'string') {
    return false;
  }

  if (res.success === true) {
    return 'data' in res;
  }

  if (res.success === false) {
    const err = res.error as Record<string, unknown> | undefined;
    return (
      typeof err === 'object' &&
      err !== null &&
      typeof err.code === 'string' &&
      typeof err.message === 'string'
    );
  }

  return false;
}

/**
 * Helper to construct a typed success response envelope.
 */
export function createSuccessResponse<T>(data: T, traceId?: string): IPCSuccessResponse<T> {
  return {
    success: true,
    ...(traceId ? { traceId } : {}),
    data,
  };
}

/**
 * Helper to construct a typed error response envelope.
 */
export function createErrorResponse(error: APIErrorDetail, traceId?: string): IPCErrorResponse {
  return {
    success: false,
    ...(traceId ? { traceId } : {}),
    error,
  };
}
