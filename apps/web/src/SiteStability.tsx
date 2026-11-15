import { useState } from "react";
import record from "./generated/site-stability.json";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;

export default function SiteStability() {
  const [targetId, setTargetId] = useState("nili");
  const target = record.cases.find((item) => item.target_id === targetId)!;
  const scalar = target.methods[0];
  const nearby = scalar.geographic_matches.find((item) => item.radius_km === 10)!;
  const [first, second] = scalar.winners;
  const midpointX = (first.easting_m + second.easting_m) / 2;
  const midpointY = (first.northing_m + second.northing_m) / 2;
  const scale = Math.min(480 / (Math.abs(first.easting_m - second.easting_m) + 26000), 280 / (Math.abs(first.northing_m - second.northing_m) + 26000));
  const colors = ["#a45334", "#536c55"];
  return (
    <section className="pit-study" aria-label="Geographic stability">
      <div className="pit-toolbar">
        <label>
          Target
          <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
            {record.cases.map((item) => <option key={item.target_id} value={item.target_id}>{item.target_name}</option>)}
          </select>
        </label>
        <a href={asset("site-shortlist.geojson")} download>Download locations</a>
      </div>
      <div className="evidence-layout pit-layout">
        <figure>
          <svg viewBox="0 0 600 400" role="img" aria-labelledby="footprint-title footprint-description" style={{ width: "100%", display: "block" }}>
            <title id="footprint-title">{target.target_name}: Earth window overlap</title>
            <desc id="footprint-description">The scalar winners at 500 and 1,000 metre support, drawn as their actual 20 kilometre square footprints in {first.region}. Intersection-over-union is {(scalar.winner_footprint_iou * 100).toFixed(1)} percent.</desc>
            {scalar.winners.map((winner, index) => {
              const x = 300 + (winner.easting_m - midpointX) * scale;
              const y = 185 - (winner.northing_m - midpointY) * scale;
              return <g key={index === 0 ? "500" : "1000"}>
                <rect x={x - 10000 * scale} y={y - 10000 * scale} width={20000 * scale} height={20000 * scale} fill={colors[index]} fillOpacity={0.16} stroke={colors[index]} strokeWidth={2} strokeDasharray={index === 1 ? "7 4" : undefined} />
                <circle cx={x} cy={y} r={4} fill={colors[index]} />
              </g>;
            })}
            <text x={30} y={30} fill="currentColor" fontSize={18}>{first.region}</text>
            <line x1={30} x2={30 + 20000 * scale} y1={350} y2={350} stroke="currentColor" strokeWidth={2} />
            <text x={30} y={376} fill="currentColor" fontSize={16}>20 km</text>
            <text x={300} y={360} fill={colors[0]} fontSize={16}>500 m support</text>
            <text x={440} y={360} fill={colors[1]} fontSize={16}>1,000 m support</text>
          </svg>
          <figcaption>Scalar winners in the regional measurement projection. North is up.</figcaption>
        </figure>
        <div className="evidence-reading" aria-live="polite">
          <h2>Different ranks can share the same ground</h2>
          <p>{target.target_name}: the scalar winners move {scalar.winner_distance_km.toFixed(1)} km between scales and overlap by {(scalar.winner_footprint_iou * 100).toFixed(0)}%. Changing the scoring contract moves the winner as far as {Math.max(...target.between_method_distance_km).toLocaleString(undefined, { maximumFractionDigits: 0 })} km.</p>
          <dl className="pit-measurements">
            <div><dt>Identical top-ten windows</dt><dd>{scalar.top_ten_exact_overlap} / 10</dd></div>
            <div><dt>One-to-one pairs within 10 km</dt><dd>{nearby.matched_pairs} / 10</dd></div>
          </dl>
          <a href={asset("site_stability.json")} download>Full analysis</a>
          <a href={asset("mimesis-paper.pdf")} download>Paper, PDF</a>
        </div>
      </div>
      <details className="pit-context">
        <summary>Compare all six targets</summary>
        <img src={asset("site-stability.png")} style={{ width: "100%", display: "block" }} alt="Exact and geographic top-ten matching, with within-method and between-method winning-center displacements for all six targets." />
      </details>
      <details className="pit-context">
        <summary>Terrain shortlist for {target.target_name}</summary>
        <p>Each choice minimizes its worse rank across the two scales. These locations need geological, source-quality and access checks before field use.</p>
        {target.methods.map((method) => {
          const site = method.minimax_rank_choice;
          return (
            <div key={method.method}>
              <h3>{method.method === "scalar" ? "Four terrain variables" : "Multigroup robust score"}</h3>
              <p>{site.region}: {site.latitude.toFixed(5)}°, {site.longitude.toFixed(5)}°. Ranks {site.ranks[0]} and {site.ranks[1]} at 500 m and 1,000 m.</p>
              <a href={`https://www.openstreetmap.org/?mlat=${site.latitude}&mlon=${site.longitude}#map=11/${site.latitude}/${site.longitude}`} target="_blank" rel="noreferrer">View location</a>
            </div>
          );
        })}
        <p>The search covers two regional pools. These are terrain comparisons, with no claim of matching gravity, atmosphere, radiation, mineralogy or lunar polar illumination.</p>
      </details>
    </section>
  );
}
