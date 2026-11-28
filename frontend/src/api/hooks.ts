import i18n from "../i18n";
import { toast } from "../ui";
import { useRef } from "react";
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api } from "./client";

/** Saved data younger than this is shown at once while it is refreshed; older data waits for the refresh. */
export const RECENT_MS = 10_000;

/**
 * GET with caching. Pass `null` as path to disable (e.g. until an ID is known).
 *
 * When a page opens, data kept from an earlier visit is shown only if it is recent and nothing has changed it
 * since (no save marked it out of date). Otherwise the page shows "Loading" until the fresh answer arrives, so
 * staff never see a paid invoice under "Open invoices" or a patient already sent home in the queue. Refreshes
 * while the page is open (polling, after a save) keep showing the current data, so typing is never interrupted.
 */
export function useGet<T>(
  key: QueryKey,
  path: string | null,
  options: { refetchInterval?: number; staleTime?: number } = {},
) {
  const client = useQueryClient();
  const hash = JSON.stringify(key);
  const opened = useRef<{ hash: string; at: number } | null>(null);
  if (opened.current?.hash !== hash) opened.current = { hash, at: Date.now() };
  const q = useQuery({
    queryKey: key,
    queryFn: () => api.get<T>(path as string),
    enabled: path !== null,
    refetchInterval: options.refetchInterval,
    staleTime: options.staleTime,
  });
  const fromBefore = q.data !== undefined && q.dataUpdatedAt < opened.current.at;
  const outdated =
    fromBefore &&
    q.isFetching &&
    (client.getQueryState(key)?.isInvalidated === true || opened.current.at - q.dataUpdatedAt > RECENT_MS);
  if (!outdated) return q;
  return { ...q, data: undefined, isLoading: true, isPending: true, isSuccess: false, status: "pending" } as typeof q;
}

/** A write that refreshes the listed query key prefixes when it succeeds, before reporting success. */
export function useAction<TVars, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  invalidate: QueryKey[] = [],
  onSuccess?: (result: TResult, vars: TVars) => void,
  successMessage: string | false = i18n.t("common.saved_toast", "Changes saved"),
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // The refreshed data is waited for, so when the toast appears (and a dialog closes) the page already
    // shows the change instead of the old state for a moment.
    onSuccess: async (result, vars) => {
      await Promise.all(invalidate.map((key) => client.invalidateQueries({ queryKey: key })));
      if (successMessage) toast(successMessage);
      onSuccess?.(result, vars);
    },
  });
}

export const post = <T>(path: string, body?: unknown) => api.post<T>(path, body);
export const patch = <T>(path: string, body: unknown) => api.patch<T>(path, body);
