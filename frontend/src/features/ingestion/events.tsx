import { Badge, Empty, Panel } from "@/components/ui";
import { compactDetails, when } from "./format";
import type { EventOut } from "./types";

const tone = { info: "neutral", warning: "warn", error: "bad" } as const;

export function EventTable({ events, title, description }: { events: EventOut[]; title: string; description: string }) {
  return (
    <Panel title={title} description={description}>
      {events.length === 0 ? <Empty title="No events yet">Nothing has been recorded here. Events appear as soon as the book is prepared or embedded.</Empty> : (
        <div className="table-scroll"><table><thead><tr><th>Level</th><th>Kind</th><th>Message</th><th>Time</th><th>Details</th></tr></thead>
          <tbody>{events.map((e) => (
            <tr key={e.id} className={e.level === "error" ? "event-error" : undefined}>
              <td><Badge tone={tone[e.level]}>{e.level}</Badge></td>
              <td className="code-text">{e.kind}</td>
              <td className="event-message">{e.message}</td>
              <td>{when(e.created_at)}</td>
              <td className="code-text">{compactDetails(e.details)}</td>
            </tr>
          ))}</tbody></table></div>
      )}
    </Panel>
  );
}
