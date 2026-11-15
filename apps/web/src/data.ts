import { z } from "zod";

const features = z.object({
  slope_histogram: z.array(z.number()),
  slope_median_deg: z.number(),
  slope_p90_deg: z.number(),
  relief_m: z.number(),
  tpi_std_m: z.number(),
  residual_rms_m: z.number(),
  anisotropy: z.number(),
  context_relief_m: z.number(),
  context_std_m: z.number(),
  valid_fraction: z.number(),
  context_valid_fraction: z.number(),
  altitude_m: z.number(),
});
const tiers = z
  .object({ "500": features, "1000": features, eroded: features })
  .catchall(features);
const candidate = z.object({
  id: z.string(),
  name: z.string(),
  region: z.string(),
  region_id: z.string(),
  latitude: z.number(),
  longitude: z.number(),
  easting_m: z.number(),
  northing_m: z.number(),
  footprint: z.array(z.array(z.number())),
  features: tiers,
  source_ids: z.array(z.string()),
  image: z.string(),
  reserved_hls_valid_fraction: z.number(),
  hls_context_valid_fraction: z.number(),
});
const target = z.object({
  id: z.string(),
  name: z.string(),
  body: z.string(),
  latitude: z.number(),
  longitude: z.number(),
  split: z.string(),
  source: z.string(),
  features: tiers,
  image: z.string(),
  projection: z.string(),
  footprint: z.array(z.array(z.number())),
});
const row = z.object({
  id: z.string(),
  rank: z.number(),
  nominal_loss: z.number(),
  robust_loss: z.number(),
  group_losses: z.array(z.number()),
  contributions: z.array(z.number()),
  scenario_rank_range: z.array(z.number()),
  top10_inclusion_fraction: z.number(),
  passes_provisional_threshold: z.boolean(),
  claim_level: z.string(),
});
const ranking = z.object({
  state: z.string(),
  reason: z.string(),
  run_hash: z.string(),
  support_m: z.number(),
  weights: z.array(z.number()),
  scenario_count: z.number(),
  excluded_count: z.number(),
  candidates: z.array(row).min(1),
});
const dossier = z.looseObject({
  candidate_id: z.string(),
  role: z.string(),
  claim_level: z.string(),
  corroboration: z.array(
    z.object({
      requirement: z.string(),
      status: z.string(),
      reason: z.string(),
    }),
  ),
  novelty_status: z.string(),
  reviewer_status: z.string(),
  field_tests: z.array(z.string()),
  assessment_outcome: z.string(),
  source_lineage: z.string(),
  imagery_packet: z.object({
    earth_image: z.string(),
    planetary_image: z.string().nullable(),
    earth_local_clear_fraction: z.number(),
    earth_context_clear_fraction: z.number(),
    planetary_valid_fraction: z.number(),
    source_scene_ids: z.array(z.string()),
  }),
  novelty: z.looseObject({ status: z.string().optional() }),
});
export const bundleSchema = z.object({
  schema_version: z.literal("1.0"),
  generated_at: z.string(),
  protocol_hash: z.string(),
  data_hash: z.string(),
  claim: z.string(),
  protocol: z.looseObject({
    id: z.string(),
    weights: z.array(z.number()),
    provisional_maximum_loss: z.number(),
    scope_deviations: z.array(z.string()),
  }),
  earth: z.object({
    name: z.string(),
    tile: z.string(),
    bounds: z.array(z.number()),
    center: z.array(z.number()),
    extent_m: z.number(),
    image: z.string(),
    attempted_windows: z.number(),
    valid_windows: z.number(),
    stride_m: z.number(),
    projection: z.string(),
    independence: z.string(),
  }),
  regions: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      bounds: z.array(z.number()),
      center: z.array(z.number()),
      tile: z.string(),
      extent_m: z.number(),
      image: z.string(),
      image_1000: z.string(),
      imagery_image: z.string(),
      valid_windows: z.number(),
      attempted_windows: z.number(),
      stride_m: z.number(),
      projection: z.string(),
      independence: z.string(),
    }),
  ),
  experiment: z.object({
    version: z.string(),
    status: z.string(),
    parent_archive: z.string().nullable(),
  }),
  assessment_summary: z.record(z.string(), z.number()),
  evidence_assessed_at: z.string(),
  evidence_hash: z.string(),
  planetary_imagery: z.array(
    z.looseObject({ target_id: z.string(), status: z.string() }),
  ),
  novelty_audit: z.record(z.string(), z.unknown()),
  targets: z.array(target).min(1),
  candidates: z.array(candidate).min(1),
  rankings: z.record(z.string(), ranking),
  rankings_1000: z.record(z.string(), ranking),
  investigations: z.record(
    z.string(),
    z.object({
      id: z.string(),
      run_hash: z.string(),
      shortlist: z.array(dossier),
      planned_count: z.number(),
      actual_count: z.number(),
      unfilled_slots: z.array(
        z.looseObject({ role: z.string(), reason: z.string() }),
      ),
      scope_note: z.string(),
      claim: z.string(),
    }),
  ),
  benchmark: z.array(
    z.object({
      target_id: z.string(),
      split: z.string(),
      body: z.string(),
      top10_jaccard_500_vs_1000: z.number(),
      rank_spearman: z.number(),
      robust_winner: z.string(),
      nominal_winner: z.string(),
      slope_only_winner: z.string(),
      robust_minimum: z.number(),
      rank_stability_warning: z.boolean(),
    }),
  ),
  sources: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      body: z.string(),
      url: z.string().url(),
      role: z.string(),
      units: z.string(),
      encoding: z.string(),
      nominal_spacing: z.string(),
      lineage: z.string(),
      rights: z.string(),
    }),
  ),
  reserved_imagery: z.object({
    scene_id: z.string(),
    acquired_at: z.string(),
    mask_rule: z.string(),
    display: z.string(),
    image: z.string(),
    interpreted: z.boolean(),
    role: z.string(),
    valid_projected_grid_fraction: z.number(),
  }),
  source_manifest: z.array(
    z.object({
      path: z.string(),
      bytes: z.number(),
      sha256: z.string(),
      status: z.string(),
    }),
  ),
});
export type Bundle = z.infer<typeof bundleSchema>;
export type Candidate = z.infer<typeof candidate>;
export type Target = z.infer<typeof target>;
export type Ranking = z.infer<typeof ranking>;
export type Row = z.infer<typeof row>;
export type Features = z.infer<typeof features>;
