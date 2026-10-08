"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  api,
  call,
  type Channel,
  type Consent,
  type ConversationStatus,
  type Priority,
} from "@/lib/api/client";

/** Query keys (CLAUDE.md). Events from lib/ws.ts invalidate these prefixes. */
export const keys = {
  conversations: (filters?: ConversationFilters) =>
    filters ? (["conversations", filters] as const) : (["conversations"] as const),
  conversation: (id: number) => ["conversation", id] as const,
  customer: (id: number) => ["customer", id] as const,
  customers: (q: string) => ["customers", q] as const,
  simulatorThread: (channel: Channel, address: string) =>
    ["simulator-thread", channel, address] as const,
  simulatorContacts: ["simulator-contacts"] as const,
  agents: ["agents"] as const,
  complianceChecks: (filters?: ComplianceFilters) =>
    filters ? (["compliance-checks", filters] as const) : (["compliance-checks"] as const),
  health: ["health"] as const,
};

export type ComplianceFilters = { passed?: boolean; rule_id?: string };

export type ConversationFilters = {
  status?: ConversationStatus;
  category?: string;
  priority?: Priority;
  assignee?: string;
  q?: string;
};

const PAGE_SIZE = 30;

export function useConversations(filters: ConversationFilters) {
  return useInfiniteQuery({
    queryKey: keys.conversations(filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(
        api.GET("/api/conversations", {
          params: { query: { ...filters, cursor: pageParam ?? undefined, limit: PAGE_SIZE } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useConversation(id: number) {
  return useQuery({
    queryKey: keys.conversation(id),
    queryFn: () =>
      call(
        api.GET("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
  });
}

export function useCustomer(id: number) {
  return useQuery({
    queryKey: keys.customer(id),
    queryFn: () =>
      call(api.GET("/api/customers/{customer_id}", { params: { path: { customer_id: id } } })),
  });
}

export function useCustomers(q: string) {
  return useQuery({
    queryKey: keys.customers(q),
    queryFn: () =>
      call(api.GET("/api/customers", { params: { query: { q: q || undefined, limit: 50 } } })),
  });
}

export function useAgents() {
  return useQuery({
    queryKey: keys.agents,
    queryFn: () => call(api.GET("/api/agents")),
    staleTime: 5 * 60_000,
  });
}

export function useSimulatorContacts() {
  return useQuery({
    queryKey: keys.simulatorContacts,
    queryFn: () => call(api.GET("/api/simulator/contacts")),
  });
}

export function useSimulatorThread(channel: Channel, address: string) {
  return useQuery({
    queryKey: keys.simulatorThread(channel, address),
    queryFn: () =>
      call(api.GET("/api/simulator/thread", { params: { query: { channel, address } } })),
    enabled: address.trim().length > 0,
  });
}

export type SendInput = {
  channel: Channel;
  body: string;
  idempotencyKey: string;
  draftId?: number | null;
};

export function useSendReply(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channel, body, idempotencyKey, draftId }: SendInput) =>
      call(
        api.POST("/api/conversations/{conversation_id}/send", {
          params: {
            path: { conversation_id: conversationId },
            header: { "idempotency-key": idempotencyKey },
          },
          body: { channel, body, draft_id: draftId ?? null },
        }),
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.conversation(conversationId) });
      qc.invalidateQueries({ queryKey: keys.conversations() });
    },
  });
}

export function usePatchConversation(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: { status?: ConversationStatus; assignee_id?: number | null }) =>
      call(
        api.PATCH("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: conversationId } },
          body: patch,
        }),
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.conversation(conversationId) });
      qc.invalidateQueries({ queryKey: keys.conversations() });
    },
  });
}

export function useRetryDelivery(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (messageId: number) =>
      call(
        api.POST("/api/messages/{message_id}/retry", {
          params: { path: { message_id: messageId } },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.conversation(conversationId) }),
  });
}

export function useLinkCustomer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ targetId, sourceId }: { targetId: number; sourceId: number }) =>
      call(
        api.POST("/api/customers/{customer_id}/link", {
          params: { path: { customer_id: targetId } },
          body: { source_customer_id: sourceId },
        }),
      ),
    onSuccess: () => qc.invalidateQueries(),
  });
}

export function useSimulatorSend() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      channel: Channel;
      from: string;
      body: string;
      sender_name?: string;
      subject?: string;
    }) => call(api.POST("/api/channels/simulator/inbound", { body: input })),
    onSettled: (_data, _err, input) =>
      qc.invalidateQueries({ queryKey: ["simulator-thread", input.channel] }),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => call(api.GET("/api/health")),
    // The heartbeat and channel health change without events: poll.
    refetchInterval: 15_000,
  });
}

/** POST /drafts. 503 llm_unavailable surfaces as an ApiError the composer shows inline. */
export function useGenerateDraft(conversationId: number) {
  return useMutation({
    mutationFn: (input: { channel: Channel; instructions?: string }) =>
      call(
        api.POST("/api/conversations/{conversation_id}/drafts", {
          params: { path: { conversation_id: conversationId } },
          body: { channel: input.channel, instructions: input.instructions || null },
        }),
      ),
  });
}

export function useSummarize(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      call(
        api.POST("/api/conversations/{conversation_id}/summarize", {
          params: { path: { conversation_id: conversationId } },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.conversation(conversationId) }),
  });
}

export function useUpdatePreference(customerId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { channel: Channel; consent: Consent; dnd: boolean }) =>
      call(
        api.PUT("/api/customers/{customer_id}/preferences", {
          params: { path: { customer_id: customerId } },
          body: input,
        }),
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.customer(customerId) });
      qc.invalidateQueries({ queryKey: ["customers"] });
    },
  });
}

export function useOutreach(customerId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channel, body, idempotencyKey }: SendInput) =>
      call(
        api.POST("/api/customers/{customer_id}/outreach", {
          params: {
            path: { customer_id: customerId },
            header: { "idempotency-key": idempotencyKey },
          },
          body: { channel, body },
        }),
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.customer(customerId) });
      qc.invalidateQueries({ queryKey: keys.conversations() });
    },
  });
}

export function useComplianceRules() {
  return useQuery({
    queryKey: ["compliance-rules"],
    queryFn: () => call(api.GET("/api/compliance/rules")),
    staleTime: 10 * 60_000,
  });
}

export function useComplianceChecks(filters: ComplianceFilters) {
  return useInfiniteQuery({
    queryKey: keys.complianceChecks(filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      call(
        api.GET("/api/compliance/checks", {
          params: { query: { ...filters, cursor: pageParam ?? undefined, limit: 50 } },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useMetrics(days: number) {
  return useQuery({
    queryKey: ["metrics", days],
    queryFn: () => call(api.GET("/api/metrics/summary", { params: { query: { days } } })),
    refetchInterval: 60_000,
  });
}
