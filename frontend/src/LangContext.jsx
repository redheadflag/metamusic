import { createContext, useContext, useState } from "react";
import { translations } from "./i18n.js";

const LangContext = createContext(null);

export function LangProvider({ children }) {
  const [lang, setLang] = useState("ru");
  const t = (key, ...args) => {
    const val = translations[lang]?.[key] ?? translations.en[key] ?? key;
    return typeof val === "function" ? val(...args) : val;
  };
  return (
    <LangContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  return useContext(LangContext);
}
