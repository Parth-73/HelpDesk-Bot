import { ArrowUpRight, BookOpen, CalendarDays, CheckCheck, ChevronRight, CircleHelp, FileText, GraduationCap, MessageSquare, Plus, Send, ShieldCheck, Sparkles, TriangleAlert, X, Zap } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { QuestionSuggestions, useQuestionSuggestions } from './QuestionSuggestions';
import type { FormEvent, KeyboardEvent } from 'react';
import type { ChatMessage as Message, ChatStats } from '../types/chat';

export function Header({ onNewChat, loading }: { onNewChat: () => void; loading: boolean }) {
 return <header className="header"><div className="brand"><img src="/assets/institution-logo.gif" alt="Institution logo"/><span className="brand-divider"/><div><h1>DPM-101 Course Helpdesk</h1><p>AI-Powered Student Assistance</p></div></div><div className="header-actions"><span className="status"><i/> Helpdesk online</span><button className="new-chat" aria-label="New chat" onClick={onNewChat} disabled={loading}><Plus size={17}/><span>New chat</span></button></div></header>;
}
const suggestionIcons = [FileText, GraduationCap, CalendarDays, ShieldCheck];
const labels = ['Examinations', 'Grading & assessment', 'Dates & deadlines', 'Course requirements'];
export const defaultQuestions = ['What are the examination guidelines?', 'How is the course graded?', 'What are the important deadlines?', 'What are the passing requirements?'];
export function SuggestedQuestions({ questions, onSelect }: { questions: string[]; onSelect: (q: string) => void }) {
 return <div className="suggestions">{questions.map((question, i) => { const Icon = suggestionIcons[i]; return <button key={question} onClick={() => onSelect(question)}><span className="suggestion-top"><Icon size={20}/><ArrowUpRight size={16}/></span><span className="suggestion-label">{labels[i]}</span><span className="suggestion-question">{question}</span></button>; })}</div>;
}
export function WelcomeScreen({ questions, onSelect }: { questions: string[]; onSelect: (q: string) => void }) {
 return <div className="welcome"><div className="welcome-icon"><BookOpen size={29} strokeWidth={1.6}/><span><Sparkles size={13}/></span></div><div className="eyebrow">YOUR COURSE COMPANION</div><h2>How can I help you today?</h2><p>Ask questions about DPM-101 course policies, examinations,<br className="desktop-break"/> grading, deadlines, and guidelines.</p><SuggestedQuestions questions={questions} onSelect={onSelect}/><span className="welcome-hint"><CircleHelp size={14}/> Start with a question above, or ask your own below.</span></div>;
}
export function ChatMessage({ message, demo }: { message: Message; demo: boolean }) {
 return <article className={`message ${message.role}`}><div className="message-avatar">{message.role === 'assistant' ? <BookOpen size={18}/> : 'You'}</div><div className="message-body"><div className="message-meta"><strong>{message.role === 'assistant' ? 'Course assistant' : 'You'}</strong><time dateTime={message.timestamp}>{new Date(message.timestamp).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</time></div><div className="bubble">{message.role === 'assistant' && demo && <span className="demo-label">DEMONSTRATION RESPONSE</span>}<p>{message.content}</p>{!!message.sources?.length && <div className="sources"><span>Sources</span>{message.sources.map((source, i) => <code key={`${source}-${i}`}><FileText size={13}/>{source}</code>)}</div>}{message.cached && <span className="cached"><CheckCheck size={13}/> Served from cache</span>}</div></div></article>;
}
export function LoadingIndicator() { return <div className="loading" role="status"><span className="typing"><i/><i/><i/></span>Checking course documents...</div>; }
export function ErrorMessage({ message, onRetry }: { message: string; onRetry: () => void }) { return <div className="error" role="alert"><TriangleAlert size={18}/><span>{message}</span><button onClick={onRetry}>Retry</button></div>; }
export function ChatInput({ value, onChange, onSend, loading }: { value: string; onChange: (v: string) => void; onSend: () => void; loading: boolean }) {
 const input = useRef<HTMLTextAreaElement>(null);
 const wrapper = useRef<HTMLDivElement>(null);
 const wasLoading = useRef(false);
 const [focused, setFocused] = useState(false);
 const [dismissedValue, setDismissedValue] = useState<string | null>(null);
 const [selectedIndex, setSelectedIndex] = useState(-1);
 const listId = useId();
 const { suggestions } = useQuestionSuggestions(value, focused && !loading && dismissedValue !== value);
 const open = suggestions.length > 0;
 useEffect(() => { setSelectedIndex(-1); }, [value, suggestions]);
 useEffect(() => { if (wasLoading.current && !loading) input.current?.focus({ preventScroll: true }); wasLoading.current = loading; }, [loading]);
 useEffect(() => { if(input.current) { input.current.style.height = 'auto'; input.current.style.height = `${Math.min(input.current.scrollHeight, 140)}px`; } }, [value]);
 function close() { setDismissedValue(value); setSelectedIndex(-1); }
 function choose(question: string) {
   onChange(question); setDismissedValue(question); setSelectedIndex(-1);
   requestAnimationFrame(() => { input.current?.focus({ preventScroll: true }); input.current?.setSelectionRange(question.length, question.length); });
 }
 function submit(event: FormEvent) { event.preventDefault(); close(); onSend(); }
 function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
   if (event.nativeEvent.isComposing) return;
   if (event.key === 'Escape') { if (open) event.preventDefault(); close(); return; }
   if (event.key === 'Tab') { close(); return; }
   if (open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
     event.preventDefault(); setSelectedIndex(index => event.key === 'ArrowDown' ? (index + 1) % suggestions.length : (index <= 0 ? suggestions.length - 1 : index - 1)); return;
   }
   if (event.key === 'Enter' && !event.shiftKey) {
     event.preventDefault();
     if (open && selectedIndex >= 0 && suggestions[selectedIndex]) choose(suggestions[selectedIndex].question);
     else if (!loading) { close(); onSend(); }
   }
 }
 function blur() { window.setTimeout(() => { if (document.activeElement !== input.current && !wrapper.current?.querySelector('.question-suggestions')?.contains(document.activeElement)) setFocused(false); }, 0); }
 return <div className="composer-wrap"><div className="composer-anchor" ref={wrapper}>
   <QuestionSuggestions id={listId} suggestions={suggestions} selectedIndex={selectedIndex} onSelect={choose} onHighlight={setSelectedIndex}/>
   <form className="composer" onSubmit={submit}><label className="sr-only" htmlFor="question">Your DPM-101 question</label>
     <textarea ref={input} id="question" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-expanded={open}
       aria-controls={open ? listId : undefined} aria-activedescendant={open && selectedIndex >= 0 ? `${listId}-${selectedIndex}` : undefined}
       rows={1} value={value} onChange={event => { setDismissedValue(null); onChange(event.target.value); }} onFocus={() => setFocused(true)} onBlur={blur}
       onKeyDown={keyDown} placeholder="Ask anything about DPM-101..." disabled={loading} maxLength={2000}/>
     <button className="send" type="submit" aria-label="Send question" disabled={loading || !value.trim()}><Send size={18}/></button>
   </form></div><div className="composer-help"><span>Enter to send <span className="help-dot">&middot;</span> Shift + Enter for a new line</span><span><ShieldCheck size={12}/> Course-specific support</span></div><footer>Answers are based on official DPM-101 course documents.</footer></div>;
}
export function StatsPanel({ stats, demo, unavailable }: { stats: ChatStats; demo: boolean; unavailable: boolean }) {
 const [expanded, setExpanded] = useState(false);
 const items = [{icon: MessageSquare, label: 'Total Questions Asked', value: stats.total_questions}, {icon: Sparkles, label: 'Gemini API Calls Made', value: stats.gemini_api_calls}, {icon: Zap, label: 'Answers Served from Cache', value: stats.cache_hits}];
 return <aside className="sidebar" aria-label="Helpdesk information"><section className="stats-section"><div className="panel-title"><h2>Helpdesk activity</h2><span className="live"><i/>{demo ? 'Demo' : 'Live'}</span></div><p className="panel-caption">A little insight into your helpdesk.</p><div className="stat-list">{items.map(({icon: Icon, label, value}) => <div className="stat" key={label}><span className="stat-icon"><Icon size={18}/></span><div><strong>{value}</strong><span>{label}</span></div></div>)}</div><p className="stats-note">{demo ? 'Counters will update when the backend is connected.' : unavailable ? 'Statistics are temporarily unavailable.' : 'Usage reported by the course helpdesk.'}</p></section><section className="guide"><span className="guide-icon"><BookOpen size={20}/></span><h3>A little guidance goes a long way.</h3><p>Keep your questions specific to DPM-101 for the most relevant support.</p><button onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>Tips for better questions <ChevronRight size={15}/></button>{expanded && <div className="tips">Ask one question at a time. Include the assessment or topic you need help with, and avoid sharing personal information.</div>}</section><div className="trust"><ShieldCheck size={16}/><p>Built for students.<br/><strong>Grounded in course documents.</strong></p></div></aside>;
}
export function DemoNotice() { const [open, setOpen] = useState(true); return open ? <div className="demo-notice"><span><Sparkles size={15}/><strong>Demo mode</strong><span>Explore the helpdesk. Verified answers arrive with the course backend.</span></span><button aria-label="Dismiss demo notice" onClick={() => setOpen(false)}><X size={15}/></button></div> : null; }

