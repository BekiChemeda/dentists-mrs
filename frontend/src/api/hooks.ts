import i18n from "../i18n";
import { toast } from "../ui";
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api } from "./client";

/** GET with caching. Pass `null` as path to disable (e.g. until an ID is known). */
export function useGet<T>(
  key: QueryKey,
  path: string | null,
  options: { refetchInterval?: number; staleTime?: number } = {},
) {
  return useQuery({
    queryKey: key,
    queryFn: () => api.get<T>(path as string),
    enabled: path !== null,
    refetchInterval: options.refetchInterval,
    staleTime: options.staleTime,
  });
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
