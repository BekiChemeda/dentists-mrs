import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";

// Amharic (am) and Afaan Oromo (om) resource files will be added alongside en.json.
// All user-facing text goes through t(); no strings are hard-coded in components.
void i18n.use(initReactI18next).init({
  resources: { en: { translation: en } },
  lng: "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false }, // React already escapes output
  returnNull: false,
});

export default i18n;
