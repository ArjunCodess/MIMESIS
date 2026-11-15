import { useEffect, useState } from "react";
import { z } from "zod";

const base = `${import.meta.env.BASE_URL}research/`;
const schema = z.object({
  id: z.string(),
  record_hash: z.string(),
  objective: z.string(),
  claim: z.string(),
  sections: z.array(z.object({
    id: z.string(),
    title: z.string(),
    statement: z.string(),
    counts: z.array(z.object({ label: z.string(), value: z.number().nullable() })),
    report: z.string(),
    record: z.string(),
    figure: z.string().nullable(),
    limitations: z.array(z.string()),
    cases: z.array(z.object({
      id: z.string(),
      label: z.string(),
      state: z.string(),
      latitude: z.number().nullable(),
      longitude: z.number().nullable(),
      metrics: z.array(z.object({ label: z.string(), value: z.string() })),
      evidence: z.array(z.string()),
      missing: z.array(z.string()),
    })),
  })),
  resources: z.array(z.object({ name: z.string(), role: z.string(), url: z.url() })),
});
type Lab = z.infer<typeof schema>;

export default function DiscoveryLab() {
  const [record, setRecord] = useState<Lab | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [active, setActive] = useState(0);
  const [caseId, setCaseId] = useState("");
  const [filter, setFilter] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetch(`${base}discovery_v9.json`, { signal: controller.signal })
      .then(response => {
        if (!response.ok) throw new Error(`Experiment record returned HTTP ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then(value => setRecord(schema.parse(value)))
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Experiment record unavailable");
      });
    return () => controller.abort();
  }, [attempt]);
  if (error) return <div role="alert"><h3>The experiment record could not be loaded</h3><p>{error}</p><button onClick={() => setAttempt(value => value + 1)}>Retry experiment record</button></div>;
  if (!record) return <p role="status">Loading source-linked discovery experiments…</p>;
  const section = record.sections[active];
  const rows = section.cases.filter(row => `${row.id} ${row.label} ${row.state}`.toLowerCase().includes(filter.toLowerCase()));
  const selected = section.cases.find(row => row.id === caseId) ?? rows[0];
  return <div className="discovery-lab">
    <h3>Test the strongest candidates</h3>
    <p>{record.objective}</p>
    <p className="lab-claim">{record.claim}</p>
    <nav className="lab-experiments" aria-label="Discovery experiments">
      {record.sections.map((item, index) => <button key={item.id} aria-pressed={active === index} onClick={() => { setActive(index); setCaseId(""); setFilter(""); }}>{item.title}</button>)}
    </nav>
    <h4>{section.title}</h4>
    <p>{section.statement}</p>
    <dl className="lab-counts">{section.counts.map(count => <div key={count.label}><dt>{count.label}</dt><dd>{count.value === null ? "Not measured" : count.value.toLocaleString()}</dd></div>)}</dl>
    <p><a href={`${base}${section.report}`} download>Read experiment report</a>{" · "}<a href={`${base}${section.record}`} download>Download complete observations</a></p>
    {section.figure && <figure><img className="research-figure" src={`${base}${section.figure}`} alt="Measured orbital reflectance, retained wavelengths and source uncertainty with excluded intervals marked" /><figcaption>Actual source measurements and quality exclusions. Pixel spread and supplied uncertainty do not establish independent geological truth.</figcaption></figure>}
    <label htmlFor="lab-case-filter">Find an observation</label>{" "}
    <input id="lab-case-filter" type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Location, observation ID or evidence state" />
    <div className="lab-observations">
      <div className="table-scroll" role="region" aria-label="Discovery observation list" tabIndex={0}>
        <table>
          <caption>{rows.length} recorded observations</caption>
          <thead><tr><th>Observation</th><th>Evidence state</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.id} aria-selected={selected?.id === row.id}><th scope="row"><button aria-pressed={selected?.id === row.id} onClick={() => setCaseId(row.id)}>{row.label}</button></th><td>{row.state.replaceAll("_", " ")}</td></tr>)}</tbody>
        </table>
        {rows.length === 0 && <p role="status">No observations match this search.</p>}
      </div>
      {selected && <article className="lab-case" aria-label="Selected discovery observation">
        <h4>{selected.label}</h4>
        <p>{selected.state.replaceAll("_", " ")}</p>
        {selected.latitude !== null && selected.longitude !== null && <p>Earth center: {selected.latitude.toFixed(5)}°, {selected.longitude.toFixed(5)}°.</p>}
        <dl>{selected.metrics.map(metric => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}</dl>
        {selected.evidence.length > 0 && <><h5>Observed evidence</h5><ul>{selected.evidence.map(item => <li key={item}>{item}</li>)}</ul></>}
        {selected.missing.length > 0 && <><h5>Evidence still needed</h5><ul>{selected.missing.map(item => <li key={item}>{item.replaceAll("_", " ")}</li>)}</ul></>}
      </article>}
    </div>
    <details><summary>Experiment limits and source roles</summary><ul>{section.limitations.map(item => <li key={item}>{item}</li>)}</ul><dl className="lab-resource-list">{record.resources.map(resource => <div key={resource.name}><dt><a href={resource.url} target="_blank" rel="noreferrer">{resource.name}</a></dt><dd>{resource.role}</dd></div>)}</dl></details>
    <p><a href={`${base}discovery_v9.json`} download>Export joined discovery record</a></p>
    <p className="muted">Record SHA-256: <code className="hash">{record.record_hash}</code></p>
  </div>;
}
