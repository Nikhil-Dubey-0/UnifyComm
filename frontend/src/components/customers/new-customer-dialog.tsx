"use client";

import { Loader2, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { useCreateCustomer } from "@/lib/queries";

/**
 * Register a known customer (KYC onboarding, ARCHITECTURE §10 POST /customers). Their
 * phone and email then resolve to this one customer on every channel.
 */
export function NewCustomerDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreateCustomer();
  const ready = name.trim() && (phone.trim() || email.trim());

  function reset(next: boolean) {
    setOpen(next);
    if (next) {
      setName("");
      setPhone("");
      setEmail("");
      setError(null);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setError(null);
    create.mutate(
      { display_name: name.trim(), phone: phone.trim(), email: email.trim() },
      {
        onSuccess: (customer) => {
          toast.success(`${customer.display_name} registered`);
          setOpen(false);
          router.push(`/customers/${customer.id}`);
        },
        onError: (err) =>
          setError(err instanceof ApiError ? err.message : "Could not register the customer."),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button>
          <UserPlus /> New customer
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Register a customer</DialogTitle>
            <DialogDescription>
              As at account opening (KYC): the bank records who owns this phone number and email.
              Messages from either, on WhatsApp, SMS or email, then join one conversation.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="nc-name">Full name</Label>
            <Input id="nc-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nc-phone">Mobile number</Label>
            <Input
              id="nc-phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+91 98xxx xxxxx"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="nc-email">Email</Label>
            <Input
              id="nc-email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Consent starts as Unknown: service replies are allowed, proactive messages need an
            opt-in on the customer page.
          </p>
          {error && (
            <p role="alert" className="rounded-md bg-destructive/8 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => reset(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!ready || create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" />}
              Register
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
