"use client";

import { useParams } from "next/navigation";

import { ConversationView } from "@/components/conversation/conversation-view";

export default function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  return <ConversationView key={conversationId} id={Number(conversationId)} />;
}
