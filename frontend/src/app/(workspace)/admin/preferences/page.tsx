"use client";

import { BadgeCheck, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Avatar } from "@/components/badges";
import { CHANNELS, PreferenceControl } from "@/components/customers/preference-control";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { CHANNEL_LABEL } from "@/lib/format";
import { useCustomers } from "@/lib/queries";

/** Consent and DND for every customer and channel (ARCHITECTURE §7.6, §10). */
export default function PreferencesPage() {
  const [q, setQ] = useState("");
  const customers = useCustomers(q.trim());

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 p-8">
        <header className="flex flex-wrap items-end gap-4">
          <div className="flex-1">
            <h1 className="text-xl font-semibold">Channel preferences</h1>
            <p className="text-sm text-muted-foreground">
              Consent and DND per channel. Changes apply to the next message and are recorded in
              the audit log. DND here is local data standing in for the national registry.
            </p>
          </div>
          <div className="relative w-64">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name, phone or email"
              aria-label="Search customers"
              className="pl-8"
            />
          </div>
        </header>

        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Customer</th>
                {CHANNELS.map((c) => (
                  <th key={c} className="px-3 py-2 font-medium">
                    {CHANNEL_LABEL[c]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {customers.isLoading &&
                [0, 1, 2].map((i) => (
                  <tr key={i}>
                    <td colSpan={4} className="px-4 py-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))}
              {customers.data?.items.map((customer) => (
                <tr key={customer.id} data-testid="preferences-row" data-customer-id={customer.id}>
                  <td className="px-4 py-2.5">
                    <Link
                      href={`/customers/${customer.id}`}
                      className="flex items-center gap-2.5 hover:underline"
                    >
                      <Avatar name={customer.display_name} className="size-7 text-[10px]" />
                      <span className="font-medium">{customer.display_name}</span>
                      {customer.verified && <BadgeCheck className="size-3.5 text-primary" />}
                    </Link>
                  </td>
                  {CHANNELS.map((channel) => (
                    <td key={channel} className="px-3 py-2.5">
                      <PreferenceControl
                        customerId={customer.id}
                        channel={channel}
                        preference={customer.preferences.find((p) => p.channel === channel)}
                        showLabel={false}
                      />
                    </td>
                  ))}
                </tr>
              ))}
              {customers.data?.items.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                    No customers match.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
