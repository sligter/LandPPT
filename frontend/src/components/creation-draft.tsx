import { createContext, useContext, useRef, useState, type MutableRefObject, type ReactNode, type Dispatch, type SetStateAction } from 'react';
import type { ApiData } from '../api';
import type { ChatTurn } from './creation-assistant';

type Draft = { fields?: ApiData; files: File[]; sourceTab: string; locked: boolean; chat?: ChatTurn[]; chatOpen?: boolean };
type Feedback = { pending: boolean; error: string; redirect: string };
type CreationSession = { draft: MutableRefObject<Draft>; feedback: Feedback; setFeedback: Dispatch<SetStateAction<Feedback>> };
const Context = createContext<CreationSession | null>(null);

// Memory only: the app keys this provider by account and role. Ordinary page
// navigation keeps the draft, while logout/account changes discard it.
export function CreationDraftProvider({ children }: { children: ReactNode }) {
  const draft = useRef<Draft>({ files: [], sourceTab: 'manual', locked: false });
  const [feedback, setFeedback] = useState<Feedback>({ pending: false, error: '', redirect: '' });
  return <Context.Provider value={{ draft, feedback, setFeedback }}>{children}</Context.Provider>;
}

export function useCreationDraft() {
  const session = useContext(Context);
  if (!session) throw new Error('Creation session is unavailable');
  return session;
}
