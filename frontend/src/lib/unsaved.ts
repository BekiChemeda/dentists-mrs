import { useEffect } from "react";

/**
 * Forms with unsaved work register here. The app shell asks before signing out or following a link
 * while anything is unsaved, and the browser asks before the tab is closed or reloaded.
 */
const unsaved = new Set<string>();

export function hasUnsaved(): boolean {
  return unsaved.size > 0;
}

export function clearUnsaved(): void {
  unsaved.clear();
}

export function useUnsavedGuard(key: string, isUnsaved: boolean): void {
  useEffect(() => {
    if (!isUnsaved) return;
    unsaved.add(key);
    const onUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      unsaved.delete(key);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [key, isUnsaved]);
}
