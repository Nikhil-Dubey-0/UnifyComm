"use client";

import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";

import { clearSession } from "@/lib/auth";

/**
 * One WebSocket per browser session (ARCHITECTURE §11). Events are invalidation hints
 * only: they mark queries stale and TanStack Query refetches over REST. Payloads are
 * never applied as state.
 */

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";
const BACKOFF_START_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const POLICY_VIOLATION = 1008; // invalid token

export type LiveStatus = "connecting" | "open" | "closed";

type ServerEvent = {
  type: string;
  conversation_id?: number;
  message_id?: number;
};

let status: LiveStatus = "closed";
const listeners = new Set<() => void>();

function setStatus(next: LiveStatus): void {
  status = next;
  for (const listener of listeners) listener();
}

export function applyEvent(qc: QueryClient, event: ServerEvent): void {
  if (event.type === "hello" || event.type === "ping") return;
  if (event.type === "resync") {
    qc.invalidateQueries();
    return;
  }
  qc.invalidateQueries({ queryKey: ["conversations"] });
  if (event.conversation_id !== undefined) {
    qc.invalidateQueries({ queryKey: ["conversation", event.conversation_id] });
  }
  if (event.type.startsWith("message.")) {
    qc.invalidateQueries({ queryKey: ["simulator-thread"] });
  }
  if (event.type.startsWith("conversation.")) {
    qc.invalidateQueries({ queryKey: ["customer"] });
  }
}

class LiveSocket {
  private socket: WebSocket | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  private connectedBefore = false;
  private stopped = true;

  constructor(
    private readonly token: string,
    private readonly qc: QueryClient,
  ) {}

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
    setStatus("closed");
  }

  private open(): void {
    setStatus("connecting");
    const socket = new WebSocket(`${WS_URL}?token=${encodeURIComponent(this.token)}`);
    this.socket = socket;

    socket.onopen = () => {
      setStatus("open");
      this.attempts = 0;
      // Anything may have changed while we were away: refetch everything.
      if (this.connectedBefore) this.qc.invalidateQueries();
      this.connectedBefore = true;
    };
    socket.onmessage = (msg) => {
      try {
        applyEvent(this.qc, JSON.parse(msg.data as string) as ServerEvent);
      } catch {
        // Ignore malformed frames.
      }
    };
    socket.onclose = (event) => {
      this.socket = null;
      setStatus("closed");
      if (this.stopped) return;
      if (event.code === POLICY_VIOLATION) {
        clearSession();
        return;
      }
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    const base = Math.min(BACKOFF_MAX_MS, BACKOFF_START_MS * 2 ** this.attempts);
    const delay = base / 2 + Math.random() * (base / 2); // jitter
    this.attempts += 1;
    this.retryTimer = setTimeout(() => {
      if (!this.stopped) this.open();
    }, delay);
  }
}

/** Keep one live socket open while the agent is logged in. */
export function useLiveUpdates(token: string | null | undefined, qc: QueryClient): void {
  useEffect(() => {
    if (!token) return;
    const live = new LiveSocket(token, qc);
    live.start();
    return () => live.stop();
  }, [token, qc]);
}

export function useLiveStatus(): LiveStatus {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => status,
    () => "closed",
  );
}
