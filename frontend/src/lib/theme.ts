/**
 * Light / dark theme. The choice is per browser (localStorage) and defaults to the device setting.
 * Applied as data-theme on <html>; styles.css holds the palettes. Printing always uses the light one.
 */
import { useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "mrs.theme";
const media =
  typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

export function storedTheme(): ThemeChoice {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice === "system") return media?.matches ? "dark" : "light";
  return choice;
}

export function applyTheme(choice: ThemeChoice = storedTheme()): void {
  const theme = resolveTheme(choice);
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "dark" ? "#10121a" : "#f6f7fc");
}

/** Call once at start-up: applies the saved choice and follows the device when set to "system". */
export function initTheme(): void {
  applyTheme();
  media?.addEventListener?.("change", () => {
    if (storedTheme() === "system") applyTheme("system");
  });
}

export function useTheme(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  useEffect(() => {
    applyTheme(choice);
  }, [choice]);
  const set = (c: ThemeChoice) => {
    try {
      if (c === "system") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, c);
    } catch {
      /* storage unavailable: the choice lasts for this page only */
    }
    setChoice(c);
  };
  return [choice, set];
}
