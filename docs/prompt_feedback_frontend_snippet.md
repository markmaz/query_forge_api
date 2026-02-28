# Prompt Feedback React Snippet

```tsx
import { useState } from "react";

type Vote = "up" | "down";

type Props = {
  workspaceId: string;
  traceId?: string;
  normalizedPrompt?: string;
  promptText?: string;
  responseJson: Record<string, unknown>;
  meta?: {
    model?: string;
    timings_ms?: Record<string, unknown>;
    domain_id?: number;
    domain_version?: number;
    intent?: string;
  };
};

export function PromptFeedbackButtons({
  workspaceId,
  traceId,
  normalizedPrompt,
  promptText,
  responseJson,
  meta,
}: Props) {
  const [selectedVote, setSelectedVote] = useState<Vote | null>(null);

  async function handleThumb(vote: Vote) {
    // optimistic highlight
    setSelectedVote(vote);
    try {
      const response = await fetch("/api/v1/prompt-feedback", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Workspace-Id": workspaceId,
        },
        credentials: "include",
        body: JSON.stringify({
          workspace_id: workspaceId,
          trace_id: traceId,
          vote,
          normalized_prompt: normalizedPrompt,
          prompt_text: promptText,
          response_json: responseJson,
          meta,
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to persist feedback: ${response.status}`);
      }
    } catch (error) {
      console.error(error);
      // optional rollback on failure
      setSelectedVote(null);
    }
  }

  return (
    <div>
      <button
        type="button"
        aria-pressed={selectedVote === "up"}
        onClick={() => handleThumb("up")}
      >
        👍
      </button>
      <button
        type="button"
        aria-pressed={selectedVote === "down"}
        onClick={() => handleThumb("down")}
      >
        👎
      </button>
    </div>
  );
}
```
