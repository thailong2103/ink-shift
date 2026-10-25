import type { TranslationResponse, TranslationRequest, APIErrorResponse, BoundingBox } from '../../src/types/contract';
import sampleFixture from '../fixtures/sample_page_response.json';

// Static type assertion: sampleFixture satisfies TranslationResponse
const response: TranslationResponse = sampleFixture as TranslationResponse;

// Verify block properties
const firstBlock = response.blocks[0];
const box: BoundingBox = firstBlock.box;
const text: string = firstBlock.translated_text;

// Verify request typing
const request: TranslationRequest = {
  image: 'data:image/jpeg;base64,abc',
  image_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  source_lang: 'ja',
  target_lang: 'vi',
  engine: 'cloud',
  force_refresh: false,
};

// Verify error response typing
const errorResp: APIErrorResponse = {
  success: false,
  error: {
    code: 'CACHE_MISS',
    message: 'Page not found',
  },
};

export { response, request, errorResp, box, text };
