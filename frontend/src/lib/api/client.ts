import createClient from "openapi-fetch";

import { clearSession, getToken } from "@/lib/auth";

import type { components, paths } from "./schema";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Schemas = components["schemas"];
export type Agent = Schemas["AgentOut"];
export type AiResult = Schemas["AiResultOut"];
export type Channel = Schemas["Channel"];
export type ComplianceCheck = Schemas["ComplianceCheckOut"];
export type ComplianceLogItem = Schemas["ComplianceLogItem"];
export type Consent = Schemas["Consent"];
export type ConversationDetail = Schemas["ConversationDetail"];
export type ConversationListItem = Schemas["ConversationListItem"];
export type ConversationOut = Schemas["ConversationOut"];
export type ConversationStatus = Schemas["ConversationStatus"];
export type CustomerDetail = Schemas["CustomerDetail"];
export type CustomerWithContacts = Schemas["CustomerWithContacts"];
export type DeliveryStatus = Schemas["DeliveryStatus"];
export type Draft = Schemas["DraftOut"];
export type Message = Schemas["MessageWithAnalysis"];
export type Preference = Schemas["PreferenceOut"];
export type Priority = Schemas["Priority"];
export type SendResponse = Schemas["SendResponse"];
export type SimulatorContact = Schemas["SimulatorContact"];
export type SimulatorThreadMessage = Schemas["SimulatorThreadMessage"];
export type Summary = Schemas["SummaryOut"];
export type SummaryJob = Schemas["SummaryJobOut"];

/** An API failure in the backend's `{"error": {"code", "message"}}` shape. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const api = createClient<paths>({ baseUrl: API_URL });

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    // An expired or revoked token ends the session; the workspace guard redirects to login.
    if (response.status === 401 && getToken()) clearSession();
    return response;
  },
});

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function call<T>(request: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await request;
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the UnifyComm API.");
  }
  if (!result.response.ok) {
    const body = result.error as { error?: { code?: string; message?: string } } | undefined;
    throw new ApiError(
      result.response.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? result.response.statusText,
    );
  }
  return result.data as T;
}
