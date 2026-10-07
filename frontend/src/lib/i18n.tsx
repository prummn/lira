import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import zh from '../locales/zh-CN.json'
import en from '../locales/en-US.json'
export type LocaleKey = keyof typeof zh
type Language = 'zh-CN' | 'en-US'
export type Theme = 'light' | 'dark' | 'system'
const UiContext = createContext({ t: (key: LocaleKey): string => zh[key], language: 'zh-CN' as Language, setLanguage: (_: Language) => {}, theme: 'system' as Theme, setTheme: (_: Theme) => {} })
export function UiProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => localStorage.getItem('riw-language') === 'en-US' ? 'en-US' : 'zh-CN')
  const [theme, setTheme] = useState<Theme>(() => { const saved = localStorage.getItem('riw-theme'); return saved === 'light' || saved === 'dark' ? saved : 'system' })
  useEffect(() => { localStorage.setItem('riw-language', language); document.documentElement.lang = language }, [language])
  useEffect(() => {
    localStorage.setItem('riw-theme', theme)
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => document.documentElement.classList.toggle('theme-dark', theme === 'dark' || (theme === 'system' && media.matches))
    apply(); media.addEventListener('change', apply); return () => media.removeEventListener('change', apply)
  }, [theme])
  return <UiContext.Provider value={{ t: key => (language === 'en-US' ? en : zh)[key], language, setLanguage, theme, setTheme }}>{children}</UiContext.Provider>
}
export const useUi = () => useContext(UiContext)
