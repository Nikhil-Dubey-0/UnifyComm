"use client";

import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { ChannelIcon } from "@/components/badges";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Channel, Consent, Preference } from "@/lib/api/client";
import { CHANNEL_LABEL } from "@/lib/format";
import { useUpdatePreference } from "@/lib/queries";
import { cn } from "@/lib/utils";

export const CHANNELS: Channel[] = ["whatsapp", "sms", "email"];

export const CONSENT_LABEL: Record<Consent, string> = {
  opted_in: "Opted in",
  opted_out: "Opted out",
  unknown: "Unknown",
};

const CONSENT_STYLE: Record<Consent, string> = {
  opted_in: "text-ok",
  opted_out: "text-urgent",
  unknown: "text-muted-foreground",
};

/** Consent and DND for one customer on one channel (ARCHITECTURE §7.6). Saves on change. */
export function PreferenceControl({
  customerId,
  channel,
  preference,
  showLabel = true,
}: {
  customerId: number;
  channel: Channel;
  preference: Preference | undefined;
  showLabel?: boolean;
}) {
  const update = useUpdatePreference(customerId);
  const consent: Consent = preference?.consent ?? "unknown";
  const dnd = preference?.dnd ?? false;
  const label = `${CHANNEL_LABEL[channel]} consent`;

  function save(next: { consent?: Consent; dnd?: boolean }) {
    update.mutate(
      { channel, consent: next.consent ?? consent, dnd: next.dnd ?? dnd },
      {
        onSuccess: () => toast.success(`${CHANNEL_LABEL[channel]} preference saved`),
        onError: (e) => toast.error("Could not save the preference", { description: e.message }),
      },
    );
  }

  return (
    <div className="flex items-center gap-2" data-testid={`pref-${channel}`}>
      {showLabel && (
        <span className="flex w-24 items-center gap-1.5 text-sm">
          <ChannelIcon channel={channel} />
          {CHANNEL_LABEL[channel]}
        </span>
      )}
      <Select value={consent} onValueChange={(v) => save({ consent: v as Consent })}>
        <SelectTrigger
          size="sm"
          aria-label={label}
          className={cn("h-7 w-28 text-xs font-medium", CONSENT_STYLE[consent])}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(CONSENT_LABEL) as Consent[]).map((c) => (
            <SelectItem key={c} value={c}>
              {CONSENT_LABEL[c]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <label className="flex cursor-pointer items-center gap-1.5 text-xs select-none">
        <input
          type="checkbox"
          checked={dnd}
          onChange={(e) => save({ dnd: e.target.checked })}
          aria-label={`${CHANNEL_LABEL[channel]} DND`}
          className="size-3.5 accent-[var(--high)]"
        />
        <span className={cn(dnd ? "font-semibold text-[oklch(0.5_0.13_62)]" : "text-muted-foreground")}>
          DND
        </span>
      </label>
      {update.isPending && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
    </div>
  );
}
