import type { ChatRequest, ChatResponse, ChatStats, Conversation, QuestionSuggestionsResponse } from '../types/chat';
const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env;
const baseUrl = (env.VITE_API_BASE_URL?.trim() || (env.PROD ? '' : 'http://localhost:8000')).replace(/\/$/, '');
export const isDemo = env.VITE_DEMO_MODE === 'true';
export const emptyStats: ChatStats = { total_questions: 0, gemini_api_calls: 0, cache_hits: 0 };
export class ApiError extends Error {
  constructor(message: string, public code: string, public retryable: boolean) { super(message); }
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${baseUrl}${path}`, { ...options, signal: options?.signal ?? AbortSignal.timeout(120000) }); }
  catch { throw new ApiError('Unable to reach the course helpdesk. Check your connection and try again.', 'NETWORK_ERROR', true); }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.error?.message || 'Unable to process your request right now. Please try again.', body?.error?.code || 'REQUEST_FAILED', body?.error?.retryable ?? true);
  }
  return response.json() as Promise<T>;
}
export async function createSession(): Promise<Conversation> {
  if (isDemo) return { sessionId: crypto.randomUUID(), messages: [] };
  const response = await request<{ session_id: string }>('/api/session', { method: 'POST' });
  return { sessionId: response.session_id, messages: [] };
}
export async function reconcileSession(sessionId: string): Promise<{ conversation: Conversation; reset: boolean }> {
  if (isDemo) return { conversation: { sessionId, messages: [] }, reset: false };
  try { return { conversation: await request<Conversation>(`/api/session/${encodeURIComponent(sessionId)}`), reset: false }; }
  catch (error) {
    if (error instanceof ApiError && error.code === 'UNKNOWN_SESSION') return { conversation: await createSession(), reset: true };
    throw error;
  }
}
export async function sendQuestion(payload: ChatRequest): Promise<ChatResponse> {
  if (!isDemo) return request<ChatResponse>('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  await new Promise(resolve => setTimeout(resolve, 800 + Math.random() * 400));
  if (env.VITE_MOCK_FAILURE === 'true' || payload.question.trim().toLowerCase() === '/test-error') throw new Error('Unable to process your request right now. Please try again.');
  return { answer: 'This is a demonstration response. Verified answers will become available when the course-document backend is connected.', sources: [], cached: false, session_id: payload.session_id };
}
export async function getStats(): Promise<ChatStats> { return isDemo ? { ...emptyStats } : request<ChatStats>('/api/stats'); }

export async function getQuestionSuggestions(q: string, signal: AbortSignal): Promise<QuestionSuggestionsResponse> {
  if (isDemo) return { suggestions: [], knowledge_version: null };
  return request<QuestionSuggestionsResponse>(`/api/faq/suggestions?${new URLSearchParams({ q, limit: '5' })}`, { signal });
}

