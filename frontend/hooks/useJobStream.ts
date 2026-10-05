"use client";

import { useEffect, useRef } from "react";
import { streamUrl } from "@/lib/api";
import type { Job } from "@/lib/types";

/** Subscribe to a job's Server-Sent Events while `enabled`. The server replays
 *  existing rows on connect; we only use the job snapshot and refetch rows via REST. */
export function useJobStream(
  jobId: number,
  enabled: boolean,
  onProgress: (job: Job) => void,
  onEnd: () => void,
) {
  const handlers = useRef({ onProgress, onEnd });
  handlers.current = { onProgress, onEnd };

  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(streamUrl(jobId));
    es.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as { job: Job };
        handlers.current.onProgress(data.job);
      } catch {
        /* ignore malformed event */
      }
    });
    es.addEventListener("end", () => {
      es.close();
      handlers.current.onEnd();
    });
    return () => es.close();
  }, [jobId, enabled]);
}
