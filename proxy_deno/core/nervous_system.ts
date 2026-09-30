// proxy_deno/core/nervous_system.ts
export type EventKind = 'spike' | 'route' | 'ingest' | 'alert' | 'heartbeat';
export interface BusEvent { kind: EventKind; source: string; payload: unknown; ts: number }
export interface BloodCell {
  jobId: string; traceId: string; organName: string; payload: unknown;
  status: string; timestamp: number; result?: unknown; error?: string;
}

type CellHandler = (cell: BloodCell) => void | Promise<void>;
type EventHandler = (e: BusEvent) => void;

export class SystemBus {
  private _cellSubs: Record<string, CellHandler[]> = {};
  private _eventSubs: Partial<Record<EventKind, EventHandler[]>> = {};
  private _hist: BloodCell[] = [];
  private readonly _maxHist = 500;

  subscribe(channel: string, handler: CellHandler): () => void {
    (this._cellSubs[channel] ??= []).push(handler);
    return () => { this._cellSubs[channel] = this._cellSubs[channel]!.filter(h => h !== handler); };
  }

  pump(cell: BloodCell): void {
    this._hist.push(cell);
    if (this._hist.length > this._maxHist) this._hist.shift();
    this._cellSubs[cell.organName]?.forEach(h => h(cell));
    if (cell.organName !== "system_monitor") {
      this._cellSubs["system_monitor"]?.forEach(h => h(cell));
    }
  }

  publish(event: BusEvent): void {
    this._eventSubs[event.kind]?.forEach(h => h(event));
  }

  on(kind: EventKind, handler: EventHandler): () => void {
    (this._eventSubs[kind] ??= []).push(handler);
    return () => { this._eventSubs[kind] = this._eventSubs[kind]!.filter(h => h !== handler); };
  }

  history(limit = 50): BloodCell[] { return this._hist.slice(-limit); }
  // Only clear history — never clear subscriptions or organs go deaf
  clear(): void { this._hist.length = 0; }
}

export const bus = new SystemBus();

export function publishAlert(source: string, msg: string): void {
  bus.publish({ kind: 'alert', source, payload: msg, ts: Date.now() });
}
export function publishHeartbeat(source: string): void {
  bus.publish({ kind: 'heartbeat', source, payload: null, ts: Date.now() });
}
