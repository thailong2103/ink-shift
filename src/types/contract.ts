/**
 * InkShift Canonical API Contract Interfaces.
 *
 * Defines the immutable TypeScript types for data exchange between
 * the Chrome Extension (extension-core) and FastAPI backend (backend-engine).
 * Synchronized field-for-field with src/backend/schemas/contract.py.
 */

/**
 * Normalized bounding box tuple: [ymin, xmin, ymax, xmax].
 * Each coordinate is an integer in the range [0, 1000] (per-mille of image dimension).
 */
export type BoundingBox = [number, number, number, number];

/**
 * 2D vertex [x, y] in range [0.0, 100.0] representing relative percentage of the bounding box.
 */
export type PolygonPoint = [number, number];

/**
 * Reading direction detected in the original manga speech bubble.
 */
export type ReadingDirection = 'vertical' | 'horizontal';

/**
 * A single translated manga text bubble or narration box.
 */
export interface TranslatedBlock {
  id: string;
  box: BoundingBox;
  polygon?: PolygonPoint[];
  parent_bubble_id?: string;
  parent_box?: BoundingBox;
  source_text?: string;
  translated_text: string;
  direction?: ReadingDirection;
  confidence?: number;
}

/**
 * Engine execution mode selection.
 */
export type EngineMode =
  | 'auto'
  | 'local'
  | 'cloud'
  | 'mock';

/**
 * Request payload sent to POST /api/v1/translate.
 */
export interface TranslationRequest {
  image: string;
  image_hash?: string;
  source_lang?: string;
  target_lang?: string;
  engine?: EngineMode;
  provider?: string;
  model?: string;
  translator?: string;
  force_refresh?: boolean;
  chapter_url?: string;
}

/**
 * Successful response returned by POST /api/v1/translate or GET /api/v1/cache/{image_hash}.
 */
export interface TranslationResponse {
  success: true;
  page_hash: string;
  engine_used: string;
  execution_time_ms: number;
  from_cache: boolean;
  is_fallback?: boolean;
  blocks: TranslatedBlock[];
}

/**
 * Machine-readable and human-readable error payload.
 */
export interface APIErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

/**
 * Standardized error envelope returned by all API endpoints upon failure.
 */
export interface APIErrorResponse {
  success: false;
  error: APIErrorDetail;
}

/**
 * Discriminated union of all possible API responses from translation endpoints.
 */
export type APIResponse = TranslationResponse | APIErrorResponse;
