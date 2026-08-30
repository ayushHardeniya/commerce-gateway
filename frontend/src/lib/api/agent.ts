/**
 * Typed client for `/api/agent` — mirrors `app.agents.schemas`. Each call is
 * one independent request: the backend holds no conversation history across
 * calls (see `ARCHITECTURE.md`), so the frontend's chat log is a client-side
 * transcript of independent turns, not evidence of server-side memory.
 */

import { apiPost } from "./client";

export type ToolCallRecord = {
  tool_name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  output: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
};

export type AgentChatResponse = {
  reply: string;
  tool_calls: ToolCallRecord[];
};

export async function chatWithAgent(message: string): Promise<AgentChatResponse> {
  return apiPost<AgentChatResponse>("/api/agent/chat", { message });
}
