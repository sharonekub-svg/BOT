"use client";

import { useEffect, useRef, useState } from "react";
import { WS_URL } from "./api";
import type { FeedEvent } from "./types";

const MAX_EVENTS = 60;

export function useFeed(): { events: FeedEvent[]; connected: boolean } {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const retryRef = useRef(1000);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;

    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 1000;
      };
      ws.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data as string) as FeedEvent;
          if (event.type === "pong") return;
          setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          timer = setTimeout(connect, retryRef.current);
          retryRef.current = Math.min(retryRef.current * 2, 15000);
        }
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return { events, connected };
}
