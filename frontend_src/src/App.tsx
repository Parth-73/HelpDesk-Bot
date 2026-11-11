import { useEffect, useRef, useState } from 'react';
import { ChatInput, ChatMessage, defaultQuestions, DemoNotice, ErrorMessage, Header, LoadingIndicator, StatsPanel, WelcomeScreen } from './components/Helpdesk';
import { ApiError, createSession, emptyStats, getStats, isDemo, reconcileSession, sendQuestion } from './services/chatService';
import type { ChatRequest, Conversation } from './types/chat';
const storageKey = isDemo ? 'dpm-101-demo-conversation' : 'dpm-101-conversation';
function fresh(): Conversation { return { sessionId: crypto.randomUUID(), messages: [] }; }
function restore(): Conversation {
 try { const raw = JSON.parse(sessionStorage.getItem(storageKey) || 'null'); if (raw && typeof raw.sessionId === 'string' && Array.isArray(raw.messages) && raw.messages.every((m: Record<string, unknown>) => typeof m.id === 'string' && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && typeof m.timestamp === 'string' && (!m.sources || (Array.isArray(m.sources) && m.sources.every(s => typeof s === 'string'))))) return raw; } catch { /* Storage may be unavailable. */ }
 return fresh();
}
export default function App() {
 const [conversation, setConversation] = useState<Conversation>(restore);
 const [input, setInput] = useState('');
 const [loading, setLoading] = useState(!isDemo);
 const [error, setError] = useState('');
 const [sessionNotice, setSessionNotice] = useState('');
 const [stats, setStats] = useState(emptyStats);
 const [statsUnavailable, setStatsUnavailable] = useState(false);
 const [questions] = useState(defaultQuestions);
 const busy = useRef(!isDemo);
 const ready = useRef(isDemo);
 const retryRequest = useRef<ChatRequest | null>(null);
 const bootstrap = useRef<ReturnType<typeof reconcileSession> | null>(null);
 const scroll = useRef<HTMLDivElement>(null);
 useEffect(() => { try { sessionStorage.setItem(storageKey, JSON.stringify(conversation)); } catch { /* In-memory history remains available. */ } }, [conversation]);
 useEffect(() => {
  if (isDemo) return;
  let active = true;
  bootstrap.current ??= reconcileSession(conversation.sessionId);
  bootstrap.current.then(({ conversation: canonical, reset }) => {
   if (!active) return;
   setConversation(canonical); ready.current = true;
   if (reset && conversation.messages.length) setSessionNotice('The previous session is no longer available. A new conversation has been started.');
   else if (conversation.messages.length && JSON.stringify(conversation.messages.map(m => [m.role, m.content])) !== JSON.stringify(canonical.messages.map(m => [m.role, m.content]))) setSessionNotice('Conversation synced with the server. Only completed, saved exchanges are shown.');
  }).catch(error => { if (active) setError(error instanceof Error ? error.message : 'Unable to start your conversation.'); })
    .finally(() => { if (active) { busy.current = false; setLoading(false); } });
  return () => { active = false; };
 }, []);
 useEffect(() => {
  let active = true; let pending = false;
  async function refresh() { if (pending) return; pending = true; try { const values = await getStats(); if (active) { setStats(values); setStatsUnavailable(false); } } catch { if (active) setStatsUnavailable(true); } finally { pending = false; } }
  void refresh(); const timer = window.setInterval(() => void refresh(), 4000);
  return () => { active = false; window.clearInterval(timer); };
 }, []);
 useEffect(() => { if (scroll.current) scroll.current.scrollTop = conversation.messages.length ? scroll.current.scrollHeight : 0; }, [conversation.messages, loading, error]);
 async function newChat() {
  if (busy.current) return;
  busy.current = true; setLoading(true); setError('');
  try { const next = await createSession(); setConversation(next); ready.current = true; setInput(''); setSessionNotice(''); retryRequest.current = null; }
  catch (error) { setError(error instanceof Error ? error.message : 'Unable to start a new conversation.'); }
  finally { busy.current = false; setLoading(false); }
 }
 async function submit(question: string, retry = false) {
  if (busy.current || !ready.current || !question.trim()) return;
  busy.current = true; setLoading(true); setError('');
  const payload = retry && retryRequest.current ? retryRequest.current : { session_id: conversation.sessionId, request_id: crypto.randomUUID(), question: question.trim() };
  retryRequest.current = payload;
  if (!retry) { setConversation(c => ({ ...c, messages: [...c.messages, {id: payload.request_id, role: 'user', content: payload.question, timestamp: new Date().toISOString()}] })); setInput(''); }
  try {
   const response = await sendQuestion(payload);
   setConversation(c => ({sessionId: response.session_id, messages: [...c.messages, {id: crypto.randomUUID(), role:'assistant', content: response.answer, sources: response.sources, cached: response.cached, timestamp: new Date().toISOString()}]}));
   retryRequest.current = null;
   try { setStats(await getStats()); setStatsUnavailable(false); } catch { setStatsUnavailable(true); }
  } catch (error) {
   if (error instanceof ApiError && error.code === 'REQUEST_OUTDATED') retryRequest.current = { ...payload, request_id: crypto.randomUUID() };
   if (error instanceof ApiError && error.code === 'UNKNOWN_SESSION') { ready.current = false; retryRequest.current = null; }
   setError(error instanceof Error ? error.message : 'Unable to process your request right now. Please try again.');
  }
  finally { busy.current = false; setLoading(false); }
 }
 return <div className="app"><Header onNewChat={() => void newChat()} loading={loading}/><div className="workspace"><main className="chat-panel"><div className="chat-topline"><span><i/> DPM-101 <span className="slash">/</span> Student helpdesk</span><span className="course-tag">COURSE SUPPORT</span></div>{isDemo && <DemoNotice/>}{sessionNotice && <div className="demo-notice" role="status">{sessionNotice}</div>}<div className="conversation" ref={scroll}>{conversation.messages.length === 0 ? <WelcomeScreen questions={questions} onSelect={q => void submit(q)}/> : <div className="message-list" role="log" aria-label="Conversation" aria-live="polite">{conversation.messages.map(message => <ChatMessage key={message.id} message={message} demo={isDemo}/>)}</div>}{loading && <LoadingIndicator/>}{error && <ErrorMessage message={error} onRetry={() => retryRequest.current ? void submit(retryRequest.current.question, true) : void newChat()}/>}</div><ChatInput value={input} onChange={setInput} onSend={() => void submit(input)} loading={loading}/></main><StatsPanel stats={stats} demo={isDemo} unavailable={statsUnavailable}/></div><div className="page-footer"><span>DPM-101 · STUDENT SUPPORT</span><span>A clearer path through your coursework.</span></div></div>;
}
