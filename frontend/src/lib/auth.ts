"use client";

import { useSyncExternalStore } from "react";

import type { components } from "@/lib/api/schema";

type Agent = components["schemas"]["AgentOut"];
export type Session = { token: string; agent: Agent };

// Token lives in memory and sessionStorage: it survives a reload, not a closed tab.
const STORAGE_KEY = "unifycomm.session";

let session: Session | null = null;
let loaded = false;
const listeners = new Set<() => void>();

function load(): void {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    session = raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    session = null;
  }
}

function emit(): void {
  for (const listener of listeners) listener();
}

export function getToken(): string | null {
  load();
  return session?.token ?? null;
}

export function setSession(next: Session): void {
  session = next;
  loaded = true;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage unavailable (private mode): the in-memory session still works.
  }
  emit();
}

export function clearSession(): void {
  session = null;
  loaded = true;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * `undefined` while rendering on the server or hydrating (unknown yet),
 * `null` when logged out, otherwise the session.
 */
export function useSession(): Session | null | undefined {
  return useSyncExternalStore(
    subscribe,
    () => {
      load();
      return session;
    },
    () => undefined,
  );
}
