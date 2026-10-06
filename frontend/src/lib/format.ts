import type { Channel, ConversationStatus, DeliveryStatus, Priority } from "@/lib/api/client";

const TIMEZONE = "Asia/Kolkata"; // display in IST (CLAUDE.md)

const timeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TIMEZONE,
  hour: "2-digit",
  minute: "2-digit",
});
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TIMEZONE,
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const dayKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TIMEZONE });
const dayLabelFmt = new Intl.DateTimeFormat("en-IN", {
  timeZone: TIMEZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
});

export function formatTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso));
}

export function dayKey(iso: string): string {
  return dayKeyFmt.format(new Date(iso));
}

export function formatDay(iso: string): string {
  const key = dayKey(iso);
  const today = dayKeyFmt.format(new Date());
  const yesterday = dayKeyFmt.format(new Date(Date.now() - 86_400_000));
  if (key === today) return "Today";
  if (key === yesterday) return "Yesterday";
  return dayLabelFmt.format(new Date(iso));
}

/** "now", "4m", "3h", "2d" */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function percent(confidence: number | null | undefined): string {
  return confidence == null ? "–" : `${Math.round(confidence * 100)}%`;
}

export function humanize(label: string): string {
  if (label === "oos") return "Out of scope";
  const text = label.replace(/[_?]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const CHANNEL_LABEL: Record<Channel, string> = {
  whatsapp: "WhatsApp",
  sms: "SMS",
  email: "Email",
};

export const PRIORITY_LABEL: Record<Priority, string> = {
  urgent: "Urgent",
  high: "High",
  normal: "Normal",
  low: "Low",
};

export const STATUS_LABEL: Record<ConversationStatus, string> = {
  open: "Open",
  pending: "Pending",
  resolved: "Resolved",
  closed: "Closed",
};

export const DELIVERY_LABEL: Record<DeliveryStatus, string> = {
  checking: "Checking",
  blocked: "Blocked",
  queued: "Queued",
  sent: "Sent",
  delivered: "Delivered",
  failed: "Failed",
};

/** Queues from ARCHITECTURE §7.3 (small_talk has no queue). */
export const CATEGORY_QUEUES: { key: string; label: string }[] = [
  { key: "fraud_security", label: "Fraud & Security" },
  { key: "payments_billing", label: "Payments & Billing" },
  { key: "transfers_topups", label: "Transfers & Top-ups" },
  { key: "cards", label: "Cards" },
  { key: "account_access", label: "Account & Identity" },
  { key: "loans_credit", label: "Loans & Credit" },
  { key: "general_banking", label: "General" },
  { key: "out_of_scope", label: "Other" },
];

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (/^[+\d]/.test(parts[0])) return "#";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}
