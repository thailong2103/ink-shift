/**
 * Privileged Backend API Gateway & FastAPI Client.
 *
 * Runs inside the Service Worker to communicate with local FastAPI backend
 * endpoints (/api/v1/health, /api/v1/cache, /api/v1/translate), featuring
 * header telemetry and bounded exponential backoff retry for transient faults.
 */

import type {
  TranslationRequest,
  TranslationResponse,
  APIErrorDetail,
} from '../../types/contract';
import type {
  ChapterContextReport,
  ChapterPagesResponse,
  ContextReportResponse,
  ProgressUpdateRequest,
  ProgressUpdateResponse,
} from '../shared/context_types';
import type {
  DiscoveredModelsData,
  ProviderSettingsData,
  SaveProviderSettingsData,
} from '../shared/ipc_types';
import type { TelemetryBatchRequest } from '../shared/telemetry_types';
import { formatLocalTimestamp } from '../shared/extension_logger';


export interface GatewayOptions {
  maxRetries?: number;
  initialRetryDelayMs?: number;
  maxRetryDelayMs?: number;
  timeoutMs?: number;
}

export class BackendGatewayError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status?: number,
    public readonly details?: unknown
  ) {
    super(message);
    this.name = 'BackendGatewayError';
  }

  toDetail(): APIErrorDetail {
    return {
      code: this.code,
      message: this.message,
      ...(this.details !== undefined ? { details: this.details } : {}),
    };
  }
}

export class BackendGateway {
  private readonly baseUrl: string;
  private readonly maxRetries: number;
  private readonly initialRetryDelayMs: number;
  private readonly maxRetryDelayMs: number;
  private readonly timeoutMs: number;

  constructor(baseUrl: string = 'http://127.0.0.1:8000', options?: GatewayOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.maxRetries = options?.maxRetries ?? 2;
    this.initialRetryDelayMs = options?.initialRetryDelayMs ?? 500;
    this.maxRetryDelayMs = options?.maxRetryDelayMs ?? 10000;
    this.timeoutMs = options?.timeoutMs ?? 120000;
  }

  private async sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private isRetryableStatus(status?: number): boolean {
    return status === 429 || status === 502 || status === 503 || status === 504;
  }

  /**
   * Executes an async operation with bounded exponential backoff on transient errors.
   */
  private async executeWithRetry<T>(operation: () => Promise<T>): Promise<T> {
    let lastError: Error | null = null;
    let attempt = 0;

    while (attempt <= this.maxRetries) {
      try {
        return await operation();
      } catch (err: unknown) {
        lastError = err instanceof Error ? err : new Error(String(err));
        attempt++;

        if (attempt > this.maxRetries) {
          break;
        }

        let isRetryable = false;
        let retryAfterMs: number | null = null;

        if (err instanceof BackendGatewayError) {
          isRetryable = this.isRetryableStatus(err.status);
        } else if (err instanceof TypeError) {
          // Transient network connection drop (e.g. backend temporarily unreachable)
          isRetryable = true;
        }
        // Deliberately do NOT retry on AbortError (timeout) to prevent cascading duplicate
        // request storms when the local ML engine is processing heavy high-resolution manga pages.

        if (!isRetryable) {
          throw lastError;
        }

        const exponentialDelay = Math.min(
          this.initialRetryDelayMs * Math.pow(2, attempt - 1),
          this.maxRetryDelayMs
        );
        const delay = retryAfterMs !== null ? Math.max(retryAfterMs, exponentialDelay) : exponentialDelay;

        console.warn(
          `[${formatLocalTimestamp()}] [InkShift:GW] Transient error on attempt ${attempt}. Retrying in ${delay}ms... (${lastError.message})`
        );
        await this.sleep(delay);
      }
    }

    throw lastError ?? new BackendGatewayError('UNKNOWN_ERROR', 'Request failed unexpectedly');
  }

  /**
   * Probes backend health endpoint.
   */
  async checkHealth(): Promise<{ status: string; engine: string; version: string }> {
    return this.executeWithRetry(async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const response = await fetch(`${this.baseUrl}/api/v1/health`, {
          method: 'GET',
          headers: {
            'X-InkShift-Client': 'extension',
          },
          signal: controller.signal,
        });

        if (!response.ok) {
          let errorDetail: APIErrorDetail = { code: 'HEALTH_CHECK_FAILED', message: response.statusText };
          try {
            const body = (await response.json()) as { error?: APIErrorDetail };
            if (body.error) {
              errorDetail = body.error;
            }
          } catch {
            // Ignore non-json responses
          }
          throw new BackendGatewayError(errorDetail.code, errorDetail.message, response.status);
        }

        return (await response.json()) as { status: string; engine: string; version: string };
      } finally {
        clearTimeout(timeoutId);
      }
    });
  }

  /**
   * Checks if an image hash is already translated and cached in backend SQLite.
   * Returns TranslationResponse on hit (200), or null on miss (404).
   */
  async checkCache(imageHash: string, engine?: string, translator?: string): Promise<TranslationResponse | null> {
    return this.executeWithRetry(async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const queryParams = new URLSearchParams();
        if (engine && engine !== 'auto') {
          queryParams.set('engine', engine);
        }
        if (translator) {
          queryParams.set('translator', translator);
        }
        const qs = queryParams.toString() ? `?${queryParams.toString()}` : '';
        const response = await fetch(`${this.baseUrl}/api/v1/cache/${encodeURIComponent(imageHash)}${qs}`, {
          method: 'GET',
          headers: {
            'X-InkShift-Client': 'extension',
          },
          signal: controller.signal,
        });

        if (response.status === 404) {
          return null;
        }

        if (!response.ok) {
          let errorDetail: APIErrorDetail = { code: 'CACHE_QUERY_FAILED', message: response.statusText };
          try {
            const body = (await response.json()) as { error?: APIErrorDetail };
            if (body.error) {
              errorDetail = body.error;
            }
          } catch {
            // Ignore parse errors
          }
          throw new BackendGatewayError(errorDetail.code, errorDetail.message, response.status);
        }

        return (await response.json()) as TranslationResponse;
      } finally {
        clearTimeout(timeoutId);
      }
    });
  }

  /**
   * Deletes cached translations from backend SQLite.
   * Can wipe all entries (all=true) or purge specific imageHash.
   */
  async clearCache(
    all: boolean = true,
    imageHash?: string,
    targetLang?: string,
    engine?: string
  ): Promise<{ success: boolean; deleted: number; scope: string }> {
    return this.executeWithRetry(async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const queryParams = new URLSearchParams();
        if (all) {
          queryParams.set('all', 'true');
        }
        if (imageHash) {
          queryParams.set('image_hash', imageHash);
        }
        if (targetLang) {
          queryParams.set('target_lang', targetLang);
        }
        if (engine && engine !== 'auto') {
          queryParams.set('engine', engine);
        }

        const qs = queryParams.toString() ? `?${queryParams.toString()}` : '';
        const response = await fetch(`${this.baseUrl}/api/v1/cache${qs}`, {
          method: 'DELETE',
          headers: {
            'X-InkShift-Client': 'extension',
          },
          signal: controller.signal,
        });

        if (!response.ok) {
          let errorDetail: APIErrorDetail = { code: 'CACHE_CLEAR_FAILED', message: response.statusText };
          try {
            const body = (await response.json()) as { error?: APIErrorDetail };
            if (body.error) {
              errorDetail = body.error;
            }
          } catch {
            // Ignore parse errors
          }
          throw new BackendGatewayError(errorDetail.code, errorDetail.message, response.status);
        }

        return (await response.json()) as { success: boolean; deleted: number; scope: string };
      } finally {
        clearTimeout(timeoutId);
      }
    });
  }

  /**
   * Sends a translation request to POST /api/v1/translate.
   */
  async requestTranslation(req: TranslationRequest): Promise<TranslationResponse> {
    return this.executeWithRetry(async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const response = await fetch(`${this.baseUrl}/api/v1/translate`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-InkShift-Client': 'extension',
          },
          body: JSON.stringify(req),
          signal: controller.signal,
        });

        if (!response.ok) {
          let errorDetail: APIErrorDetail = {
            code: `HTTP_${response.status}`,
            message: `Translation request failed with status ${response.status}`,
          };
          try {
            const body = (await response.json()) as { error?: APIErrorDetail };
            if (body.error) {
              errorDetail = body.error;
            }
          } catch {
            // Ignore parse errors
          }
          throw new BackendGatewayError(errorDetail.code, errorDetail.message, response.status);
        }

        return (await response.json()) as TranslationResponse;
      } finally {
        clearTimeout(timeoutId);
      }
    });
  }

  /**
   * Reports manga series, chapter, and page manifest to POST /api/v1/context/report.
   */
  async reportContext(report: ChapterContextReport): Promise<ContextReportResponse> {
    return this.executeWithRetry(async () => {
      const response = await fetch(`${this.baseUrl}/api/v1/context/report`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-InkShift-Client': 'extension',
        },
        body: JSON.stringify(report),
      });

      if (!response.ok) {
        throw new BackendGatewayError('CONTEXT_REPORT_FAILED', `Report context failed: ${response.status}`, response.status);
      }

      return (await response.json()) as ContextReportResponse;
    });
  }

  /**
   * Updates active reading progress to PATCH /api/v1/context/progress.
   */
  async updateReadingProgress(update: ProgressUpdateRequest): Promise<ProgressUpdateResponse> {
    return this.executeWithRetry(async () => {
      const response = await fetch(`${this.baseUrl}/api/v1/context/progress`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-InkShift-Client': 'extension',
        },
        body: JSON.stringify(update),
      });

      if (!response.ok) {
        throw new BackendGatewayError('PROGRESS_UPDATE_FAILED', `Progress update failed: ${response.status}`, response.status);
      }

      return (await response.json()) as ProgressUpdateResponse;
    });
  }

  /**
   * Retrieves chapter pages from GET /api/v1/context/chapters/{chapter_id}/pages.
   */
  async getChapterPages(chapterId: string): Promise<ChapterPagesResponse> {
    return this.executeWithRetry(async () => {
      const response = await fetch(`${this.baseUrl}/api/v1/context/chapters/${encodeURIComponent(chapterId)}/pages`, {
        headers: {
          'X-InkShift-Client': 'extension',
        },
      });

      if (!response.ok) {
        throw new BackendGatewayError('CHAPTER_PAGES_FAILED', `Get chapter pages failed: ${response.status}`, response.status);
      }

      return (await response.json()) as ChapterPagesResponse;
    });
  }

  /**
   * Transmits batched extension telemetry logs to POST /api/v1/telemetry/logs.
   *
   * Network or server errors are caught silently without throwing,
   * guaranteeing that telemetry failures never interrupt core translation or reading workflows.
   */
  async postTelemetryLogs(batch: TelemetryBatchRequest): Promise<boolean> {
    if (!batch.logs || batch.logs.length === 0) {
      return true;
    }

    try {
      const response = await fetch(`${this.baseUrl}/api/v1/telemetry/logs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-InkShift-Client': 'extension',
        },
        body: JSON.stringify(batch),
      });

      return response.ok;
    } catch {
      // Telemetry ingestion is fire-and-forget; never interrupt user workflows
      return false;
    }
  }

  /**
   * Discovers available models for a provider via POST /api/v1/models/discover.
   */
  async discoverModels(
    provider: string,
    apiKey?: string,
    baseUrl?: string
  ): Promise<DiscoveredModelsData> {
    return this.executeWithRetry(async () => {
      const payload: Record<string, string> = { provider };
      if (apiKey) payload.api_key = apiKey;
      if (baseUrl) payload.base_url = baseUrl;

      const response = await fetch(`${this.baseUrl}/api/v1/models/discover`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-InkShift-Client': 'extension',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let errCode = 'MODEL_DISCOVERY_FAILED';
        let errMsg = `Model discovery failed: ${response.status}`;
        try {
          const errBody = await response.json();
          if (errBody?.error?.code) errCode = errBody.error.code;
          if (errBody?.error?.message) errMsg = errBody.error.message;
        } catch {
          // Fall back to default error text if JSON parsing fails
        }
        throw new BackendGatewayError(errCode, errMsg, response.status);
      }

      return (await response.json()) as DiscoveredModelsData;
    });
  }

  /**
   * Retrieves provider settings and masked status via GET /api/v1/settings/providers.
   */
  async getProviderSettings(): Promise<ProviderSettingsData> {
    return this.executeWithRetry(async () => {
      const response = await fetch(`${this.baseUrl}/api/v1/settings/providers`, {
        headers: {
          'X-InkShift-Client': 'extension',
        },
      });

      if (!response.ok) {
        throw new BackendGatewayError('SETTINGS_FETCH_FAILED', `Fetch provider settings failed: ${response.status}`, response.status);
      }

      return (await response.json()) as ProviderSettingsData;
    });
  }

  /**
   * Updates provider credentials and base URL via POST /api/v1/settings/providers.
   */
  async saveProviderSettings(
    provider: string,
    apiKey?: string,
    baseUrl?: string
  ): Promise<SaveProviderSettingsData> {
    return this.executeWithRetry(async () => {
      const payload: Record<string, string> = { provider };
      if (apiKey !== undefined) payload.api_key = apiKey;
      if (baseUrl !== undefined) payload.base_url = baseUrl;

      const response = await fetch(`${this.baseUrl}/api/v1/settings/providers`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-InkShift-Client': 'extension',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let errCode = 'SETTINGS_SAVE_FAILED';
        let errMsg = `Save provider settings failed: ${response.status}`;
        try {
          const errBody = await response.json();
          if (errBody?.error?.code) errCode = errBody.error.code;
          if (errBody?.error?.message) errMsg = errBody.error.message;
        } catch {
          // Fall back to default error text if JSON parsing fails
        }
        throw new BackendGatewayError(errCode, errMsg, response.status);
      }

      return (await response.json()) as SaveProviderSettingsData;
    });
  }
}

