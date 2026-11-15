"""Join independently acquired observations without changing a terrain ranking."""

from copy import deepcopy


def assess_packets(
    bundle: dict,
    packets: list[dict],
    imagery: list[dict],
    rubric: dict,
    observations: dict,
    novelty: dict,
):
    result = deepcopy(bundle["investigations"])
    by_packet = {(p["target_id"], p["candidate_id"]): p for p in packets}
    by_source = {source["target_id"]: source for source in imagery}
    by_novelty = {
        entry["candidate_id"]: entry for entry in novelty.get("candidates", [])
    }
    counts = {}
    for target_id, investigation in result.items():
        target = observations["target_assessments"][target_id]
        for dossier in investigation["shortlist"]:
            cid = dossier["candidate_id"]
            packet = by_packet[(target_id, cid)]
            clear = (
                packet["earth_local_clear_fraction"]
                >= rubric["minimum_clear_local_fraction"]
                and packet["earth_context_clear_fraction"]
                >= rubric["minimum_clear_context_fraction"]
            )
            camera = packet["planetary_valid_fraction"] >= 0.95
            earth = observations["earth_assessments"].get(cid)
            rows = []
            for index, requirement in enumerate(rubric["requirements"]):
                target_status = target["statuses"][index]
                earth_status = (
                    earth["statuses"][index] if clear and earth else "unassessable"
                )
                earth_reason = (
                    earth["observations"][index]
                    if clear and earth
                    else f"Clear source area is {packet['earth_local_clear_fraction']:.1%} locally and {packet['earth_context_clear_fraction']:.1%} in context; the declared complete-image gate is unmet or no interpretation is recorded."
                )
                if target_status == "contradicted":
                    status = "contradicted"
                elif (
                    not camera
                    or target_status == "unassessable"
                    or earth_status == "unassessable"
                ):
                    status = "unassessable"
                elif earth_status == "contradicted":
                    status = "contradicted"
                else:
                    status = "supported"
                rows.append(
                    {
                        "requirement": requirement["id"],
                        "status": status,
                        "target_status": target_status,
                        "earth_status": earth_status,
                        "reason": f"Target: {target['observations'][index]} Earth: {earth_reason}",
                        "earth_image": packet["earth_image"],
                        "planetary_image": packet["planetary_image"],
                    }
                )
            if all(row["status"] == "supported" for row in rows):
                outcome = "provisional_visual_support"
            elif any(row["status"] == "contradicted" for row in rows):
                outcome = "target_task_mismatch"
            elif not clear or not camera:
                outcome = "insufficient_image_coverage"
            else:
                outcome = "ambiguous_morphology"
            counts[outcome] = counts.get(outcome, 0) + 1
            dossier.update(
                {
                    "corroboration": rows,
                    "assessment_outcome": outcome,
                    "rubric_id": rubric["id"],
                    "reviewer_status": observations["reviewer_status"],
                    "blinding": observations["blinding"],
                    "claim_level": "screened_candidate",
                    "imagery_packet": packet,
                    "source_lineage": by_source[target_id].get(
                        "independence", by_source[target_id].get("reason")
                    ),
                    "contradictions": earth.get("counterevidence", []) if earth else [],
                    "contradiction_assessment": "model_assisted_remote_image_assessment",
                    "novelty": by_novelty.get(
                        cid,
                        {
                            "status": "not_audited",
                            "reason": "Outside the focused Jezero novelty investigation",
                        },
                    ),
                    "novelty_status": by_novelty.get(cid, {}).get(
                        "status", "not_audited"
                    ),
                }
            )
        investigation["claim"] = (
            "Model-assisted remote-sensing assessment; no independently validated or new analogue is established"
        )
        investigation["scope_note"] = (
            "Up to three nominations and three category/coverage-matched alternatives; non-overlapping 80 km contexts; unfilled slots remain explicit in the corrected exploratory v3 record"
        )
    return result, counts
