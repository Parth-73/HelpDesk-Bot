import { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { getQuestionSuggestions } from '../services/chatService';
import type { QuestionSuggestion } from '../types/chat';

const empty: QuestionSuggestion[] = [];
export function useQuestionSuggestions(value: string, enabled: boolean) {
  const [result, setResult] = useState<{ query: string; items: QuestionSuggestion[]; version: string | null }>({ query: '', items: empty, version: null });
  const sequence = useRef(0);
  useEffect(() => {
    let active = true;
    let controller: AbortController | undefined;
    sequence.current++;
    if (!enabled || value.trim().length < 2) {
      setResult({ query: value, items: empty, version: null });
      return;
    }
    async function refresh() {
      controller?.abort();
      controller = new AbortController();
      const current = controller;
      const requestNumber = ++sequence.current;
      try {
        const response = await getQuestionSuggestions(value.trim().slice(0, 200), current.signal);
        if (active && !current.signal.aborted && requestNumber === sequence.current) {
          // Replace the complete result set, including its version; never mix snapshots.
          setResult({ query: value, items: response.suggestions.slice(0, 5), version: response.knowledge_version });
        }
      } catch {
        if (active && !current.signal.aborted && requestNumber === sequence.current) setResult({ query: value, items: empty, version: null });
      }
    }
    const timer = window.setTimeout(() => void refresh(), 200);
    // Recheck an unchanged focused input so a new knowledge snapshot can clear old options.
    const interval = window.setInterval(() => void refresh(), 10000);
    return () => { active = false; sequence.current++; controller?.abort(); window.clearTimeout(timer); window.clearInterval(interval); };
  }, [value, enabled]);
  return { suggestions: enabled && result.query === value ? result.items : empty, knowledgeVersion: result.version };
}

export function QuestionSuggestions({ id, suggestions, selectedIndex, onSelect, onHighlight }: {
  id: string; suggestions: QuestionSuggestion[]; selectedIndex: number;
  onSelect: (question: string) => void; onHighlight: (index: number) => void;
}) {
  const selected = useRef<HTMLLIElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function fit() {
      const element = panel.current;
      if (!element) return;
      const viewport = window.visualViewport;
      const available = (element.parentElement?.getBoundingClientRect().top ?? 340) - (viewport?.offsetTop ?? 0) - 12;
      element.style.maxHeight = `${Math.max(60, Math.min(340, available, (viewport?.height ?? window.innerHeight) * .43))}px`;
    }
    fit(); window.addEventListener('resize', fit); window.visualViewport?.addEventListener('resize', fit); window.visualViewport?.addEventListener('scroll', fit);
    return () => { window.removeEventListener('resize', fit); window.visualViewport?.removeEventListener('resize', fit); window.visualViewport?.removeEventListener('scroll', fit); };
  }, [suggestions.length]);
  useEffect(() => { selected.current?.scrollIntoView({ block: 'nearest' }); }, [selectedIndex]);
  if (!suggestions.length) return null;
  return <div ref={panel} className="question-suggestions" aria-label="Question suggestions">
    <div className="question-suggestions-heading" id={`${id}-label`}>Suggested questions</div>
    <ul id={id} role="listbox" aria-labelledby={`${id}-label`}>{suggestions.map((suggestion, index) =>
      <li key={suggestion.faq_id} id={`${id}-${index}`} role="option" aria-selected={selectedIndex === index}
        ref={selectedIndex === index ? selected : undefined} onMouseEnter={() => onHighlight(index)}>
        <button type="button" tabIndex={-1} onMouseDown={event => event.preventDefault()} onClick={() => onSelect(suggestion.question)}>
          <Search size={15} aria-hidden="true"/><span><span className="question-suggestion-text">{suggestion.question}</span><span className="question-suggestion-topic">{suggestion.topic}</span></span>
        </button>
      </li>)}</ul>
    <span className="sr-only" role="status">{suggestions.length} suggested questions. Use arrow keys to navigate, Enter to select, or Escape to close.</span>
  </div>;
}
