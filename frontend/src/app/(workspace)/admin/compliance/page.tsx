"use client";

import { CheckCircle2, Loader2, ShieldX } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ChannelIcon } from "@/components/badges";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { CHANNEL_LABEL, formatDateTime } from "@/lib/format";
import { type ComplianceFilters, useComplianceChecks, useComplianceRules } from "@/lib/queries";
import { cn } from "@/lib/utils";

type Outcome = "blocked" | "passed" | "all";
const ALL_RULES = "all";

const PURPOSE_LABEL = { service_reply: "Service reply", proactive: "Proactive" };

/** Every stored compliance check, newest first (ARCHITECTURE §7.6, §10). */
export default function ComplianceLogPage() {
  const [outcome, setOutcome] = useState<Outcome>("blocked");
  const [ruleId, setRuleId] = useState(ALL_RULES);
  const rules = useComplianceRules();
  const filters: ComplianceFilters = {
    ...(outcome !== "all" && { passed: outcome === "passed" }),
    ...(ruleId !== ALL_RULES && { rule_id: ruleId }),
  };
  const checks = useComplianceChecks(filters);
  const items = checks.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-8">
        <header className="flex flex-wrap items-end gap-4">
          <div className="flex-1">
            <h1 className="text-xl font-semibold">Compliance log</h1>
            <p className="text-sm text-muted-foreground">
              Every outbound message is checked against every rule before a provider is called.
              Blocked messages are recorded here and never sent.
            </p>
          </div>
          <Select value={outcome} onValueChange={(v) => setOutcome(v as Outcome)}>
            <SelectTrigger aria-label="Outcome" className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="blocked">Blocked only</SelectItem>
              <SelectItem value="passed">Passed only</SelectItem>
              <SelectItem value="all">All checks</SelectItem>
            </SelectContent>
          </Select>
          <Select value={ruleId} onValueChange={setRuleId}>
            <SelectTrigger aria-label="Rule" className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_RULES}>All rules</SelectItem>
              {rules.data?.map((r) => (
                <SelectItem key={r.rule_id} value={r.rule_id}>
                  {r.rule_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </header>

        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm" data-testid="compliance-log">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Checked</th>
                <th className="px-3 py-2 font-medium">Customer</th>
                <th className="px-3 py-2 font-medium">Message</th>
                <th className="px-3 py-2 font-medium">Rule</th>
                <th className="px-3 py-2 font-medium">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {checks.isLoading &&
                [0, 1, 2].map((i) => (
                  <tr key={i}>
                    <td colSpan={5} className="px-4 py-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))}
              {items.map((c) => (
                <tr
                  key={c.id}
                  data-testid="compliance-row"
                  data-rule={c.rule_id}
                  data-passed={c.passed}
                  className="align-top"
                >
                  <td className="tabular px-4 py-2.5 whitespace-nowrap text-muted-foreground">
                    {formatDateTime(c.evaluated_at)}
                  </td>
                  <td className="px-3 py-2.5">
                    <Link href={`/customers/${c.customer.id}`} className="hover:underline">
                      {c.customer.display_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5">
                    <Link
                      href={`/inbox/${c.message.conversation_id}`}
                      className="inline-flex items-center gap-1.5 hover:underline"
                    >
                      <ChannelIcon channel={c.message.channel} />
                      {CHANNEL_LABEL[c.message.channel]} · #{c.message.conversation_id}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      {c.message.purpose ? PURPOSE_LABEL[c.message.purpose] : "–"}
                      {" · "}
                      {c.message.is_template
                        ? "acknowledgement"
                        : c.message.sender_type === "agent"
                          ? "agent"
                          : c.message.sender_type}
                    </p>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs">{c.rule_id}</td>
                  <td className="px-3 py-2.5">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 text-xs font-medium",
                        c.passed ? "text-ok" : "text-destructive",
                      )}
                    >
                      {c.passed ? (
                        <CheckCircle2 className="size-3.5" />
                      ) : (
                        <ShieldX className="size-3.5" />
                      )}
                      {c.passed ? "Passed" : "Blocked"}
                    </span>
                    {c.reason && <p className="mt-0.5 max-w-80 text-xs">{c.reason}</p>}
                  </td>
                </tr>
              ))}
              {!checks.isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                    No checks match these filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {checks.hasNextPage && (
          <div className="flex justify-center">
            <Button
              variant="outline"
              onClick={() => checks.fetchNextPage()}
              disabled={checks.isFetchingNextPage}
            >
              {checks.isFetchingNextPage && <Loader2 className="animate-spin" />}
              Load more
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
