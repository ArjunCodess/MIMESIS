import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Layers,
  MapPin,
  Mountain,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { bundleSchema } from "./data";
import type { Bundle, Candidate, Features, Ranking, Row, Target } from "./data";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
const DiscoveryPanel = lazy(() => import("./DiscoveryPanel"));
const ValidationPanel = lazy(() => import("./ValidationPanel"));
const ResearchPanel = lazy(() => import("./ResearchPanel"));
const EvidencePanel = lazy(() => import("./EvidencePanel"));
const groups = [
  "Slope distribution",
  "Relief & position",
  "Terrain organization",
  "Multiscale context",
];
const fmt = (value: number, decimals = 0) =>
  value.toLocaleString("en", {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  });
const coordinates = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(3)}° ${lat < 0 ? "S" : "N"}, ${Math.abs(lon).toFixed(3)}° ${lon < 0 ? "W" : "E"}`;

function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function App() {
  const [data, setData] = useState<Bundle | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(asset("bundle.json"), { signal: controller.signal })
      .then((response) => {
        if (!response.ok)
          throw new Error(`Research bundle returned HTTP ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then((value) => setData(bundleSchema.parse(value)))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Research bundle could not be read",
          );
      });
    return () => controller.abort();
  }, []);
  if (error)
    return (
      <main className="load-screen">
        <Mountain size={36} />
        <h1>The research bundle couldn’t load.</h1>
        <p>{error}</p>
        <p>
          Reload the page to try again, or open the downloaded research records.
        </p>
        <button onClick={() => window.location.reload()}>Retry loading</button>
      </main>
    );
  if (!data)
    return (
      <main className="load-screen" aria-busy="true">
        <Mountain size={36} />
        <h1>Opening the terrain atlas.</h1>
        <p>
          Reading measured terrain, source records and frozen investigations…
        </p>
      </main>
    );
  return <Workspace data={data} />;
}

function Workspace({ data }: { data: Bundle }) {
  const [page, setPage] = useState("Explore");
  const [archive, setArchive] = useState("");
  const [targetId, setTargetId] = useState(
    () => new URLSearchParams(window.location.search).get("target") ?? "jezero",
  );
  const [support, setSupport] = useState("500");
  const [candidateId, setCandidateId] = useState("");
  const [sort, setSort] = useState("robust");
  const [search, setSearch] = useState("");
  const [passingOnly, setPassingOnly] = useState(false);
  const [limit, setLimit] = useState(8);
  const [showHelp, setShowHelp] = useState(false);
  const [regionFilter, setRegionFilter] = useState("");
  const lookup = useMemo(
    () =>
      new Map(data.candidates.map((candidate) => [candidate.id, candidate])),
    [data.candidates],
  );
  const target =
    data.targets.find((item) => item.id === targetId) ?? data.targets[0];
  const result = (support === "500" ? data.rankings : data.rankings_1000)[
    target.id
  ];
  const selectedRow =
    result.candidates.find((row) => row.id === candidateId) ??
    result.candidates[0];
  const selected = lookup.get(selectedRow.id)!;
  const selectedRegion = data.regions.find(
    (region) => region.id === selected.region_id,
  )!;
  const visible = useMemo(() => {
    const rows = result.candidates.filter(
      (row) =>
        (!passingOnly || row.passes_provisional_threshold) &&
        (!regionFilter || lookup.get(row.id)!.region_id === regionFilter) &&
        row.id.toLowerCase().includes(search.toLowerCase()),
    );
    if (sort === "nominal")
      rows.sort(
        (a, b) => a.nominal_loss - b.nominal_loss || a.id.localeCompare(b.id),
      );
    if (sort === "slope")
      rows.sort(
        (a, b) =>
          a.group_losses[0] - b.group_losses[0] || a.id.localeCompare(b.id),
      );
    return rows;
  }, [result, passingOnly, search, sort, regionFilter, lookup]);
  function chooseTarget(id: string) {
    setTargetId(id);
    setRegionFilter("");
    setCandidateId("");
    setLimit(8);
    const url = new URL(window.location.href);
    url.searchParams.set("target", id);
    window.history.replaceState(null, "", url);
  }
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to research
      </a>
      <header className="header">
        <a className="brand" href="./" aria-label="MIMESIS home">
          <span className="wordmark">MIMESIS</span>
        </a>
        <nav aria-label="Main navigation">
          {["Explore", "Evidence", "Methods", "Data"].map((label) => (
            <button
              key={label}
              className={page === label ? "nav-active" : ""}
              aria-current={page === label ? "page" : undefined}
              onClick={() => setPage(label)}
            >
              {label}
            </button>
          ))}
        </nav>
        <a
          className="challenge-link"
          href="https://www.spaceappschallenge.org/2026/challenges/permanent-moon-base-locations-and-mars/"
          target="_blank"
          rel="noreferrer"
        >
          Space Apps 2026 <ArrowUpRight size={15} />
        </a>
      </header>
      <main id="main">
        <div className="intro">
          <div>
            <h1>
              {page === "Explore"
                ? "Compare planetary terrain with Earth"
                : page === "Evidence"
                  ? "Evidence"
                  : page === "Methods"
                    ? "Methods"
                    : "Data"}
            </h1>
          </div>
          {page === "Explore" ? (
            <button
              className="outline"
              onClick={() =>
                download(`mimesis-${target.id}-${support}m.json`, {
                  protocol: data.protocol,
                  protocol_hash: data.protocol_hash,
                  source_manifest: data.source_manifest,
                  sources: data.sources,
                  target,
                  candidates: data.candidates,
                  ranking: result,
                  investigation: data.investigations[target.id],
                  regions: data.regions,
                  experiment: data.experiment,
                  planetary_imagery: data.planetary_imagery,
                  novelty_audit: data.novelty_audit,
                  evidence_hash: data.evidence_hash,
                })
              }
            >
              <ArrowDownToLine size={16} /> Export evidence
            </button>
          ) : (
            <a className="outline" href={asset("mimesis-paper.pdf")} download>
              <ArrowDownToLine size={16} /> Research paper
            </a>
          )}
        </div>
        {showHelp && (
          <div className="help-panel">
            <p>
              Terrain resemblance supports a mapping hypothesis. Corroboration,
              novelty and independent review are not established. Scores are
              distances, not probabilities. The imagery rubric is
              model-assisted. This study does not assess geological origin,
              mineralogy, trafficability or permanent-base suitability.
            </p>
            <button
              aria-label="Close research limits"
              onClick={() => setShowHelp(false)}
            >
              <X size={18} />
            </button>
          </div>
        )}
        {page === "Evidence" ? (
          <>
            <Suspense fallback={<p>Opening the evidence/</p>}>
              <EvidencePanel />
            </Suspense>
            <details className="archive">
              <summary>Inspect frozen investigations</summary>
              <Investigations
                data={data}
                lookup={lookup}
                open={(id, candidate) => {
                  chooseTarget(id);
                  setCandidateId(candidate);
                  setPage("Explore");
                }}
              />
            </details>
            <details
              className="archive"
              onToggle={(event) =>
                setArchive(event.currentTarget.open ? "Research" : "")
              }
            >
              <summary>Earlier experiments and full tables</summary>
              {archive && (
                <>
                  <div className="evidence-switch">
                    {["Research", "Validation", "Discovery"].map((name) => (
                      <button
                        key={name}
                        aria-pressed={archive === name}
                        onClick={() => setArchive(name)}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                  <a
                    href={asset(
                      archive === "Research"
                        ? "research_v6.json"
                        : archive === "Validation"
                          ? "natural_land_v5.json"
                          : "discovery.json.gz",
                    )}
                    download
                  >
                    Export {archive.toLowerCase()} record
                  </a>
                  <Suspense fallback={<p>Opening earlier experiments/</p>}>
                    {archive === "Research" ? (
                      <ResearchPanel />
                    ) : archive === "Validation" ? (
                      <ValidationPanel />
                    ) : (
                      <DiscoveryPanel />
                    )}
                  </Suspense>
                </>
              )}
            </details>
          </>
        ) : page === "Explore" ? (
          <>
            <section className="controls" aria-label="Search configuration">
              <div className="control-field">
                <label htmlFor="target">Planetary study window</label>
                <div className="select-wrap">
                  <select
                    id="target"
                    value={target.id}
                    onChange={(event) => chooseTarget(event.target.value)}
                  >
                    {["Mars", "Moon"].map((body) => (
                      <optgroup key={body} label={body}>
                        {data.targets
                          .filter((item) => item.body === body)
                          .map((item) => (
                            <option value={item.id} key={item.id}>
                              {item.name} , {item.body}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                  <ChevronDown size={15} />
                </div>
              </div>
              <fieldset className="support">
                <legend>Analysis grid</legend>
                {["500", "1000"].map((value) => (
                  <button
                    key={value}
                    aria-pressed={support === value}
                    className={support === value ? "chosen" : ""}
                    onClick={() => setSupport(value)}
                  >
                    {value === "500" ? "500 m" : "1 km"}
                  </button>
                ))}
              </fieldset>
              <button
                className="limits-toggle"
                onClick={() => setShowHelp(!showHelp)}
                aria-expanded={showHelp}
              >
                <CircleHelp size={16} /> Research limits
              </button>
            </section>
            <section
              className="terrain-pair"
              aria-label="Planetary and terrestrial terrain"
            >
              <div className="terrain-panel target-panel">
                <div className="panel-heading">
                  <span>{target.body} reference</span>
                  <span>
                    {target.source.toUpperCase()} ,{" "}
                    {support === "500" ? "500 m" : "1 km"} grid
                  </span>
                </div>
                <div className="target-image">
                  <img
                    src={asset(
                      support === "500"
                        ? target.image
                        : target.id + "-1000.png",
                    )}
                    alt={`${target.name}, 80 km elevation-derived terrain rendering`}
                  />
                  <svg
                    viewBox="0 0 800 800"
                    aria-label="20 kilometre study footprint within 80 kilometre context"
                  >
                    <rect
                      x="300"
                      y="300"
                      width="200"
                      height="200"
                      className="target-footprint"
                    />
                    <path
                      d="M400 280v-20m0 280v-20M280 400h-20m280 0h-20"
                      className="crosshair"
                    />
                  </svg>
                  <div className="map-label">
                    <Mountain size={16} />
                    <span>
                      {target.name}
                      <small>
                        {coordinates(target.latitude, target.longitude)}
                      </small>
                    </span>
                  </div>
                  <div className="map-bottom">
                    <span className="scale-bar">20 km</span>
                    <span>Elevation-derived view , 80 km context</span>
                  </div>
                  <span className="north">N ↑</span>
                </div>
                <div className="panel-caption">
                  <span>
                    {fmt(target.features[support].relief_m)} m local relief
                  </span>
                  <span>
                    {fmt(target.features[support].slope_median_deg, 1)}° median
                    slope
                  </span>
                  <span>{target.split.replace("_", " ")} case</span>
                </div>
              </div>
              <div className="terrain-panel earth-panel">
                <div className="panel-heading">
                  <span>Earth search domain</span>
                  <span>NASADEM , four adjacent tiles</span>
                </div>
                <EarthMap
                  earth={selectedRegion}
                  support={support}
                  candidates={data.candidates.filter(
                    (candidate) => candidate.region_id === selected.region_id,
                  )}
                  ranked={result.candidates}
                  selected={selected}
                  onSelect={setCandidateId}
                />
                <div className="panel-caption">
                  <span>
                    <MapPin size={13} /> {selectedRegion.name}
                  </span>
                  <span>{fmt(selectedRegion.valid_windows)} valid windows</span>
                  <span>
                    {fmt(selectedRegion.stride_m / 1000)} km search stride
                  </span>
                </div>
              </div>
            </section>
            <section className="results-layout">
              <div className="ranked">
                <div className="section-title">
                  <h2>
                    Terrain candidates <span>{visible.length}</span>
                  </h2>
                  <label className="sort">
                    <SlidersHorizontal size={14} />
                    <select
                      aria-label="Rank candidates by"
                      value={sort}
                      onChange={(e) => setSort(e.target.value)}
                    >
                      <option value="robust">Worst-case loss</option>
                      <option value="nominal">Nominal baseline</option>
                      <option value="slope">Slope-only baseline</option>
                    </select>
                  </label>
                </div>
                <div className="table-filters">
                  <select
                    aria-label="Filter Earth region"
                    value={regionFilter}
                    onChange={(event) => {
                      setRegionFilter(event.target.value);
                      if (event.target.value)
                        setCandidateId(
                          result.candidates.find(
                            (row) =>
                              lookup.get(row.id)!.region_id ===
                              event.target.value,
                          )?.id ?? "",
                        );
                      setLimit(8);
                    }}
                  >
                    <option value="">All Earth regions</option>
                    {data.regions.map((region) => (
                      <option key={region.id} value={region.id}>
                        {region.name}
                      </option>
                    ))}
                  </select>
                  <label className="search">
                    <Search size={15} />
                    <input
                      aria-label="Find candidate by ID"
                      placeholder="Find a study window…"
                      value={search}
                      onChange={(e) => {
                        setSearch(e.target.value);
                        setLimit(8);
                      }}
                    />
                  </label>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={passingOnly}
                      onChange={(e) => setPassingOnly(e.target.checked)}
                    />{" "}
                    Within provisional cutoff
                  </label>
                </div>

                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Rank</th>
                        <th scope="col">Earth window</th>
                        <th
                          scope="col"
                          aria-label="Worst-case loss, lower is closer"
                        >
                          Loss
                        </th>
                        <th scope="col">
                          <span className="sr-only">View candidate</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {visible.slice(0, limit).map((row) => (
                        <CandidateRow
                          key={row.id}
                          row={row}
                          candidate={lookup.get(row.id)!}
                          selected={selected.id === row.id}
                          onSelect={setCandidateId}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
                {visible.length === 0 && (
                  <div className="empty">
                    <Mountain size={28} />
                    <h3>No windows meet this filter.</h3>
                    <p>
                      {passingOnly
                        ? "The lunar cases may have no candidate within the provisional cutoff. Nearest neighbours remain inspectable."
                        : "Try another candidate ID."}
                    </p>
                    <button
                      onClick={() => {
                        setPassingOnly(false);
                        setSearch("");
                        setRegionFilter("");
                      }}
                    >
                      Show all measured candidates
                    </button>
                  </div>
                )}
                <div className="table-footer">
                  <span>
                    Showing {Math.min(limit, visible.length)} of{" "}
                    {visible.length} , overlapping study windows
                  </span>
                  {limit < visible.length && (
                    <button onClick={() => setLimit(limit + 20)}>
                      Show 20 more <ChevronDown size={14} />
                    </button>
                  )}
                </div>
              </div>
              <aside className="selection-summary">
                <h2>{selected.id}</h2>
                <p>{coordinates(selected.latitude, selected.longitude)}</p>
                <div className="loss-number">
                  {fmt(selectedRow.robust_loss, 4)}
                  <span>worst-case loss</span>
                </div>
                <span
                  className={`evidence-badge ${selectedRow.passes_provisional_threshold ? "" : "outside"}`}
                >
                  {selectedRow.passes_provisional_threshold
                    ? "Within provisional cutoff"
                    : "Outside provisional cutoff"}
                </span>

                <dl>
                  <div>
                    <dt>Local relief</dt>
                    <dd>{fmt(selected.features[support].relief_m)} m</dd>
                  </div>
                  <div>
                    <dt>Median slope</dt>
                    <dd>
                      {fmt(selected.features[support].slope_median_deg, 1)}°
                    </dd>
                  </div>
                  <div>
                    <dt>Valid local area</dt>
                    <dd>
                      {fmt(selected.features[support].valid_fraction * 100, 1)}%
                    </dd>
                  </div>
                  <div>
                    <dt>Top-10 scenario inclusion</dt>
                    <dd>{fmt(selectedRow.top10_inclusion_fraction * 100)}%</dd>
                  </div>
                </dl>
                <a href="#dossier">
                  Inspect evidence below <ChevronDown size={15} />
                </a>
              </aside>
            </section>
            <Dossier
              data={data}
              target={target}
              candidate={selected}
              row={selectedRow}
              support={support}
              result={result}
            />
          </>
        ) : page === "Methods" ? (
          <Methods data={data} />
        ) : (
          <Sources data={data} />
        )}
      </main>
      <footer>
        <a className="wordmark" href="./">
          MIMESIS
        </a>
        <p className="builder-credit">
          Built by{" "}
          <a
            href="https://arjuncodess.is-a.dev/"
            target="_blank"
            rel="noreferrer"
          >
            Arjun Vijay Prakash
          </a>
          <span>
            Grade XI, City Montessori School, Kanpur Road, Lucknow, India
          </span>
        </p>
        <a href={asset("mimesis-paper.pdf")} download>
          Read the research report <ArrowDownToLine size={14} />
        </a>
      </footer>
    </>
  );
}

function EarthMap({
  earth,
  support,
  candidates,
  ranked,
  selected,
  onSelect,
}: {
  earth: Bundle["regions"][number];
  support: string;
  candidates: Candidate[];
  ranked: Row[];
  selected: Candidate;
  onSelect: (id: string) => void;
}) {
  const [zoom, setZoom] = useState(false);
  const top = new Set(ranked.slice(0, 10).map((row) => row.id));
  const size = earth.extent_m;
  const points = candidates.filter((c) => top.has(c.id));
  const x = (value: number) => ((value + size / 2) / size) * 800;
  const y = (value: number) => ((size / 2 - value) / size) * 800;
  const footprintSize = (20000 / size) * 800;
  return (
    <div className={`earth-map ${zoom ? "zoomed" : ""}`}>
      <div className="map-content">
        <img
          src={asset(support === "500" ? earth.image : earth.image_1000)}
          alt={`NASADEM-derived terrain across ${earth.name}`}
        />
        <svg
          viewBox="0 0 800 800"
          aria-label="Ranked study window footprints, use the candidate table for keyboard selection"
        >
          {points
            .filter((c) => c.id !== selected.id)
            .map((c) => (
              <g
                key={c.id}
                className="map-window"
                onClick={() => onSelect(c.id)}
              >
                <title>{c.id}</title>
                <rect
                  x={x(c.easting_m) - footprintSize / 2}
                  y={y(c.northing_m) - footprintSize / 2}
                  width={footprintSize}
                  height={footprintSize}
                />
                <circle cx={x(c.easting_m)} cy={y(c.northing_m)} r="4" />
              </g>
            ))}
          <g className="map-selection">
            <rect
              x={x(selected.easting_m) - footprintSize / 2}
              y={y(selected.northing_m) - footprintSize / 2}
              width={footprintSize}
              height={footprintSize}
            />
            <circle
              cx={x(selected.easting_m)}
              cy={y(selected.northing_m)}
              r="7"
            />
            <text x={x(selected.easting_m) + 14} y={y(selected.northing_m) + 5}>
              Selected
            </text>
          </g>
        </svg>
      </div>
      <div className="map-label">
        <MapPin size={17} />
        <span>
          {earth.name}
          <small>{coordinates(earth.center[1], earth.center[0])}</small>
        </span>
      </div>
      <span className="north">N ↑</span>
      <button
        className="map-zoom"
        onClick={() => setZoom(!zoom)}
        aria-pressed={zoom}
      >
        <Search size={15} />
        {zoom ? "Full domain" : "Zoom view"}
      </button>
      <div className="map-bottom">
        <span
          className="scale-bar"
          style={{ width: `${(20000 / earth.extent_m) * 100}%` }}
        >
          {zoom ? "10 km" : "20 km"}
        </span>
        <span>Elevation, not satellite color</span>
      </div>
    </div>
  );
}

function CandidateRow({
  row,
  candidate,
  selected,
  onSelect,
}: {
  row: Row;
  candidate: Candidate;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <tr className={selected ? "selected-row" : ""}>
      <td>{String(row.rank).padStart(2, "0")}</td>
      <th scope="row">
        <button onClick={() => onSelect(row.id)} aria-pressed={selected}>
          {row.id}
          <small>{coordinates(candidate.latitude, candidate.longitude)}</small>
        </button>
      </th>
      <td className="loss-cell">
        {fmt(row.robust_loss, 4)}
        <span className="loss-track">
          <span style={{ width: `${row.robust_loss * 100}%` }} />
        </span>
      </td>
      <td>
        <button
          className="icon-button"
          aria-label={`Inspect ${row.id}`}
          onClick={() => onSelect(row.id)}
        >
          <ChevronRight size={16} />
        </button>
      </td>
    </tr>
  );
}

function Distribution({ a, b }: { a: Features; b: Features }) {
  const labels = [
    "0-1",
    "1-2",
    "2-3",
    "3-5",
    "5-8",
    "8-12",
    "12-20",
    "20-35",
    "35-60",
    "60-90",
  ];
  const max = Math.max(...a.slope_histogram, ...b.slope_histogram, 0.1);
  return (
    <div className="distribution">
      <div className="legend">
        <span>
          <i className="target-key" />
          Planetary target
        </span>
        <span>
          <i className="earth-key" />
          Earth candidate
        </span>
      </div>
      <div
        className="histogram"
        role="img"
        aria-label="Slope distribution comparison. See the accessible data table below."
      >
        {labels.map((label, index) => (
          <div className="hist-bin" key={label}>
            <div className="bin-bars">
              <span
                style={{ height: `${(a.slope_histogram[index] / max) * 100}%` }}
                title={`Target ${fmt(a.slope_histogram[index] * 100, 1)}%`}
              />
              <span
                style={{ height: `${(b.slope_histogram[index] / max) * 100}%` }}
                title={`Earth ${fmt(b.slope_histogram[index] * 100, 1)}%`}
              />
            </div>
            <small>{label}</small>
          </div>
        ))}
      </div>
      <p className="axis-caption">
        Slope in degrees , equal-area grid-cell fractions
      </p>
      <details>
        <summary>View distribution values</summary>
        <table>
          <thead>
            <tr>
              <th>Slope °</th>
              <th>Target %</th>
              <th>Earth %</th>
            </tr>
          </thead>
          <tbody>
            {labels.map((label, i) => (
              <tr key={label}>
                <td>{label}</td>
                <td>{fmt(a.slope_histogram[i] * 100, 1)}</td>
                <td>{fmt(b.slope_histogram[i] * 100, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function Dossier({
  data,
  target,
  candidate,
  row,
  support,
  result,
}: {
  data: Bundle;
  target: Target;
  candidate: Candidate;
  row: Row;
  support: string;
  result: Ranking;
}) {
  const [tab, setTab] = useState("Terrain comparison");
  const investigation = data.investigations[target.id];
  const record = investigation.shortlist.find(
    (item) => item.candidate_id === candidate.id,
  );
  return (
    <section className="dossier" id="dossier">
      <div className="section-title">
        <div>
          <h2>Candidate evidence</h2>
          <p>
            {candidate.id} ↔ {target.name} ,{" "}
            {support === "500" ? "500 m" : "1 km"} analysis grid
          </p>
        </div>
        <button
          className="outline"
          onClick={() =>
            download(`${candidate.id}-${target.id}-dossier.json`, {
              target,
              candidate,
              ranking: row,
              run_hash: result.run_hash,
              protocol: data.protocol,
              source_manifest: data.source_manifest,
              evidence: record ?? {
                claim_level: "screened_candidate",
                shortlist_membership: false,
                corroboration: "unassessable",
                novelty_status: "unresolved",
                reviewer_status: "not_reviewed",
              },
              planetary_imagery: data.planetary_imagery.find(
                (item) => item.target_id === target.id,
              ),
              novelty_audit: data.novelty_audit,
            })
          }
        >
          <ArrowDownToLine size={15} /> Export dossier
        </button>
      </div>
      <div className="tabs" role="tablist" aria-label="Candidate evidence">
        {[
          "Terrain comparison",
          "Independent imagery",
          "Evidence & limits",
          "Source record",
        ].map((label) => (
          <button
            key={label}
            role="tab"
            aria-selected={tab === label}
            id={`tab-${label.replaceAll(" ", "-")}`}
            aria-controls="evidence-panel"
            onClick={() => setTab(label)}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="evidence-panel"
        aria-labelledby={`tab-${tab.replaceAll(" ", "-")}`}
      >
        {tab === "Terrain comparison" ? (
          <div className="comparison">
            <div>
              <h3>Where the terrain agrees</h3>
              <p>
                Shared-bin slope distributions compare broad terrain gradients
                at matched grid spacings.
              </p>
              <Distribution
                a={target.features[support]}
                b={candidate.features[support]}
              />
            </div>
            <div className="contributions">
              <h3>What contributes to discrepancy</h3>
              <p>
                Weighted nominal losses sum to {fmt(row.nominal_loss, 4)}.
                Worst-case loss is the worst scenario.
              </p>
              {groups.map((label, i) => (
                <div className="contribution" key={label}>
                  <div>
                    <span>{label}</span>
                    <strong>{fmt(row.contributions[i], 4)}</strong>
                  </div>
                  <span className="contribution-track">
                    <span
                      style={{
                        width: `${(row.contributions[i] / result.weights[i]) * 100}%`,
                      }}
                    />
                  </span>
                  <small>
                    Group budget {fmt(result.weights[i] * 100)}% , bounded loss{" "}
                    {fmt(row.group_losses[i], 3)}
                  </small>
                </div>
              ))}
              <div className="scenario-note">
                <Layers size={18} />
                <p>
                  {result.scenario_count} sensitivity scenarios. Rank{" "}
                  {row.scenario_rank_range[0]}-{row.scenario_rank_range[1]};
                  top-10 inclusion {fmt(row.top10_inclusion_fraction * 100)}%.
                  These are scenario outcomes, not confidence intervals.
                </p>
              </div>
            </div>
          </div>
        ) : tab === "Independent imagery" ? (
          record ? (
            <div className="image-assessment">
              <p className="assessment-disclosure">
                Model-assisted visual assessment, not independent expert review.
                Numerical terrain ranks remain unchanged.
              </p>
              <div className="optical-pair">
                <figure>
                  {record.imagery_packet.planetary_image &&
                  record.imagery_packet.planetary_valid_fraction >= 0.95 ? (
                    <img
                      loading="lazy"
                      src={asset(record.imagery_packet.planetary_image)}
                      alt={`${target.name} separately acquired camera context, 80 km`}
                    />
                  ) : (
                    <div className="missing-image">
                      Usable planetary camera coverage is unavailable.
                    </div>
                  )}
                  <figcaption>
                    {target.name} , separate optical acquisition , 80 km context
                  </figcaption>
                </figure>
                <figure>
                  <img
                    loading="lazy"
                    src={asset(record.imagery_packet.earth_image)}
                    alt={`${candidate.id} masked Landsat RGB, 80 km context`}
                  />
                  <figcaption>
                    {candidate.id} , HLS RGB , 80 km context
                  </figcaption>
                </figure>
              </div>
              <p>
                Clear Earth area:{" "}
                {fmt(record.imagery_packet.earth_local_clear_fraction * 100, 1)}
                % locally,{" "}
                {fmt(
                  record.imagery_packet.earth_context_clear_fraction * 100,
                  1,
                )}
                % in context. Pale areas are missing or masked. The optical
                views do not measure slope or composition.
              </p>
              <h3>{record.assessment_outcome.replaceAll("_", " ")}</h3>
              <div className="rubric-observations">
                {record.corroboration.map((item) => (
                  <article key={item.requirement}>
                    <div>
                      <strong>{item.requirement.replaceAll("_", " ")}</strong>
                      <span className="evidence-badge">{item.status}</span>
                    </div>
                    <p>{item.reason}</p>
                  </article>
                ))}
              </div>
              <p>{record.source_lineage}</p>
              <a href={asset("novelty_audit.json")} download>
                Inspect the focused novelty ledger <ArrowDownToLine size={14} />
              </a>
            </div>
          ) : (
            <div className="empty">
              <h3>This window is outside the frozen image investigation.</h3>
              <p>
                Open a frozen footprint from Investigations to inspect its
                source-linked imagery and assessment.
              </p>
            </div>
          )
        ) : tab === "Evidence & limits" ? (
          <div className="evidence-columns">
            <div>
              <h3>Screened candidate</h3>
              <p>
                {record
                  ? `Frozen as a ${record.role.replaceAll("_", " ")} for this target.`
                  : "This window is in the measured search pool but is not in the frozen investigation shortlist."}{" "}
                Ranking never promotes a discovery claim.
              </p>
              <dl className="gate-list">
                <div>
                  <dt>Terrain nomination</dt>
                  <dd>
                    <Check size={14} /> Measured
                  </dd>
                </div>
                <div>
                  <dt>Separate imagery corroboration</dt>
                  <dd>
                    {record
                      ? record.assessment_outcome.replaceAll("_", " ")
                      : "Not assessed"}
                  </dd>
                </div>
                <div>
                  <dt>Footprint-specific novelty search</dt>
                  <dd>
                    {record?.novelty_status.replaceAll("_", " ") ??
                      "Not audited"}
                  </dd>
                </div>
                <div>
                  <dt>Independent scientific review</dt>
                  <dd>Not reviewed</dd>
                </div>
              </dl>
              <p>
                Frozen footprints have model-assisted image observations and
                counterevidence. Missing evidence is not a positive result, and
                no external scientist has reviewed these interpretations.
              </p>
            </div>
            <div>
              <h3>What does not transfer</h3>
              <p>
                A matching landform distribution cannot establish shared
                composition, formation process, traction, bearing strength,
                radiation, gravity response, pressure or lunar thermal
                conditions.
              </p>
              <h3>Measurements that would test it</h3>
              <ul>
                <li>Field slope transects to check the DEM-scale relief.</li>
                <li>
                  Surface descriptions and grain sizes to test substrate
                  assumptions.
                </li>
                <li>
                  Separate planetary imagery interpretation for basin, margin
                  and transition requirements.
                </li>
              </ul>
              <p>
                Study footprints are research nominations. Access and permits
                have not been checked.
              </p>
            </div>
          </div>
        ) : (
          <div className="evidence-columns">
            <div>
              <h3>Measurement record</h3>
              <dl className="gate-list">
                <div>
                  <dt>Earth source</dt>
                  <dd>NASADEM , {candidate.region}</dd>
                </div>
                <div>
                  <dt>Planetary source</dt>
                  <dd>{target.source.toUpperCase()}</dd>
                </div>
                <div>
                  <dt>Study / context</dt>
                  <dd>20 km / 80 km</dd>
                </div>
                <div>
                  <dt>Processing</dt>
                  <dd>Gaussian support matching</dd>
                </div>
                <div>
                  <dt>Reserved HLS clear coverage</dt>
                  <dd>
                    {fmt(candidate.reserved_hls_valid_fraction * 100, 1)}% of
                    local window
                  </dd>
                </div>
                <div>
                  <dt>Target reference</dt>
                  <dd>{target.projection}</dd>
                </div>
              </dl>
            </div>
            <div>
              <h3>Reproduce this decision</h3>
              <p>
                All rankings are precomputed by the same Python package served
                through the API. The app does not calculate a separate
                similarity formula.
              </p>
              <p className="hash">
                Run SHA-256
                <br />
                <code>{result.run_hash}</code>
              </p>
              <p className="hash">
                Protocol SHA-256
                <br />
                <code>{data.protocol_hash}</code>
              </p>
              <a href={asset("source_manifest.json")} download>
                Download source checksums <ArrowDownToLine size={14} />
              </a>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function Investigations({
  data,
  lookup,
  open,
}: {
  data: Bundle;
  lookup: Map<string, Candidate>;
  open: (target: string, candidate: string) => void;
}) {
  return (
    <div className="reading-page">
      <p className="page-note">
        The corrected investigation requires non-overlapping 80 km contexts and
        category/coverage-matched alternatives. It retains{" "}
        {Object.values(data.investigations).reduce(
          (n, investigation) => n + investigation.actual_count,
          0,
        )}{" "}
        comparisons; unfilled slots remain explicit. Model-assisted observations
        are separate from independent scientific review.
      </p>
      {data.targets.map((target) => {
        const investigation = data.investigations[target.id];
        return (
          <section className="investigation" key={target.id}>
            <div className="section-title">
              <div>
                <h2>
                  {target.name} <span>{target.body}</span>
                </h2>
                <p>
                  {target.split.replace("_", " ")} ,{" "}
                  {investigation.actual_count} of {investigation.planned_count}{" "}
                  planned windows retained
                </p>
              </div>
              <span className="evidence-badge">Unresolved hypotheses</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Frozen footprint</th>
                    <th>Role</th>
                    <th>Corroboration</th>
                    <th>Novelty</th>
                    <th>Review</th>
                  </tr>
                </thead>
                <tbody>
                  {investigation.shortlist.map((item) => (
                    <tr key={item.candidate_id}>
                      <th>
                        <button
                          className="table-link"
                          onClick={() => open(target.id, item.candidate_id)}
                        >
                          {item.candidate_id} <ArrowUpRight size={14} />
                          <small>
                            {coordinates(
                              lookup.get(item.candidate_id)!.latitude,
                              lookup.get(item.candidate_id)!.longitude,
                            )}
                          </small>
                        </button>
                      </th>
                      <td>{item.role.replaceAll("_", " ")}</td>
                      <td>{item.assessment_outcome.replaceAll("_", " ")}</td>
                      <td>{item.novelty_status}</td>
                      <td>Not reviewed</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details>
              <summary>
                Unfilled investigation slots (
                {investigation.unfilled_slots.length})
              </summary>
              <ul>
                {investigation.unfilled_slots.map((slot, index) => (
                  <li key={index}>
                    {slot.role.replaceAll("_", " ")}: {slot.reason}.
                  </li>
                ))}
              </ul>
            </details>
            <details>
              <summary>Inspect the withheld-evidence rubric</summary>
              <p>
                Basin floor, ridge margin and relief transition are mandatory
                observable requirements. Complete local and contextual camera
                coverage is required. Missing or ambiguous imagery stays
                unassessable; a second rendering of a ranking DEM is not
                separate acquisition evidence.
              </p>
            </details>
          </section>
        );
      })}
    </div>
  );
}

function Methods({ data }: { data: Bundle }) {
  const targetNames: Record<string, string> = Object.fromEntries(
    data.targets.map((target) => [target.id, target.name]),
  );
  return (
    <div className="reading-page">
      <ol className="method-sequence">
        <li>
          <h2>Match the analysis scale</h2>
          <p>
            Measure each 20 km study window inside an 80 km context. Smooth
            before sampling at 500 m and 1 km. Grid spacing does not establish
            source resolution.
          </p>
        </li>
        <li>
          <h2>Compare terrain descriptors</h2>
          <p>
            Compare slope distributions, relief, terrain organization and
            context. Exclude absolute elevation from cross-body discrepancy.
            Weights and tolerances are fixed protocol assumptions.
          </p>
        </li>
        <li>
          <h2>Test sensitivity</h2>
          <p>
            Report the worst discrepancy across 35 scenarios, including weight
            perturbations, grid spacing and mask erosion. The score is not a
            probability of geological relevance.
          </p>
        </li>
        <li>
          <h2>Require independent evidence</h2>
          <p>
            Apply terrain, land-cover and imagery gates before nomination.
            Geological corroboration, independent review and mapping-task
            outcomes are still required for stronger claims.
          </p>
        </li>
      </ol>
      <div className="download-links">
        <a href={asset("mimesis-paper.pdf")} download>
          Research paper
        </a>
        <a href={asset("frozen_protocol.json")} download>
          Regional protocol
        </a>
        <a href={asset("pit-calibration-protocol-v10.json")} download>
          Pit calibration protocol
        </a>
      </div>
      <details className="benchmark archive">
        <summary>Inspect all six sensitivity comparisons</summary>
        <h2>Measured sensitivity across the six cases</h2>
        <p>
          Top-10 overlap compares 500 m and 1 km worst-case rankings. Values
          below 0.60 trigger the predeclared warning.
        </p>
        <div className="benchmark-chart">
          {data.benchmark.map((item) => (
            <div key={item.target_id}>
              <span>{targetNames[item.target_id]}</span>
              <div>
                <span
                  style={{ width: `${item.top10_jaccard_500_vs_1000 * 100}%` }}
                  className={item.rank_stability_warning ? "warning-bar" : ""}
                />
              </div>
              <strong>{fmt(item.top10_jaccard_500_vs_1000, 3)}</strong>
            </div>
          ))}
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Target</th>
                <th>Worst-case minimum</th>
                <th>Rank correlation</th>
                <th>Worst-case winner</th>
                <th>Nominal winner</th>
                <th>Slope-only winner</th>
              </tr>
            </thead>
            <tbody>
              {data.benchmark.map((item) => (
                <tr key={item.target_id}>
                  <th>{targetNames[item.target_id]}</th>
                  <td>{fmt(item.robust_minimum, 4)}</td>
                  <td>{fmt(item.rank_spearman, 3)}</td>
                  <td>{item.robust_winner}</td>
                  <td>{item.nominal_winner}</td>
                  <td>{item.slope_only_winner}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Baseline differences do not demonstrate superiority without
          independent relevance judgments.
        </p>
      </details>
      <details className="archive">
        <summary>Scope and exclusions</summary>
        <ul>
          {data.protocol.scope_deviations.map((item) => (
            <li key={item}>{item}.</li>
          ))}
        </ul>
        <a href={asset("frozen_protocol.json")} download>
          Inspect the frozen protocol <ArrowDownToLine size={15} />
        </a>
      </details>
    </div>
  );
}

function Sources({ data }: { data: Bundle }) {
  return (
    <div className="reading-page">
      <section className="source-intro">
        <div className="download-links">
          <a href={asset("source_manifest.json")} download>
            Source manifest <ArrowDownToLine size={15} />
          </a>
          <a href={asset("rankings.csv")} download>
            Full rankings CSV <ArrowDownToLine size={15} />
          </a>
          <a href={asset("bundle.json")} download>
            Complete offline bundle <ArrowDownToLine size={15} />
          </a>
        </div>
      </section>
      <section className="reserved-imagery">
        <img
          loading="lazy"
          src={asset(data.reserved_imagery.image)}
          alt="Reserved HLS RGB context reprojected to the Earth search domain. Pale areas lack clear, valid imagery."
        />
        <div>
          <h2>Reserved imagery, visible coverage gaps.</h2>
          <p>
            The displayed Landsat mosaic combines separate acquisitions
            beginning {data.reserved_imagery.acquired_at.slice(0, 10)}. Pale
            areas have no valid imagery after cloud, cirrus, adjacency, shadow,
            snow and water masking. Frozen footprints have model-assisted
            landform assessments paired with planetary camera images; external
            scientific review has not been performed.
          </p>
          <p>
            {data.reserved_imagery.display}. The image is reprojected to the 232
            km Atacama display domain. Candidate source records expose local
            clear-area coverage.
          </p>
        </div>
      </section>
      {data.sources.map((source) => (
        <details className="source-record archive" key={source.id}>
          <summary>
            {source.name} / {source.body}
          </summary>
          <div>
            <h2>{source.name}</h2>
            <a href={source.url} target="_blank" rel="noreferrer">
              Open source archive <ArrowUpRight size={15} />
            </a>
          </div>
          <div>
            <dl>
              <div>
                <dt>Measurement units</dt>
                <dd>{source.units}</dd>
              </div>
              <div>
                <dt>Source spacing</dt>
                <dd>{source.nominal_spacing}</dd>
              </div>
              <div>
                <dt>Encoding</dt>
                <dd>{source.encoding}</dd>
              </div>
            </dl>
            <p>{source.lineage}.</p>
            <p className="muted">{source.rights}.</p>
          </div>
        </details>
      ))}
      <details className="archive">
        <summary>Rebuild the investigation and read disclosures</summary>
        <pre>
          <code>
            python -m pip install -e ".[test]"{"\n"}python scripts/acquire.py
            mola lola{"\n"}python scripts/build_research.py{"\n"}python -m
            pytest{"\n"}npm install{"\n"}npm run build{"\n"}python -m uvicorn
            services.api.main:app --host 127.0.0.1 --port 8000
          </code>
        </pre>
        <p>
          Core terrain access uses public archives and requires no NASA API key.
          Additional Earthdata products may require an Earthdata account.
          Credentials never belong in a research export.
        </p>
        <h3>AI and prior-work disclosure</h3>
        <p>
          The supplied planning documents date November 4-5, 2026. Codex
          assisted with implementation, scientific methods text and tests. No
          organizer or independent scientist has reviewed this release, and no
          event submission has been made.
        </p>
      </details>
    </div>
  );
}
