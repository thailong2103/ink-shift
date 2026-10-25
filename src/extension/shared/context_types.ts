/**
 * TypeScript models and contracts for Manga Context Graph.
 * Synchronized with src/backend/context/schemas.py.
 */

export type PageStatus = 'discovered' | 'queued' | 'processing' | 'ready' | 'failed';
export type ChapterStatus = 'discovered' | 'reading' | 'completed';

export interface PageItem {
  page_number: number;
  image_url: string;
  image_hash?: string;
  status?: PageStatus;
}

export interface ChapterContextReport {
  series_id: string;
  series_title: string;
  source_domain: string;
  cover_url?: string;
  chapter_id: string;
  chapter_ordinal: number;
  chapter_label: string;
  chapter_url: string;
  total_pages?: number;
  pages: PageItem[];
}

export interface ProgressUpdateRequest {
  chapter_id: string;
  page_number: number;
}

export interface PageResponse {
  page_id: string;
  chapter_id: string;
  page_number: number;
  image_url: string;
  image_hash: string | null;
  status: PageStatus;
  created_at: number;
  updated_at: number;
}

export interface ChapterPagesResponse {
  chapter_id: string;
  total_pages: number;
  last_read_page: number;
  status: ChapterStatus;
  pages: PageResponse[];
}

export interface ContextReportResponse {
  success: boolean;
  chapter_id: string;
  series_id: string;
  pages_registered: number;
}

export interface ProgressUpdateResponse {
  success: boolean;
  chapter_id: string;
  last_read_page: number;
  status: ChapterStatus;
}
