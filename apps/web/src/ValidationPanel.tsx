import { useEffect, useState } from "react";
import { z } from "zod";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
const diagnostic = z.object({
  candidate_id: z.string(),
  mapped_natural_local_fraction_before_smoothing: z.number(),
  mapped_natural_context_fraction_before_smoothing: z.number(),
  image_available: z.boolean(),
  failed_rules: z.array(z.string()),
});
const pair = z.object({
  target_id: z.string(),
  nomination: z.string().nullable(),
  control: z.string().nullable(),
  unfilled_reason: z.string().nullable(),
  state: z.string(),
});
const schema = z.object({
  record_hash: z.string(),
  evidence_hash: z.string(),
  claim: z.string(),
  mask_image: z.string(),
  limits: z.array(z.string()),
  eligible_counts: z.record(z.string(), z.number()),
  old_lead_diagnostics: z.record(z.string(), z.array(diagnostic)),
  pairs: z.record(z.string(), z.record(z.string(), pair)),
  attrition: z.record(
    z.string(),
    z.object({
      baseline_terrain_windows: z.number(),
      clear_image_only: z.number(),
      masked_terrain_only: z.number(),
      combined_eligible: z.number(),
    }),
  ),
  targets: z.array(
    z.object({
      id: z.string(),
      latitude: z.number(),
      longitude: z.number(),
      stereo_valid_fraction: z.number(),
      camera_valid_fraction: z.number(),
      stereo_url: z.string(),
      image: z.string().nullable(),
    }),
  ),
  fine_results: z.array(
    z.object({
      target_id: z.string(),
      buffer_m: z.number(),
      candidate_id: z.string(),
      joint_wasserstein: z.number().nullable(),
      hypsometric_difference: z.number().nullable(),
      state: z.string(),
      earth_valid_fraction: z.number(),
      planetary_valid_fraction: z.number(),
    }),
  ),
  primary_complete_target_pairs: z.number(),
  mola_support: z.array(
    z.object({
      target_id: z.string(),
      local_zero_count_fraction: z.number(),
      context_zero_count_fraction: z.number(),
    }),
  ),
  mola_support_limit: z.string(),
  source_limits: z.array(
    z.object({
      region_id: z.string(),
      osm_status: z.string(),
      limitation: z.string(),
    }),
  ),
  pool_sensitivity: z.array(
    z.object({
      candidate_id: z.string(),
      old_rank: z.number(),
      expanded_rank: z.number(),
      old_robust_loss: z.number(),
      expanded_robust_loss: z.number(),
      interpretation: z.string(),
    }),
  ),
});
type Record = z.infer<typeof schema>;

export default function ValidationPanel() {
  const [data, setData] = useState<Record | null>(null);
  const [error, setError] = useState("");
  const [section, setSection] = useState("Masked land");
  const [buffer, setBuffer] = useState("1000");
  useEffect(() => {
    const controller = new AbortController();
    fetch(asset("validation_v5_view.json"), { signal: controller.signal })
      .then((response) => {
        if (!response.ok)
          throw new Error(`Validation record returned HTTP ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then((value) => setData(schema.parse(value)))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not read the validation record",
          );
      });
    return () => controller.abort();
  }, []);
  if (error)
    return (
      <div role="alert">
        <h2>Validation record unavailable</h2>
        <p>{error}</p>
      </div>
    );
  if (!data)
    return (
      <p aria-busy="true">
        Reading the frozen mask and prospective validation results…
      </p>
    );
  const sections = [
    "Masked land",
    "New targets",
    "Source support",
    "Review & limits",
  ];
  const attrition = data.attrition[buffer];
  return (
    <section className="validation-workspace">
      <div className="status-strip">
        <span className="status-dot" />
        <strong>V5 · frozen feasibility test</strong>
        <span>
          Six new stereo AOIs · two mask buffers ·{" "}
          {data.primary_complete_target_pairs} complete matched target pairs
        </span>
        <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
      </div>
      <h2>Earlier leads fail the strict mapped-land test</h2>
      <p className="discovery-summary">{data.claim}</p>
      <div className="tabs" role="tablist" aria-label="Validation evidence">
        {sections.map((name, index) => (
          <button
            key={name}
            id={`validation-tab-${index}`}
            role="tab"
            aria-controls="validation-panel"
            aria-selected={section === name}
            tabIndex={section === name ? 0 : -1}
            onClick={() => setSection(name)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % sections.length
                  : event.key === "ArrowLeft"
                    ? (index + sections.length - 1) % sections.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? sections.length - 1
                        : null;
              if (next !== null) {
                event.preventDefault();
                setSection(sections[next]);
                document.getElementById(`validation-tab-${next}`)?.focus();
              }
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="validation-panel"
        aria-labelledby={`validation-tab-${sections.indexOf(section)}`}
      >
        {section === "Masked land" ? (
          <>
            <label htmlFor="mask-buffer">
              Modification buffer
              <select
                id="mask-buffer"
                value={buffer}
                onChange={(event) => setBuffer(event.target.value)}
              >
                <option value="500">500 m</option>
                <option value="1000">1 km</option>
              </select>
            </label>
            <p>
              WorldCover 2021 mapped crop/built-up areas are excluded before
              smoothing and derivatives. Unflagged pixels are not verified
              natural land. OSM road/industrial extracts were unavailable, and
              source epochs differ.
            </p>
            <div className="validation-metrics">
              <div>
                <strong>
                  {attrition.baseline_terrain_windows.toLocaleString()}
                </strong>
                <span>original terrain windows</span>
              </div>
              <div>
                <strong>{attrition.clear_image_only.toLocaleString()}</strong>
                <span>clear imagery alone</span>
              </div>
              <div>
                <strong>
                  {attrition.masked_terrain_only.toLocaleString()}
                </strong>
                <span>masked terrain alone</span>
              </div>
              <div>
                <strong>{attrition.combined_eligible}</strong>
                <span>combined eligible windows</span>
              </div>
            </div>
            <p>
              The combined count reflects both mask/derivative validity and
              existing imagery gaps. It is not a measured causal effect of
              farming on the historical DEM.
            </p>
            <div className="table-scroll">
              <table>
                <caption>Earlier lead diagnostics, before smoothing</caption>
                <thead>
                  <tr>
                    <th>Earth footprint</th>
                    <th>Unflagged local</th>
                    <th>Unflagged context</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.old_lead_diagnostics[buffer].map((row) => (
                    <tr key={row.candidate_id}>
                      <th scope="row">{row.candidate_id}</th>
                      <td>
                        {(
                          row.mapped_natural_local_fraction_before_smoothing *
                          100
                        ).toFixed(2)}
                        %
                      </td>
                      <td>
                        {(
                          row.mapped_natural_context_fraction_before_smoothing *
                          100
                        ).toFixed(2)}
                        %
                      </td>
                      <td>{row.failed_rules.join("; ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <figure>
              <img
                className="validation-mask-image"
                src={asset(data.mask_image)}
                alt="Source-linked Landsat contexts of all three earlier leads overlaid with excluded mask regions for both buffers"
              />
              <figcaption>
                Red marks exclusion under the source classification and buffer
                policy, not confirmed historical human disturbance. White
                squares are 20 km footprints in 80 km contexts.
              </figcaption>
            </figure>
          </>
        ) : section === "New targets" ? (
          <>
            <p>
              Six new stereo AOIs were quality-selected and frozen before masked
              Earth ranking. The same-region, separated matched controls remain
              unfilled. No missing pair is replaced after seeing the finer
              measurements.
            </p>
            <div className="table-scroll">
              <table>
                <caption>
                  Prospective target and pair availability, {buffer} m buffer
                </caption>
                <thead>
                  <tr>
                    <th>AOI</th>
                    <th>Coordinates</th>
                    <th>Stereo valid</th>
                    <th>80 km image valid</th>
                    <th>Nomination / control</th>
                  </tr>
                </thead>
                <tbody>
                  {data.targets.map((target) => {
                    const frozen = data.pairs[buffer][target.id];
                    return (
                      <tr key={target.id}>
                        <th scope="row">
                          <a
                            href={target.stereo_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {target.id}
                          </a>
                        </th>
                        <td>
                          {target.latitude.toFixed(3)},{" "}
                          {target.longitude.toFixed(3)}
                        </td>
                        <td>
                          {(target.stereo_valid_fraction * 100).toFixed(1)}%
                        </td>
                        <td>
                          {(target.camera_valid_fraction * 100).toFixed(1)}%
                        </td>
                        <td>
                          {frozen.nomination ?? "Unfilled"} /{" "}
                          {frozen.control ?? "Unfilled"}
                          <details>
                            <summary>Why the pair is incomplete</summary>
                            {frozen.unfilled_reason}
                          </details>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <h3>Finer observations, without invented controls</h3>
            <p>
              100 m analysis spacing · real Copernicus DSM and CTX stereo
              observations · fixed slope/curvature scales. Shared fill and MOLA
              reference ancestry restrict independence. These distances are
              surrogate descriptors, not contact-mapping or field performance.
            </p>
            <div className="table-scroll">
              <table>
                <caption>
                  Nomination-only fine diagnostics, {buffer} m buffer
                </caption>
                <thead>
                  <tr>
                    <th>Target</th>
                    <th>Earth window</th>
                    <th>Joint Wasserstein</th>
                    <th>Hypsometric difference</th>
                    <th>State</th>
                  </tr>
                </thead>
                <tbody>
                  {data.fine_results
                    .filter((row) => String(row.buffer_m) === buffer)
                    .map((row) => (
                      <tr key={`${row.target_id}-${row.candidate_id}`}>
                        <th scope="row">{row.target_id}</th>
                        <td>{row.candidate_id}</td>
                        <td>
                          {row.joint_wasserstein?.toFixed(3) ?? "Unavailable"}
                        </td>
                        <td>
                          {row.hypsometric_difference?.toFixed(3) ??
                            "Unavailable"}
                        </td>
                        <td>{row.state.replaceAll("_", " ")}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <p>
              Complete primary target pairs:{" "}
              {data.primary_complete_target_pairs}. Paired significance and
              superiority are unassessable. Fine contact lines and independently
              blinded task labels have not been acquired.
            </p>
          </>
        ) : section === "Source support" ? (
          <>
            <h3>Observation counts expose interpolation</h3>
            <p>{data.mola_support_limit}</p>
            <div className="table-scroll">
              <table>
                <caption>
                  500 m cell centers mapped to native MOLA count bins
                </caption>
                <thead>
                  <tr>
                    <th>AOI</th>
                    <th>Local zero-count fraction</th>
                    <th>Context zero-count fraction</th>
                  </tr>
                </thead>
                <tbody>
                  {data.mola_support.map((row) => (
                    <tr key={row.target_id}>
                      <th scope="row">{row.target_id}</th>
                      <td>
                        {(row.local_zero_count_fraction * 100).toFixed(1)}%
                      </td>
                      <td>
                        {(row.context_zero_count_fraction * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>A relative rank change is not a changed physical loss</h3>
            {data.pool_sensitivity.map((row) => (
              <p key={row.candidate_id}>
                {row.candidate_id}: rank {row.old_rank} → {row.expanded_rank};
                robust loss {row.old_robust_loss.toFixed(6)} →{" "}
                {row.expanded_robust_loss.toFixed(6)}. {row.interpretation}
              </p>
            ))}
          </>
        ) : (
          <>
            <h3>What software cannot authenticate</h3>
            <ul>
              {data.limits.map((limit) => (
                <li key={limit}>{limit}</li>
              ))}
            </ul>
            <p>
              SIM 3292 is a 1:20,000,000 regional map. The contact-scoring API
              rejects a 200 m tolerance for that source rather than reporting an
              unsupported accuracy value.
            </p>
            <p>
              <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>{" "}
              ·{" "}
              <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>{" "}
              ·{" "}
              <a href="/docs" target="_blank" rel="noreferrer">
                API and contact-reference contract
              </a>
            </p>
            <div className="table-scroll">
              <table>
                <caption>Road-source availability</caption>
                <thead>
                  <tr>
                    <th>Region</th>
                    <th>Actual state</th>
                  </tr>
                </thead>
                <tbody>
                  {data.source_limits.map((source) => (
                    <tr key={source.region_id}>
                      <th scope="row">{source.region_id}</th>
                      <td>{source.osm_status.replaceAll("_", " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              Record SHA-256: <code className="hash">{data.record_hash}</code>
            </p>
            <p>
              Evidence SHA-256:{" "}
              <code className="hash">{data.evidence_hash}</code>
            </p>
          </>
        )}
      </div>
    </section>
  );
}
