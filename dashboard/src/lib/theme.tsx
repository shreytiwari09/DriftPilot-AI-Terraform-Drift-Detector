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

/** Colours for the charts (SVG), picked per theme. Severity hues each mean something; everything else is neutral. */
export const palette = (dark: boolean) => ({
  critical: dark ? '#e5484d' : '#dc2626',
  high: dark ? '#e0803c' : '#d9691e',
  medium: dark ? '#d9a93f' : '#ca8a04',
  low: dark ? '#85858b' : '#8a8a8a',
  brand: dark ? '#58a6ff' : '#1f6feb',
  neutral: dark ? '#6b6b70' : '#a3a3a3',
  grid: dark ? 'rgba(237,237,237,0.08)' : 'rgba(23,23,23,0.08)',
  cursor: dark ? 'rgba(237,237,237,0.05)' : 'rgba(23,23,23,0.04)',
  text: dark ? '#85858b' : '#737373',
  surface: dark ? '#19191b' : '#ffffff',
});
