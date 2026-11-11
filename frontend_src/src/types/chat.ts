export interface ChatMessage { id: string; role: 'user' | 'assistant'; content: string; timestamp: string; sources?: string[]; cached?: boolean }
export interface ChatStats { total_questions: number; gemini_api_calls: number; cache_hits: number }
export interface ChatRequest { session_id: string; request_id: string; question: string }
export interface ChatResponse { answer_path?: "response_cache" | "semantic_faq" | "gemini_rag" | "deterministic" | "abstention" | null; answer: string; sources: string[]; cached: boolean; session_id: string }
export interface Conversation { sessionId: string; messages: ChatMessage[] }

export interface QuestionSuggestion { faq_id: string; question: string; topic: string }
export interface QuestionSuggestionsResponse { suggestions: QuestionSuggestion[]; knowledge_version: string | null }
