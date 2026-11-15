import { useState } from "react";
import study from "./generated/pit-study-v10.json";

const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
const percent = (value: number) => `${(value * 100).toFixed(2)}%`;

export default function PitStudy() {
  const [siteId, setSiteId] = useState(study.cases[0].id);
  const [support, setSupport] = useState(10);
  const site = study.cases.find((item) => item.id === siteId)!;
  const result = site.supports.find((item) => item.support_m === support)!;
  return (
    <section className="pit-study" aria-label="Pit study calibration">
      <div className="pit-toolbar">
        <label>
          Lunar site
          <select
            value={siteId}
            onChange={(event) => setSiteId(event.target.value)}
          >
            {study.cases.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend>Smoothing support</legend>
          <div className="evidence-switch">
            {site.supports.map((item) => (
              <button
                key={item.support_m}
                aria-pressed={support === item.support_m}
                onClick={() => setSupport(item.support_m)}
              >
                {item.support_m} m
              </button>
            ))}
          </div>
        </fieldset>
      </div>
      <div className="evidence-layout pit-layout">
        <figure>
          <picture>
            <source
              media="(max-width: 700px)"
              srcSet={asset(result.mobile_image)}
            />
            <img
              src={asset(result.image)}
              alt={`${site.name}: successful-correlation pixels before and after the ${support} metre smoothing-support mask`}
            />
          </picture>
          <figcaption>
            Atlas funnel proxy, not a mapped rim · LROC / NASA / ASU
          </figcaption>
        </figure>
        <div className="evidence-reading">
          <h2>The lunar source check fails</h2>
          <p>Selection stopped before Earth–Moon–Mars matching.</p>
          <dl className="pit-measurements" aria-live="polite">
            <div>
              <dt>Native quality coverage</dt>
              <dd>{percent(site.raw_valid_fraction)}</dd>
            </div>
            <div>
              <dt>After {support} m support mask</dt>
              <dd>{percent(result.valid_fraction)}</dd>
            </div>
            <div>
              <dt>Required coverage</dt>
              <dd>95.00%</dd>
            </div>
          </dl>
          <p className="pit-detail">
            {site.pixel_m} m DTM posting · {site.proxy_diameter_m} m funnel
            proxy
          </p>
          <a href={site.atlas_url} target="_blank" rel="noreferrer">
            LROC source
          </a>
          <a href={asset("pit_study_v10.json")} download>
            Study record
          </a>
        </div>
      </div>
      <details className="pit-context">
        <summary>Earth sources and calibration controls</summary>
        <div className="evidence-layout">
          <figure>
            <img
              src={asset(study.earth_context.image)}
              loading="lazy"
              alt="Registered NAIP aerial imagery and shaded USGS terrain around Indian Tunnel, in NAD83 UTM zone 12 north"
            />
            <figcaption>
              USDA NAIP / USGS · Indian Tunnel search crop, 650 × 800 m
            </figcaption>
          </figure>
          <div className="evidence-reading">
            <h3>A usable Earth source, a failed lunar calibration</h3>
            <p>
              The newer USGS gap-filling DEM covers the Earth search crop. The
              earlier tile is empty there. Neither raster registers the local
              cave scans.
            </p>
            <p>
              Six analytical-plane checks recover the expected slope and flat
              residual. All {study.sensitivity_runs} lunar source-mask runs
              fail, including shifted centers, both published funnel diameters
              and edited-elevation sensitivity. Those runs describe two sites.
            </p>
            <a href={asset("pit-calibration-audit-v10.json")} download>
              Controls and sensitivities
            </a>
          </div>
        </div>
      </details>
    </section>
  );
}
