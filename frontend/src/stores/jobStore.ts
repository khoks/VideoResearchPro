import { create } from 'zustand';

export type ToastKind = 'error' | 'success' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

export type Theme = 'light' | 'dark';

export type AppTab =
  | 'submit'
  | 'jobs'
  | 'library'
  | 'library-qa'
  | 'qa-history'
  | 'exports'
  | 'author'
  | 'echo'
  | 'subscription'
  | 'ai-models';

const THEME_KEY = 'vrp:theme';

function loadInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'light';
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === 'dark' || saved === 'light') return saved;
  if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'dark';
  return 'light';
}

function applyTheme(theme: Theme) {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', theme);
  }
}

interface JobStore {
  activeJobId: string | null;
  isReportModalOpen: boolean;
  activeTab: AppTab;
  theme: Theme;
  toasts: Toast[];
  setActiveJob: (id: string | null) => void;
  openReportModal: () => void;
  closeReportModal: () => void;
  setActiveTab: (tab: AppTab) => void;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
  pushToast: (kind: ToastKind, message: string) => void;
  dismissToast: (id: number) => void;
}

const initialTheme = loadInitialTheme();
applyTheme(initialTheme);

let toastCounter = 0;

export const useJobStore = create<JobStore>((set, get) => ({
  activeJobId: null,
  isReportModalOpen: false,
  activeTab: 'submit',
  theme: initialTheme,
  toasts: [],
  setActiveJob: (id) => set({ activeJobId: id }),
  openReportModal: () => set({ isReportModalOpen: true }),
  closeReportModal: () => set({ isReportModalOpen: false }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  toggleTheme: () => {
    const next: Theme = get().theme === 'light' ? 'dark' : 'light';
    window.localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
    set({ theme: next });
  },
  setTheme: (theme) => {
    window.localStorage.setItem(THEME_KEY, theme);
    applyTheme(theme);
    set({ theme });
  },
  pushToast: (kind, message) => {
    const id = ++toastCounter;
    set((s) => ({ toasts: [...s.toasts, { id, kind, message }] }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 5000);
  },
  dismissToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));
