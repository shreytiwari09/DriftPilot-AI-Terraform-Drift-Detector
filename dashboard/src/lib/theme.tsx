import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';
const KEY = 'driftpilot-theme';

function stored(): ThemeChoice {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

const systemDark = () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;

interface ThemeState {
  choice: ThemeChoice;
  dark: boolean;
  toggle: () => void;
}

const Ctx = createContext<ThemeState>({ choice: 'system', dark: false, toggle: () => undefined });
export const useTheme = () => useContext(Ctx);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoice] = useState<ThemeChoice>(stored);
  const [prefersDark, setPrefersDark] = useState(systemDark);
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return;
    const on = () => setPrefersDark(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  const dark = choice === 'dark' || (choice === 'system' && prefersDark);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  }, [dark]);
  const toggle = useCallback(() => {
    const next: ThemeChoice = dark ? 'light' : 'dark';
    setChoice(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      /* private window: the choice just lasts until the page closes */
    }
  }, [dark]);
  const value = useMemo(() => ({ choice, dark, toggle }), [choice, dark, toggle]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Colours for the charts (SVG), picked per theme. Same meaning in both: red worst, grey least. */
export const palette = (dark: boolean) => ({
  critical: dark ? '#f87171' : '#dc2626',
  high: dark ? '#fb923c' : '#ea580c',
  medium: dark ? '#fbbf24' : '#ca8a04',
  low: dark ? '#94a3b8' : '#64748b',
  brand: dark ? '#5b9bff' : '#1f6feb',
  teal: dark ? '#2dd4bf' : '#0d9488',
  grid: dark ? '#243049' : '#e2e8f0',
  text: dark ? '#94a3b8' : '#5b6678',
  surface: dark ? '#111a2b' : '#ffffff',
});
