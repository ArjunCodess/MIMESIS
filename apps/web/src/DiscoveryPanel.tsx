import { useEffect, useMemo, useState } from "react";
import { z } from "zod";
import { bundleSchema } from "./data";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
const score = z.object({
  candidate_ids: z.array(z.string()),
  coverage: z.array(z.number()),
  objective: z.number(),
});
const subwindow = z.object({
  row: z.number(),
  column: z.number(),
  class: z.string(),
  values: z.array(z.number()).nullable(),
});
const suite = z.object({
  state: z.string(),
  selected: score,
  single: score,
  top_two: score,
  random_pair_mean: z.number().nullable(),
  eligible_count: z.number(),
  evaluated_pair_count: z.number(),
  requirements: z.array(z.string()),
  uncovered_requirements: z.array(z.string()),
  limitation: z.string(),
  selected_subwindows: z.record(
    z.string(),
    z.record(z.string(), z.array(subwindow)),
  ),
});
const task = z.object({
  id: z.string(),
  title: z.string(),
  scientific_question: z.string(),
  weights: z.array(z.number()),
  excluded_transfer_claims: z.array(z.string()),
});
const schema = z.object({
  protocol_hash: z.string(),
  record_hash: z.string(),
  candidate_count: z.number(),
  regions: bundleSchema.shape.regions,
  candidates: bundleSchema.shape.candidates,
  targets: bundleSchema.shape.targets,
  tasks: z.object({ tasks: z.array(task) }),
  acquisition: z.array(
    z.object({
      region_id: z.string(),
      valid_windows: z.number(),
      excluded_windows: z.number(),
      unavailable_tiles: z.array(z.string()),
    }),
  ),
  runs: z.record(
    z.string(),
    z.record(
      z.string(),
      z.record(
        z.string(),
        z.looseObject({
          candidates: bundleSchema.shape.rankings.valueType.shape.candidates,
          run_hash: z.string(),
          full_candidate_count: z.number(),
        }),
      ),
    ),
  ),
  suites: z.record(z.string(), z.record(z.string(), suite)),
  target_subwindows: z.record(
    z.string(),
    z.record(z.string(), z.array(subwindow)),
  ),
  claim: z.string(),
});
const findingSchema = z.object({
  headline: z.string(),
  conclusion: z.string(),
  leads: z.array(
    z.object({
      candidate_id: z.string(),
      target_id: z.string(),
      claim_level: z.string(),
      statement: z.string(),
      gates: z.array(
        z.object({ name: z.string(), state: z.string(), reason: z.string() }),
      ),
      limitations: z.array(z.string()),
      earth_image: z.string(),
      planetary_image: z.string(),
    }),
  ),
  remaining: z.array(z.string()),
});
type Discovery = z.infer<typeof schema>;
type Findings = z.infer<typeof findingSchema>;

async function readJson(name: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(asset(name), { signal });
  if (!response.ok) throw new Error(`${name} returned HTTP ${response.status}`);
  return response.json();
}

export default function DiscoveryPanel() {
  const [data, setData] = useState<Discovery | null>(null);
  const [findings, setFindings] = useState<Findings | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      readJson("discovery_view.json", controller.signal),
      readJson("discovery_findings.json", controller.signal),
    ])
      .then(([record, claims]) => {
        setData(schema.parse(record));
        setFindings(findingSchema.parse(claims));
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "The discovery record could not load",
          );
      });
    return () => controller.abort();
  }, []);
  if (error)
    return (
      <section className="help-panel" role="alert">
        <h2>Discovery record unavailable</h2>
        <p>{error}</p>
        <p>
          The archived investigation is available under Explore. Rebuild the
          discovery record to inspect the expanded experiment.
        </p>
      </section>
    );
  if (!data || !findings)
    return (
      <p aria-busy="true">
        Reading the expanded search and source-linked findings…
      </p>
    );
  return <DiscoveryWorkspace data={data} findings={findings} />;
}

function DiscoveryWorkspace({
  data,
  findings,
}: {
  data: Discovery;
  findings: Findings;
}) {
  const [tab, setTab] = useState("Findings");
  const [targetId, setTargetId] = useState("syrtis");
  const [taskId, setTaskId] = useState("regional_geomorphological_mapping");
  const [tier, setTier] = useState("500");
  const [regionId, setRegionId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [requirement, setRequirement] = useState("low_slope_floor");
  const lookup = useMemo(
    () => new Map(data.candidates.map((c) => [c.id, c])),
    [data.candidates],
  );
  const run = data.runs[taskId][targetId][tier];
  const rows = run.candidates.filter(
    (r) => !regionId || lookup.get(r.id)?.region_id === regionId,
  );
  const selected =
    lookup.get(candidateId) ?? (rows[0] ? lookup.get(rows[0].id) : undefined);
  const region = selected
    ? data.regions.find((r) => r.id === selected.region_id)
    : undefined;
  const selectedTask = data.tasks.tasks.find((t) => t.id === taskId)!;
  const pair = data.suites.terrain_diversity_sampling[targetId];
  return (
    <section className="discovery-workspace">
      <div className="status-strip">
        <span className="status-dot" />
        <strong>Exploratory discovery run</strong>
        <span>
          {data.candidate_count.toLocaleString()} valid overlapping windows ·{" "}
          {data.regions.length} bounded regions · two versioned tasks
        </span>
        <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
      </div>
      <div className="tabs" role="tablist" aria-label="Discovery investigation">
        {[
          "Findings",
          "Expanded search",
          "Complementary sites",
          "Evidence gaps",
        ].map((label) => (
          <button
            key={label}
            id={`discovery-tab-${label.replaceAll(" ", "-")}`}
            role="tab"
            aria-controls="discovery-panel"
            aria-selected={tab === label}
            tabIndex={tab === label ? 0 : -1}
            className={tab === label ? "tab-active" : ""}
            onClick={() => setTab(label)}
            onKeyDown={(event) => {
              const labels = [
                "Findings",
                "Expanded search",
                "Complementary sites",
                "Evidence gaps",
              ];
              const position = labels.indexOf(label);
              const next =
                event.key === "ArrowRight"
                  ? (position + 1) % labels.length
                  : event.key === "ArrowLeft"
                    ? (position + labels.length - 1) % labels.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? labels.length - 1
                        : null;
              if (next !== null) {
                event.preventDefault();
                setTab(labels[next]);
                document
                  .getElementById(
                    `discovery-tab-${labels[next].replaceAll(" ", "-")}`,
                  )
                  ?.focus();
              }
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        id="discovery-panel"
        role="tabpanel"
        aria-labelledby={`discovery-tab-${tab.replaceAll(" ", "-")}`}
      >
        {tab === "Findings" ? (
          <div>
            <h2>{findings.headline}</h2>
            <p className="discovery-summary">{findings.conclusion}</p>
            {findings.leads.map((lead) => (
              <article
                className="discovery-lead"
                key={`${lead.target_id}-${lead.candidate_id}`}
              >
                <div className="section-heading">
                  <h3>
                    {lead.candidate_id} →{" "}
                    {data.targets.find((t) => t.id === lead.target_id)?.name}
                  </h3>
                  <span>{lead.claim_level.replaceAll("_", " ")}</span>
                </div>
                <p>{lead.statement}</p>
                <div className="optical-pair">
                  <figure>
                    <img
                      src={asset(lead.planetary_image)}
                      alt="Separately acquired planetary camera context, 80 km across"
                    />
                    <figcaption>Planetary camera context · 80 km</figcaption>
                  </figure>
                  <figure>
                    <img
                      src={asset(lead.earth_image)}
                      alt={`Quality-masked Landsat context for ${lead.candidate_id}, 80 km across`}
                    />
                    <figcaption>Earth camera context · 80 km</figcaption>
                  </figure>
                </div>
                <table>
                  <caption>
                    Release gates, assessed separately from ranking
                  </caption>
                  <thead>
                    <tr>
                      <th>Gate</th>
                      <th>State</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lead.gates.map((gate) => (
                      <tr key={gate.name}>
                        <th scope="row">{gate.name}</th>
                        <td>{gate.state}</td>
                        <td>{gate.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <ul>
                  {lead.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </article>
            ))}
            <p>
              <a href={asset("syrtis_novelty_audit.json")} download>
                Download the actual prior-association search ledger
              </a>
            </p>
          </div>
        ) : tab === "Expanded search" ? (
          <div>
            <div className="discovery-controls">
              <label>
                Target
                <select
                  value={targetId}
                  onChange={(e) => {
                    setTargetId(e.target.value);
                    setCandidateId("");
                  }}
                >
                  {data.targets.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name} · {t.body}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Investigation
                <select
                  value={taskId}
                  onChange={(e) => {
                    setTaskId(e.target.value);
                    setCandidateId("");
                  }}
                >
                  {data.tasks.tasks.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Analysis spacing
                <select value={tier} onChange={(e) => setTier(e.target.value)}>
                  <option value="500">500 m</option>
                  <option value="1000">1 km</option>
                </select>
              </label>
              <label>
                Earth region
                <select
                  value={regionId}
                  onChange={(e) => {
                    setRegionId(e.target.value);
                    setCandidateId("");
                  }}
                >
                  <option value="">All regions</option>
                  {data.regions.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} ({r.valid_windows})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p>
              {selectedTask.scientific_question} Weights are{" "}
              {selectedTask.weights.join(" / ")}; filters preserve the frozen
              ranking.
            </p>
            <p>
              These are retained top results, including each region’s leading
              five windows. The full record contains{" "}
              {run.full_candidate_count.toLocaleString()} candidates for this
              task and target.{" "}
              <a href={asset("discovery.json.gz")} download>
                Download all ranks and descriptors
              </a>
              .
            </p>
            <div className="discovery-search-grid">
              <div className="table-scroll">
                <table>
                  <caption>Measured regional candidates</caption>
                  <thead>
                    <tr>
                      <th>Rank</th>
                      <th>Earth window</th>
                      <th>Robust loss</th>
                      <th>Nominal loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, 30).map((row) => (
                      <tr
                        key={row.id}
                        className={selected?.id === row.id ? "selected" : ""}
                      >
                        <td>{row.rank}</td>
                        <td>
                          <button onClick={() => setCandidateId(row.id)}>
                            {row.id}
                          </button>
                        </td>
                        <td>{row.robust_loss.toFixed(5)}</td>
                        <td>{row.nominal_loss.toFixed(5)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rows.length === 0 && (
                  <p>
                    No valid windows in this region under the frozen coverage
                    rule.
                  </p>
                )}
              </div>
              {selected && region ? (
                <aside>
                  <h3>{selected.id}</h3>
                  <p>
                    {selected.latitude.toFixed(5)},{" "}
                    {selected.longitude.toFixed(5)}
                  </p>
                  <div className="discovery-map">
                    <img
                      src={asset(region.image)}
                      alt={`Bounded NASADEM terrain for ${region.name}`}
                    />
                    <svg
                      viewBox="0 0 232 232"
                      aria-label="Selected 20 km footprint in the 232 km search context"
                    >
                      <rect
                        x={(selected.easting_m + 116000) / 1000 - 10}
                        y={(116000 - selected.northing_m) / 1000 - 10}
                        width="20"
                        height="20"
                        fill="none"
                        stroke="white"
                        strokeWidth="1"
                      />
                    </svg>
                  </div>
                  <p>
                    232 km map extent · centered 20 km footprint ·
                    elevation-derived preview
                  </p>
                  <dl>
                    <dt>Local relief</dt>
                    <dd>{selected.features[tier].relief_m.toFixed(1)} m</dd>
                    <dt>Median slope</dt>
                    <dd>
                      {selected.features[tier].slope_median_deg.toFixed(2)}°
                    </dd>
                    <dt>Clear Earth imagery locally</dt>
                    <dd>
                      {(selected.reserved_hls_valid_fraction * 100).toFixed(2)}%
                    </dd>
                  </dl>
                  <p>
                    New v4 shortlist membership does not inherit a completed
                    assessment from a nearby v3 footprint.
                  </p>
                </aside>
              ) : null}
            </div>
            <p>
              Excluded transfers:{" "}
              {selectedTask.excluded_transfer_claims
                .map((s) => s.replaceAll("_", " "))
                .join(", ")}
              .
            </p>
          </div>
        ) : tab === "Complementary sites" ? (
          <div>
            <h2>What a second site adds</h2>
            <label>
              Suite target
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
              >
                {data.targets.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Terrain-diversity task · 4 km subwindows · minimum across 500 m, 1
              km and mask scenarios. Only individually below-cutoff sites enter
              the eligible pool, with non-overlapping 80 km contexts.
            </p>
            <p>
              {pair.state === "no_feasible_pair"
                ? "No feasible separated pair; the eligible single is retained."
                : `${pair.evaluated_pair_count.toLocaleString()} feasible pairs evaluated from the declared shortlist.`}{" "}
              {pair.limitation}
            </p>
            <table>
              <caption>
                Descriptor coverage under equal site and separation constraints
              </caption>
              <thead>
                <tr>
                  <th>Selection</th>
                  <th>Sites</th>
                  <th>Weighted coverage</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["Best single", pair.single],
                  ["Individually ranked top two", pair.top_two],
                  ["Coverage-selected pair", pair.selected],
                ].map(([name, value]) => {
                  const result = value as z.infer<typeof score>;
                  return (
                    <tr key={name as string}>
                      <th scope="row">{name as string}</th>
                      <td>
                        {result.candidate_ids.join(" + ") || "No eligible site"}
                      </td>
                      <td>{result.objective.toFixed(3)}</td>
                    </tr>
                  );
                })}
                <tr>
                  <th scope="row">Seeded random pairs</th>
                  <td>Same evaluated pool and constraints</td>
                  <td>{pair.random_pair_mean?.toFixed(3) ?? "Unavailable"}</td>
                </tr>
              </tbody>
            </table>
            <div className="coverage-rows">
              {pair.requirements.map((r, i) => (
                <button
                  key={r}
                  onClick={() => setRequirement(r)}
                  aria-pressed={requirement === r}
                >
                  <span>{r.replaceAll("_", " ")}</span>
                  <meter
                    min={0}
                    max={1}
                    value={pair.selected.coverage[i]}
                    aria-label={`${r} descriptor coverage`}
                  />
                  <span>{pair.selected.coverage[i].toFixed(3)}</span>
                </button>
              ))}
            </div>
            <div className="subwindow-panels">
              {[
                { id: targetId, tiers: data.target_subwindows[targetId] },
                ...Object.entries(pair.selected_subwindows).map(
                  ([id, tiers]) => ({ id, tiers }),
                ),
              ].map((item) => (
                <figure key={item.id}>
                  <figcaption>{item.id} · 20 km footprint</figcaption>
                  <div className="subwindow-grid">
                    {item.tiers["500"].map((cell) => (
                      <span
                        key={`${cell.row}-${cell.column}`}
                        className={
                          cell.class === requirement ? "highlight" : ""
                        }
                        title={`${cell.row + 1}, ${cell.column + 1}: ${cell.class.replaceAll("_", " ")}`}
                      >
                        {cell.class === requirement ? "●" : "·"}
                      </span>
                    ))}
                  </div>
                </figure>
              ))}
            </div>
            <p>
              Highlighted cells belong to the selected measured class.
              Closest-descriptor matches may cross class boundaries within the
              tolerance. Empty target requirements score zero. Coverage gains
              measure this formula; independent usefulness judgments and field
              performance remain unmeasured.
            </p>
          </div>
        ) : (
          <div>
            <h2>What remains to establish</h2>
            <ul>
              {findings.remaining.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <table>
              <caption>Acquisition and terrain exclusions</caption>
              <thead>
                <tr>
                  <th>Region</th>
                  <th>Valid windows</th>
                  <th>Excluded windows</th>
                  <th>Unavailable tiles</th>
                </tr>
              </thead>
              <tbody>
                {data.acquisition.map((r) => (
                  <tr key={r.region_id}>
                    <th scope="row">{r.region_id}</th>
                    <td>{r.valid_windows}</td>
                    <td>{r.excluded_windows}</td>
                    <td>{r.unavailable_tiles.join(", ") || "None"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              <a href={asset("finer_support.json")} download>
                Finer-support source and measurement record
              </a>{" "}
              ·{" "}
              <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
            </p>
            <p>
              Protocol SHA-256:{" "}
              <code className="hash">{data.protocol_hash}</code>
            </p>
            <p>
              Record SHA-256: <code className="hash">{data.record_hash}</code>
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
