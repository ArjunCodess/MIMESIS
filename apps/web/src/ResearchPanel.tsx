import { lazy, Suspense, useEffect, useState } from "react";
import { z } from "zod";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
const DiscoveryLab = lazy(() => import("./DiscoveryLab"));
const schema = z.object({
  claim: z.string(),
  record_hash: z.string(),
  followup: z.object({
    buffers: z.array(
      z.object({
        buffer_m: z.number(),
        eligible_count: z.number(),
        terrain_only_count: z.number(),
        clear_image_count: z.number(),
        complete_pairs: z.number(),
      }),
    ),
    regions: z.array(
      z.object({
        region_id: z.string(),
        scene_count: z.number(),
        clear_context_fraction: z.number(),
        osm_status: z.string(),
      }),
    ),
    pairs: z.array(
      z.object({
        target_id: z.string(),
        buffer_m: z.number(),
        nomination: z.string().nullable(),
        control: z.string().nullable(),
        unfilled_reason: z.string().nullable(),
      }),
    ),
    fine_complete_pairs: z.number(),
  }),
  global: z.object({
    terrain_stem: z.string(),
    count: z.number(),
    requested_count: z.number(),
    missing_tile_count: z.number(),
    pilot: z.object({
      frozen_count: z.number(),
      measured_count: z.number(),
      excluded_count: z.number(),
      target_count: z.number(),
      passing_targets: z.number(),
      leaders: z.array(
        z.object({
          target_id: z.string(),
          candidate_id: z.string(),
          robust_loss: z.number(),
          state: z.string(),
        }),
      ),
      limitations: z.array(z.string()),
    }),
    blocks: z.array(
      z.object({
        id: z.string(),
        latitude: z.number(),
        longitude: z.number(),
        stratum: z.string(),
        ai_ratio: z.number().nullable(),
      }),
    ),
    limitations: z.array(z.string()),
  }),
  geology: z.object({
    coverage_fraction: z.number(),
    unit_class_count: z.number(),
    contact_length_km: z.number(),
    certainty: z.array(z.object({ name: z.string(), length_km: z.number() })),
    limits: z.array(z.string()),
  }),
  spectroscopy: z.object({
    asset_count: z.number(),
    pair_count: z.number(),
    mismatch_count: z.number(),
    nearest_sam_count: z.number(),
    nearest_continuum_count: z.number(),
    matched_sam: z.number().nullable(),
    mismatch_sam: z.number().nullable(),
    pairs: z.array(
      z.object({
        sample_id: z.string(),
        sam: z.number(),
        continuum_rmse: z.number(),
        sam_rank: z.number(),
      }),
    ),
    limits: z.array(z.string()),
  }),
  judging: z.array(
    z.object({
      criterion: z.string(),
      evidence: z.string(),
      remaining: z.string(),
    }),
  ),
});
type Research = z.infer<typeof schema>;

function DiscoveryTest({ data }: { data: Research["followup"] }) {
  return (
    <>
      <h3>Did better observations make the test feasible?</h3>
      <p>
        V6 adds the acquired HLS scenes and available OSM roads and land-use
        areas. The terrain threshold, buffer variants and matched-control
        tolerances remain fixed. V5 stays separately inspectable.
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Scrollable research table"
        tabIndex={0}
      >
        <table>
          <caption>Frozen follow-up eligibility and pairs</caption>
          <thead>
            <tr>
              <th>Buffer</th>
              <th>Clear imagery only</th>
              <th>Masked terrain only</th>
              <th>Combined eligible</th>
              <th>Frozen pairs</th>
            </tr>
          </thead>
          <tbody>
            {data.buffers.map((b) => (
              <tr key={b.buffer_m}>
                <th scope="row">{b.buffer_m} m</th>
                <td>{b.clear_image_count.toLocaleString()}</td>
                <td>{b.terrain_only_count.toLocaleString()}</td>
                <td>{b.eligible_count.toLocaleString()}</td>
                <td>{b.complete_pairs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Complete finer-observation pairs: {data.fine_complete_pairs}. A frozen
        pair still needs usable finer coverage, geological relevance and
        independent task evaluation.
      </p>
      <details>
        <summary>Inspect every prospective nomination and control</summary>
        <div
          className="table-scroll"
          role="region"
          aria-label="Scrollable research table"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th>Target / buffer</th>
                <th>Nomination</th>
                <th>Control or gap</th>
              </tr>
            </thead>
            <tbody>
              {data.pairs.map((p) => (
                <tr key={`${p.target_id}-${p.buffer_m}`}>
                  <th scope="row">
                    {p.target_id} / {p.buffer_m} m
                  </th>
                  <td>{p.nomination ?? "Unfilled"}</td>
                  <td>{p.control ?? p.unfilled_reason ?? "Unfilled"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <div
        className="table-scroll"
        role="region"
        aria-label="Scrollable research table"
        tabIndex={0}
      >
        <table>
          <caption>Actual regional sources</caption>
          <thead>
            <tr>
              <th>Region</th>
              <th>HLS scenes</th>
              <th>Clear field</th>
              <th>OSM state</th>
            </tr>
          </thead>
          <tbody>
            {data.regions.map((r) => (
              <tr key={r.region_id}>
                <th scope="row">{r.region_id}</th>
                <td>{r.scene_count}</td>
                <td>{(r.clear_context_fraction * 100).toFixed(1)}%</td>
                <td>{r.osm_status.replaceAll("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <a href={asset("natural_land_v6.json")} download>
          Full masked rankings and exclusions
        </a>{" "}
        ·{" "}
        <a href={asset("prospective_validation_v6.json")} download>
          Fine-scale comparison record
        </a>
      </p>
    </>
  );
}

function GlobalFrame({ data }: { data: Research["global"] }) {
  const [selected, setSelected] = useState(data.blocks[0]?.id ?? "");
  const block = data.blocks.find((b) => b.id === selected);
  return (
    <>
      <h3>A declared global search population</h3>
      <p>
        {data.count} of {data.requested_count} climate-selected blocks are
        frozen independently of terrain ranks. Current local inventory is
        missing {data.missing_tile_count} of the frame's native elevation tiles.
        These points are sampling locations, not discovered analogues.
      </p>
      <svg
        viewBox="0 0 720 360"
        className="global-frame-map"
        role="img"
        aria-label="Locations of the frozen global dryland sampling blocks"
      >
        <rect width="720" height="360" fill="#eeeadd" />
        {[-120, -60, 0, 60, 120].map((x) => (
          <line
            key={x}
            x1={(x + 180) * 2}
            x2={(x + 180) * 2}
            y1="0"
            y2="360"
            stroke="#c9c9bb"
          />
        ))}
        {[-60, -30, 0, 30, 60].map((y) => (
          <line
            key={y}
            x1="0"
            x2="720"
            y1={(90 - y) * 2}
            y2={(90 - y) * 2}
            stroke="#c9c9bb"
          />
        ))}
        {data.blocks.map((b) => (
          <circle
            key={b.id}
            cx={(b.longitude + 180) * 2}
            cy={(90 - b.latitude) * 2}
            r={selected === b.id ? 5 : 3}
            fill={b.stratum === "BWh" ? "#a15d3a" : "#426b71"}
          >
            <title>
              {b.id}: {b.latitude.toFixed(3)}, {b.longitude.toFixed(3)};{" "}
              {b.stratum}
            </title>
          </circle>
        ))}
      </svg>
      <p className="muted">
        Geographic longitude/latitude graticule. Rust: hot desert (BWh); blue:
        cold desert (BWk). Equal-area proposal sampling does not make this
        display equal-area or prove statistical independence.
      </p>
      <h3>
        What the {data.pilot.frozen_count}-block terrain experiment measured
      </h3>
      <p>
        {data.pilot.measured_count}/{data.pilot.frozen_count} blocks pass
        terrain coverage; {data.pilot.excluded_count} remain excluded.{" "}
        {data.pilot.passing_targets}/{data.pilot.target_count} planetary targets
        have a descriptive cutoff pass. These are screened terrain matches, with
        human-modification, imagery and geological gates still incomplete.
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Scrollable research table"
        tabIndex={0}
      >
        <table>
          <caption>All planetary terrain cases, including failures</caption>
          <thead>
            <tr>
              <th>Target</th>
              <th>Leading sampled block</th>
              <th>Robust discrepancy</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {data.pilot.leaders.map((r) => (
              <tr key={r.target_id}>
                <th scope="row">{r.target_id}</th>
                <td>
                  <button onClick={() => setSelected(r.candidate_id)}>
                    {r.candidate_id}
                  </button>
                </td>
                <td>{r.robust_loss.toFixed(5)}</td>
                <td>{r.state.replaceAll("_", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <a href={asset(`${data.terrain_stem}.json`)} download>
          Measured terrain ranks and source coverage
        </a>{" "}
        ·{" "}
        <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
      </p>
      <label htmlFor="global-block">Inspect a sampled block</label>{" "}
      <select
        id="global-block"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
      >
        {data.blocks.map((b) => (
          <option key={b.id} value={b.id}>
            {b.id} · {b.stratum}
          </option>
        ))}
      </select>
      {block && (
        <p>
          {block.latitude.toFixed(5)}° latitude, {block.longitude.toFixed(5)}°
          east longitude; annual aridity index{" "}
          {block.ai_ratio?.toFixed(4) ?? "missing"}. The frame records climate
          eligibility; terrain measurements are published separately, and
          geological relevance remains unvalidated.
        </p>
      )}
      <ul>
        {data.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      <p>
        <a href={asset("global_frame_v6.json")} download>
          Frame and source metadata
        </a>{" "}
        ·{" "}
        <a href={asset("global_nasadem_manifest_v6.json")} download>
          Exact acquisition manifest
        </a>
      </p>
    </>
  );
}

function GeologicalReference({ data }: { data: Research["geology"] }) {
  return (
    <>
      <h3>Jezero has a geological calibration reference</h3>
      <figure>
        <img
          className="research-figure"
          src={asset("geology_v6_jezero.png")}
          alt="Published SIM3464 geological units and certain or approximate contacts in the20km Jezero calibration window, projected in Mars local kilometres"
        />
        <figcaption>
          Published geological interpretation, with native unit symbols. This is
          a calibration reference; no predicted-contact accuracy is shown.
        </figcaption>
      </figure>
      <p>
        SIM 3464 covers {(data.coverage_fraction * 100).toFixed(1)}% of the
        local Jezero window, with {data.unit_class_count} mapped unit classes
        and {data.contact_length_km.toFixed(2)} km of clipped contacts. The
        acquired map does not cover the six prospective targets.
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Scrollable research table"
        tabIndex={0}
      >
        <table>
          <caption>
            Published contact certainty, preserved from the source
          </caption>
          <thead>
            <tr>
              <th>Type</th>
              <th>Length in window</th>
            </tr>
          </thead>
          <tbody>
            {data.certainty.map((c) => (
              <tr key={c.name}>
                <th scope="row">{c.name}</th>
                <td>{c.length_km.toFixed(2)} km</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul>
        {data.limits.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      <p>
        <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>{" "}
        ·{" "}
        <a href={asset("geology_v6_sim3464_native.gpkg")} download>
          Native Mars GIS
        </a>{" "}
        ·{" "}
        <a href={asset("prior_work_v6.json")} download>
          Prior-association audit
        </a>
      </p>
    </>
  );
}

function LaboratoryControl({ data }: { data: Research["spectroscopy"] }) {
  return (
    <>
      <h3>Test the method on a known mineral analogue</h3>
      <figure>
        <img
          className="research-figure"
          src={asset("puga_sam_matrix.png")}
          alt="Field-to-laboratory spectral angle matrix for10 Puga specimens, including matching and different specimen IDs"
        />
        <figcaption>
          Lower spectral angle means a closer spectral shape on the declared
          common support. It does not identify minerals or prove orbital
          detectability.
        </figcaption>
      </figure>
      <p>
        The Puga control uses {data.asset_count} archived measurements,{" "}
        {data.pair_count} matched field/laboratory pairs and{" "}
        {data.mismatch_count} different-ID comparisons. Puga is a published
        analogue; this experiment does not discover it.
      </p>
      <div className="validation-stats">
        <div>
          <strong>
            {data.nearest_sam_count}/{data.pair_count}
          </strong>
          <span>same specimen nearest by spectral angle</span>
        </div>
        <div>
          <strong>
            {data.nearest_continuum_count}/{data.pair_count}
          </strong>
          <span>same specimen nearest after continuum removal</span>
        </div>
      </div>
      <p>
        Median spectral angle: {data.matched_sam?.toFixed(4) ?? "unavailable"}{" "}
        radians for matching IDs versus{" "}
        {data.mismatch_sam?.toFixed(4) ?? "unavailable"} for different IDs.
        Different specimens can share mineralogy, and this small archive is not
        an independent classification benchmark.
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Scrollable research table"
        tabIndex={0}
      >
        <table>
          <caption>Actual matched-sample comparisons</caption>
          <thead>
            <tr>
              <th>Sample</th>
              <th>Spectral angle</th>
              <th>Continuum RMSE</th>
              <th>Same-ID rank</th>
            </tr>
          </thead>
          <tbody>
            {data.pairs.map((p) => (
              <tr key={p.sample_id}>
                <th scope="row">{p.sample_id}</th>
                <td>{p.sam.toFixed(4)}</td>
                <td>{p.continuum_rmse.toFixed(4)}</td>
                <td>{p.sam_rank}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul>
        {data.limits.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      <p>
        <a href={asset("puga_control_v6.json")} download>
          Laboratory measurements and lineage
        </a>{" "}
        ·{" "}
        <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
      </p>
    </>
  );
}

export default function ResearchPanel() {
  const [data, setData] = useState<Research | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);
  const tabs = [
    "Discovery test",
    "Global search",
    "Geology",
    "Laboratory",
    "Challenge",
    "Discovery lab",
  ];
  useEffect(() => {
    const controller = new AbortController();
    fetch(asset("research_v6.json"), { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`Research record returned HTTP ${r.status}`);
        return r.json() as Promise<unknown>;
      })
      .then((v) => setData(schema.parse(v)))
      .catch((e: unknown) => {
        if (!controller.signal.aborted)
          setError(
            e instanceof Error ? e.message : "Research record unavailable",
          );
      });
    return () => controller.abort();
  }, []);
  if (error)
    return (
      <section role="alert">
        <h2>Research record unavailable</h2>
        <p>{error}</p>
        <p>
          The preserved experiments are available under Validation and
          Discovery.
        </p>
      </section>
    );
  if (!data)
    return <p aria-busy="true">Reading the measured research results…</p>;
  return (
    <section className="validation-workspace">
      <div className="status-strip">
        <span className="status-dot" />
        <strong>V6 · evidence follow-up</strong>
        <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
      </div>
      <h2>Search beyond a similarity score</h2>
      <p className="validation-claim">{data.claim}</p>
      <div className="tabs" role="tablist" aria-label="Research evidence">
        {tabs.map((name, index) => (
          <button
            key={name}
            id={`research-tab-${index}`}
            role="tab"
            tabIndex={tab === index ? 0 : -1}
            aria-selected={tab === index}
            aria-controls="research-panel"
            onClick={() => setTab(index)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % tabs.length
                  : event.key === "ArrowLeft"
                    ? (index + tabs.length - 1) % tabs.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? tabs.length - 1
                        : null;
              if (next !== null) {
                event.preventDefault();
                setTab(next);
                document.getElementById(`research-tab-${next}`)?.focus();
              }
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <div
        id="research-panel"
        role="tabpanel"
        aria-labelledby={`research-tab-${tab}`}
        tabIndex={0}
      >
        {tab === 0 ? (
          <DiscoveryTest data={data.followup} />
        ) : tab === 1 ? (
          <GlobalFrame data={data.global} />
        ) : tab === 2 ? (
          <GeologicalReference data={data.geology} />
        ) : tab === 3 ? (
          <LaboratoryControl data={data.spectroscopy} />
        ) : tab === 5 ? (
          <Suspense fallback={<p role="status">Loading discovery workspace…</p>}><DiscoveryLab /></Suspense>
        ) : (
          <>
            <h3>Make the evidence assessable</h3>
            <p>
              The challenge asks for a useful Earth analogue or search method,
              with an exploration connection and clear limits. The five judging
              dimensions below follow published guidance; exact current event
              rules and format still require confirmation.
            </p>
            <div
              className="table-scroll"
              role="region"
              aria-label="Scrollable research table"
              tabIndex={0}
            >
              <table>
                <caption>
                  Challenge and judging evidence, without self-assigned scores
                </caption>
                <thead>
                  <tr>
                    <th>Criterion</th>
                    <th>Evidence</th>
                    <th>Still needed</th>
                  </tr>
                </thead>
                <tbody>
                  {data.judging.map((j) => (
                    <tr key={j.criterion}>
                      <th scope="row">{j.criterion}</th>
                      <td>{j.evidence}</td>
                      <td>{j.remaining}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              <a href={asset("mimesis-paper.pdf")} download>
                Research paper, PDF
              </a>
            </p>
          </>
        )}
      </div>
      <p>
        Joined record SHA-256: <code className="hash">{data.record_hash}</code>
      </p>
    </section>
  );
}
