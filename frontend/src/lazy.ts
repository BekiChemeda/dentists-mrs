import { lazy, type ComponentType } from "react";

const RELOAD_FLAG = "mrs-reloaded-for-update";

/**
 * React.lazy for a named export. After the server is upgraded, an open browser tab still refers to the
 * old file names, so loading a page fails once; then the tab reloads itself to get the new version.
 * The flag stops a reload loop when the server is simply unreachable.
 */
export function lazyPage<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M & string) {
  return lazy(async () => {
    try {
      const module = await load();
      try {
        sessionStorage.removeItem(RELOAD_FLAG);
      } catch {
        /* storage unavailable: nothing to clear */
      }
      return { default: module[name] as ComponentType };
    } catch (error) {
      let reloaded = false;
      try {
        reloaded = sessionStorage.getItem(RELOAD_FLAG) === "1";
        sessionStorage.setItem(RELOAD_FLAG, "1");
      } catch {
        reloaded = true;
      }
      if (!reloaded) window.location.reload();
      throw error;
    }
  });
}
