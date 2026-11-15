import { useState } from "react";
import record from "./generated/replication-v11.json";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;

export default function ReplicationStudy() {
  const [targetId, setTargetId] = useState(record.adaptation.cases[0].target_id);
  const target = record.adaptation.cases.find((item) => item.target_id === targetId)!;
  return (
    <section className="pit-study" aria-label="Replication and terrain support">
      <div className="pit-toolbar">
        <label>
          Target
          <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
            {record.adaptation.cases.map((item) => (
              <option key={item.target_id} value={item.target_id}>{item.target_name}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="evidence-layout pit-layout">
        <figure>
          <img src={asset(record.figure)} alt="Top-ten candidate overlap between 500 metre and 1,000 metre support for six targets; rust bars mark a changed first-ranked candidate" />
          <figcaption>Rust: first-ranked site changes · MIMESIS measurements</figcaption>
        </figure>
        <div className="evidence-reading">
          <h2>Rankings change with scale</h2>
          <p>Our four-variable adaptation changes the leading window for four of six targets. These are exploratory rankings; source eligibility remains unresolved.</p>
          <dl className="pit-measurements" aria-live="polite">
            {target.supports.map((support) => {
              const site = support.top_ten[0];
              return (
                <div key={support.support_m}>
                  <dt>{support.support_m.toLocaleString()} m support</dt>
                  <dd>{site.latitude.toFixed(3)}°, {site.longitude.toFixed(3)}°</dd>
                </div>
              );
            })}
            <div><dt>Shared top-ten windows</dt><dd>{target.top_ten_overlap} / 10</dd></div>
          </dl>
          <a href={asset("scalar_baseline_transfer.json")} download>Measurements</a>
        </div>
      </div>
      <details className="pit-context">
        <summary>Replication and attribution</summary>
        <p>We reproduced seven Terrestrial Analog Finder sensitivity calculations exactly from its published feature records: twelve targets and a 469-record Earth reference pool. Raw DEM extraction and geological validation were not reproduced.</p>
        <a href={record.upstream.repository} target="_blank" rel="noreferrer">Original project · shishir-kuet</a>
        <a href={asset("terrain_finder_replay.json")} download>Replication record</a>
        <p>The adaptation above uses MIMESIS’s 3,693 existing Earth windows and four scalar observables. It does not establish a new geological analogue.</p>
      </details>
    </section>
  );
}
