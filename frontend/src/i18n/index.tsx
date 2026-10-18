import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { he, type Entry, type MessageKey, type Messages } from "./locales/he";
import { en } from "./locales/en";
import { ar } from "./locales/ar";
import { ru } from "./locales/ru";

export type Lang = "he" | "en" | "ar" | "ru";
export type Dir = "rtl" | "ltr";
export type { MessageKey };

/** Languages offered in the UI. `name` is written in the language itself, as in a language picker. */
export const LANGS: { code: Lang; name: string; dir: Dir; locale: string }[] = [
  { code: "he", name: "עברית", dir: "rtl", locale: "he-IL" },
  { code: "en", name: "English", dir: "ltr", locale: "en-US" },
  { code: "ar", name: "العربية", dir: "rtl", locale: "ar" },
  { code: "ru", name: "Русский", dir: "ltr", locale: "ru-RU" },
];

const MESSAGES: Record<Lang, Messages> = { he, en, ar, ru };
const STORAGE_KEY = "lang";
const DEFAULT_LANG: Lang = "he";

type Params = Record<string, string | number>;
export type Translate = (key: MessageKey, params?: Params) => string;

export function hasKey(key: string): key is MessageKey {
  return key in he;
}

function isLang(v: unknown): v is Lang {
  return LANGS.some((l) => l.code === v);
}

/** Saved choice, else the first browser language we support, else Hebrew. */
function initialLang(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (isLang(saved)) return saved;
  } catch {
    /* storage blocked */
  }
  for (const tag of navigator.languages ?? []) {
    const base = tag.toLowerCase().split("-")[0];
    if (isLang(base)) return base;
    if (base === "iw") return "he";
  }
  return DEFAULT_LANG;
}

function applyToDocument(lang: Lang) {
  const meta = LANGS.find((l) => l.code === lang)!;
  document.documentElement.lang = lang;
  document.documentElement.dir = meta.dir;
}

/** Picks the plural form for `count`; a language lists only the forms it uses, `other` is the fallback. */
function resolve(entry: Entry, rules: Intl.PluralRules, params?: Params): string {
  if (typeof entry === "string") return entry;
  const count = Number(params?.count ?? 0);
  if (count === 0 && entry.zero !== undefined) return entry.zero;
  return entry[rules.select(count)] ?? entry.other;
}

function interpolate(text: string, params?: Params): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k]) : m));
}

interface I18n {
  lang: Lang;
  dir: Dir;
  /** BCP 47 locale for Intl / toLocale* calls. */
  locale: string;
  setLang: (lang: Lang) => void;
  t: Translate;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const l = initialLang();
    applyToDocument(l);
    return l;
  });

  useEffect(() => applyToDocument(lang), [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* storage blocked: the choice lasts for this visit only */
    }
  }, []);

  const value = useMemo<I18n>(() => {
    const meta = LANGS.find((l) => l.code === lang)!;
    const messages = MESSAGES[lang];
    const rules = new Intl.PluralRules(meta.locale);
    const t: Translate = (key, params) => interpolate(resolve(messages[key] ?? he[key], rules, params), params);
    return { lang, dir: meta.dir, locale: meta.locale, setLang, t };
  }, [lang, setLang]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}
