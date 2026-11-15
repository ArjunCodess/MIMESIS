import { useState } from "react";
import PitStudy from "./PitStudy";
import ReplicationStudy from "./ReplicationStudy";
import SiteStability from "./SiteStability";
const asset = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;

const evidence = {
  Sampling: {
    title: "Sparse sampling lowers the measured slope",
    image: "shot-support-summary.png",
    alt: "Median slope changes for six actual MOLA sampling patterns across Namib, Mojave and Atacama",
    text: "Median slope falls in all 18 comparisons after sampling Earth terrain at actual MOLA positions and reconstructing it by linear interpolation. This measures observation sensitivity; geological relevance remains untested.",
    record: "shot_support_v9.json",
    caption:
      "Six Mars contexts × three Earth fields. Common derivative-valid coverage is 35.5 to 56.4%.",
  },
  Coverage: {
    title: "No context passes every source check",
    image: "eligibility-summary.png",
    alt: "100 frozen contexts: 18 terrain exclusions, 49 observed natural-land exclusions and 33 unknown due to missing required layers",
    text: "None of the 100 frozen contexts passes every gate in the saved v9 inventory. Missing layers leave 33 outcomes unknown, so this does not establish that suitable Earth sites are absent.",
    record: "global_eligibility_v9.json",
    caption:
      "Saved measurement snapshot. Later downloads require a new measurement run before these counts change.",
  },
  Geology: {
    title: "The geological map covers Jezero",
    image: "geology_v6_jezero.png",
    alt: "Published geological units and clipped contacts in the Jezero calibration window",
    text: "The Jezero calibration square contains seven mapped unit classes and 248.128 km of clipped contacts from USGS SIM 3464. The six prospective Mars windows lie outside this map, so it cannot validate their contact predictions.",
    record: "geology_v6.json",
    caption:
      "Published geological mapping provides calibration context, with the source map's own uncertainty.",
  },
  Spectra: {
    title: "The spectral comparison lacks geological controls",
    image: "orbital_spectra_v9.png",
    alt: "EMIT native-region reflectance and supplied channel uncertainty diagnostic",
    text: "Eleven seasonal EMIT masks are acquired; five scenes contain quality-eligible native centers. One has reflectance and uncertainty analysis. Independent registered positive and negative geological zones are still missing, so no orbital mineral-validation claim is supported.",
    record: "orbital_spectra_v9.json",
    caption:
      "Native pixel centers are not area estimates or independent geological samples.",
  },
};
export default function EvidencePanel() {
  const [view, setView] = useState<keyof typeof evidence | "Pit study" | "Replication" | "Locations">(
    "Locations",
  );
  const current = view === "Pit study" || view === "Replication" || view === "Locations" ? null : evidence[view];
  return (
    <section className="evidence-workspace" aria-label="Measured evidence">
      <div className="evidence-switch" aria-label="Evidence topic">
        {(
          ["Locations", "Pit study", "Replication", ...Object.keys(evidence)] as Array<
            keyof typeof evidence | "Pit study" | "Replication" | "Locations"
          >
        ).map((label) => (
          <button
            key={label}
            aria-pressed={view === label}
            onClick={() => setView(label)}
          >
            {label}
          </button>
        ))}
      </div>
      {current ? (
        <div className="evidence-layout">
          <figure>
            <img src={asset(current.image)} alt={current.alt} />
            <figcaption>{current.caption}</figcaption>
          </figure>
          <div className="evidence-reading">
            <h2>{current.title}</h2>
            <p>{current.text}</p>
            <a href={asset(current.record)} download>
              Record
            </a>
            <a href={asset("mimesis-paper.pdf")} download>
              Paper, PDF
            </a>
          </div>
        </div>
      ) : (
        view === "Locations" ? <SiteStability /> : view === "Replication" ? <ReplicationStudy /> : <PitStudy />
      )}
    </section>
  );
}
