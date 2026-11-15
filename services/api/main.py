"""Serve the same scientific records used by the offline client."""

from functools import lru_cache
from html import escape
import json
from pathlib import Path
from typing import Annotated, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator, FiniteFloat
from src.ranking import rank
from src.suites import select_suite
from src.validation import boundary_f1
from src.research_assets import asset_exists, read_json_asset

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="MIMESIS research API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_request, error: RequestValidationError):
    # Do not echo rejected NaN/Infinity values into a JSON response.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                for item in error.errors()
            ]
        },
    )


@lru_cache
def bundle():
    path = ROOT / "apps/web/public/research/bundle.json"
    if not path.exists():
        raise HTTPException(
            503, "Research bundle is unavailable. Run python scripts/build_research.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


class RankRequest(BaseModel):
    target_id: str
    support_m: Literal[500, 1000] = 500
    objective: Literal[
        "regional_geomorphological_mapping",
        "base_suitability",
        "vacuum",
        "mineral_similarity",
        "terrain_diversity_sampling",
    ] = "regional_geomorphological_mapping"
    weights: list[float] | None = Field(default=None, min_length=4, max_length=4)
    region: str | None = None
    experiment: Literal["v3", "v4"] = "v3"
    task_version: Literal["1.0"] = "1.0"

    @field_validator("weights")
    @classmethod
    def valid_weights(cls, value):
        if value is not None:
            import math

            if any(not math.isfinite(w) or w < 0 for w in value) or sum(value) <= 0:
                raise ValueError(
                    "Weights must be finite, nonnegative, and have a positive total"
                )
        return value


@app.get("/v1/health")
def health():
    data = bundle()
    return {
        "status": "ok",
        "protocol_hash": data["protocol_hash"],
        "candidate_count": len(data["candidates"]),
    }


@app.get("/v1/catalog")
def catalog():
    data = bundle()
    return {
        key: data[key]
        for key in (
            "schema_version",
            "protocol",
            "sources",
            "earth",
            "regions",
            "experiment",
            "targets",
            "claim",
        )
    } | {
        "tasks": task_contracts()["tasks"],
        "experiments": [
            {
                "id": "v3",
                "candidate_count": len(data["candidates"]),
                "status": "preserved_baseline",
            },
            {
                "id": "v4",
                "status": "exploratory_discovery",
                "available": asset_exists(
                    ROOT / "apps/web/public/research/discovery.json"
                ),
            },
        ],
        "evidence_inventory": "/v1/layers",
    }


@app.get("/v1/targets")
def targets():
    return bundle()["targets"]


@app.post("/v1/rank")
def ranking(request: RankRequest):
    if request.experiment == "v4":
        data = discovery()
        if request.objective not in data["runs"]:
            return {
                "state": "unsupported_objective",
                "reason": "Verified evidence for this objective is unavailable",
                "candidates": [],
            }
        if request.target_id not in data["runs"][request.objective]:
            raise HTTPException(404, "Unknown target ID")
        if request.region is None and request.weights is None:
            return data["runs"][request.objective][request.target_id][
                str(request.support_m)
            ]
        target = next(t for t in data["targets"] if t["id"] == request.target_id)
        if request.region is not None and request.region not in {
            r["name"] for r in data["regions"]
        }:
            raise HTTPException(422, "Unknown allowed Earth region")
        task = next(t for t in data["tasks"]["tasks"] if t["id"] == request.objective)
        protocol = {
            **data["protocol"],
            "task": task["id"],
            "task_version": task["version"],
            "weights": task["weights"],
        }
        candidates = [
            c
            for c in data["candidates"]
            if request.region is None or c["region"] == request.region
        ]
        result = rank(candidates, target, protocol, request.support_m, request.weights)
        if result["candidates"]:
            rank_runs[result["run_hash"]] = result
            if len(rank_runs) > 64:
                rank_runs.pop(next(iter(rank_runs)))
        return result
    data = bundle()
    target = next((t for t in data["targets"] if t["id"] == request.target_id), None)
    if target is None:
        raise HTTPException(404, "Unknown target ID")
    if request.region is not None and request.region not in {
        r["name"] for r in data["regions"]
    }:
        raise HTTPException(422, "Unknown allowed Earth region")
    if request.objective not in {
        "regional_geomorphological_mapping",
        "terrain_diversity_sampling",
    }:
        return {
            "state": "unsupported_objective",
            "reason": "Terrain descriptors cannot establish this objective",
            "candidates": [],
        }
    candidates = (
        data["candidates"]
        if request.region is None
        else [c for c in data["candidates"] if c["region"] == request.region]
    )
    if (
        request.objective == "regional_geomorphological_mapping"
        and request.region is None
        and request.weights is None
    ):
        return data["rankings" if request.support_m == 500 else "rankings_1000"][
            request.target_id
        ]
    protocol = data["protocol"]
    if request.objective == "terrain_diversity_sampling":
        protocol = {
            **protocol,
            "task": request.objective,
            "task_version": request.task_version,
            "weights": [0.25, 0.30, 0.20, 0.25],
        }
    result = rank(candidates, target, protocol, request.support_m, request.weights)
    if result["candidates"]:
        rank_runs[result["run_hash"]] = result
        if len(rank_runs) > 64:
            rank_runs.pop(next(iter(rank_runs)))
    return result


@app.get("/v1/candidates/{candidate_id}")
def candidate(candidate_id: str):
    item = next((c for c in bundle()["candidates"] if c["id"] == candidate_id), None)
    if item is None:
        raise HTTPException(404, "Unknown candidate ID")
    return item


@app.get("/v1/investigations/{target_id}")
def investigation(target_id: str):
    item = bundle()["investigations"].get(target_id)
    if item is None:
        raise HTTPException(404, "Unknown investigation ID")
    return item


@app.get("/v1/benchmark")
def benchmark():
    return bundle()["benchmark"]


@app.get("/v1/evidence")
def evidence():
    data = bundle()
    return {
        key: data[key]
        for key in (
            "assessment_summary",
            "corroboration_rubric",
            "planetary_imagery",
            "novelty_audit",
            "evidence_hash",
        )
    }


@app.get("/v1/export/{target_id}")
def export(target_id: str):
    data = bundle()
    if target_id not in data["rankings"]:
        raise HTTPException(404, "Unknown target ID")
    return {
        "protocol": data["protocol"],
        "source_manifest": data["source_manifest"],
        "sources": data["sources"],
        "target": next(t for t in data["targets"] if t["id"] == target_id),
        "candidates": data["candidates"],
        "ranking": data["rankings"][target_id],
        "investigation": data["investigations"][target_id],
        "regions": data["regions"],
        "experiment": data["experiment"],
        "assessment_summary": data["assessment_summary"],
        "corroboration_rubric": data["corroboration_rubric"],
        "novelty_audit": data["novelty_audit"],
        "evidence_hash": data["evidence_hash"],
    }


@lru_cache
def task_contracts():
    return json.loads((ROOT / "configs/task_contracts.json").read_text())


@lru_cache
def discovery():
    path = ROOT / "apps/web/public/research/discovery.json"
    if not asset_exists(path):
        raise HTTPException(503, "The separate discovery build is not available yet")
    return read_json_asset(path)


rank_runs: dict[str, dict] = {}


@app.get("/v1/tasks")
def tasks():
    return task_contracts()


@app.get("/v1/discovery")
def discovery_summary():
    data = discovery()
    return {
        k: data[k]
        for k in (
            "protocol_hash",
            "record_hash",
            "regions",
            "acquisition",
            "tasks",
            "benchmark",
            "investigations",
            "claim",
        )
    }


class SuiteRequest(BaseModel):
    rank_run_hash: str = Field(min_length=64, max_length=64)
    k: Literal[2] = 2
    allowed_regions: list[str] | None = None
    minimum_context_separation_m: float = Field(
        default=80000, ge=80000, allow_inf_nan=False
    )
    scenario_budget: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    scenario_costs: (
        dict[str, Annotated[float, Field(ge=0, allow_inf_nan=False)]] | None
    ) = None
    require_verified_access: bool = False


@app.post("/v1/suites")
def suites(request: SuiteRequest):
    data = discovery()
    if request.require_verified_access:
        return {
            "state": "insufficient_logistics_evidence",
            "reason": "No verified site-specific permission/access records are available",
            "selected": None,
        }
    if request.scenario_budget is not None and request.scenario_costs is None:
        return {
            "state": "insufficient_logistics_evidence",
            "reason": "A scenario budget requires user-supplied costs; no travel prices are inferred",
            "selected": None,
        }
    if request.allowed_regions is not None and not set(request.allowed_regions) <= {
        r["id"] for r in data["regions"]
    }:
        raise HTTPException(422, "Unknown allowed region ID")
    for tid, suite in data["suites"]["terrain_diversity_sampling"].items():
        if suite["rank_run_hash"] == request.rank_run_hash:
            if request.scenario_budget is None and (
                request.allowed_regions is None
                and request.minimum_context_separation_m == 80000
            ):
                return suite
            coverage = data["requirement_coverages"][tid]
            contract = {
                **data["tasks"]["suite"],
                "minimum_context_separation_m": request.minimum_context_separation_m,
                "scenario_budget": request.scenario_budget,
                "scenario_costs": request.scenario_costs or {},
                "cost_provenance": "User-supplied scenario values, not quoted travel costs",
            }
            return select_suite(
                data["runs"]["terrain_diversity_sampling"][tid]["500"],
                data["candidates"],
                coverage,
                contract,
                request.allowed_regions,
            )
    raise HTTPException(
        404, "No measured subwindow coverage is associated with this rank run"
    )


@app.get("/v1/benchmarks/{version}")
def versioned_benchmark(version: Literal["v3", "v4"]):
    data = bundle() if version == "v3" else discovery()
    return {
        "protocol": data["protocol"],
        "benchmark": data["benchmark"],
        "independent_relevance_labels": 0,
        "uncertainty_method": "Finite sensitivity; no significance inference from reused targets",
    }


@app.get("/v1/runs/{run_hash}/report")
def run_report(run_hash: str, format: Literal["html", "json"] = "html"):
    result = rank_runs.get(run_hash)
    if result is None:
        for tier in ("rankings", "rankings_1000"):
            result = next(
                (r for r in bundle()[tier].values() if r["run_hash"] == run_hash), None
            )
            if result is not None:
                break
    if result is None and asset_exists(ROOT / "apps/web/public/research/discovery.json"):
        result = next(
            (
                r
                for task in discovery()["runs"].values()
                for target in task.values()
                for r in target.values()
                if r["run_hash"] == run_hash
            ),
            None,
        )
    if result is None:
        raise HTTPException(404, "Unknown rank-run hash")
    record = {
        "run": result,
        "run_hash": run_hash,
        "claim": "Terrain screening does not establish an analogue discovery",
        "task_contracts": task_contracts(),
        "sources": bundle()["sources"],
    }
    if format == "json":
        return record
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>MIMESIS research record</title><style>body{font:16px system-ui;max-width:80ch;margin:3rem auto;padding:1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}@media print{body{margin:0}}</style><h1>MIMESIS research record</h1><p>Exact decision record. Use the browser print command to save or print.</p><pre>"
        + escape(json.dumps(record, indent=2))
        + "</pre></html>"
    )


@app.get("/v1/layers")
def layers():
    return json.loads((ROOT / "configs/evidence_layers.json").read_text())


@lru_cache
def natural_land(version="v5"):
    path = ROOT / f"apps/web/public/research/natural_land_{version}.json"
    if not path.exists():
        raise HTTPException(503, "The masked-land experiment has not been built")
    return json.loads(path.read_text())


@app.get("/v1/validation")
def validation_summary():
    return json.loads(
        (ROOT / "apps/web/public/research/validation_v5_view.json").read_text()
    )


@app.get("/v1/research")
def research_summary():
    path = ROOT / "apps/web/public/research/research_v6.json"
    if not path.exists():
        raise HTTPException(503, "Research follow-up is not yet built")
    return json.loads(path.read_text())


@app.get("/v1/discovery/v9")
def discovery_experiments_v9():
    path = ROOT / "apps/web/public/research/discovery_v9.json"
    if not path.exists():
        raise HTTPException(503, "Discovery experiments have not published a record")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/v1/research/rank/{target_id}")
def followup_ranking(target_id: str, buffer_m: int = 1000):
    if buffer_m not in (500, 1000):
        raise HTTPException(422, "buffer_m must be 500 or 1000")
    result = natural_land("v6")["experiments"][str(buffer_m)]["results"].get(target_id)
    if result is None:
        raise HTTPException(404, "Unknown follow-up target")
    return result


@app.get("/v1/validation/rank/{target_id}")
def natural_ranking(target_id: str, buffer_m: int = 1000):
    if buffer_m not in (500, 1000):
        raise HTTPException(status_code=422, detail="buffer_m must be 500 or 1000")
    result = natural_land()["experiments"][str(buffer_m)]["results"].get(target_id)
    if result is None:
        raise HTTPException(404, "Unknown masked-experiment target")
    return result


class ContactRequest(BaseModel):
    body: Literal["Earth", "Mars", "Moon"]
    metric_crs: str = Field(min_length=5)
    predicted: list[tuple[FiniteFloat, FiniteFloat]] = Field(
        min_length=2, max_length=1000
    )
    reference: list[tuple[FiniteFloat, FiniteFloat]] = Field(
        min_length=2, max_length=1000
    )
    tolerance_m: float = Field(ge=1, allow_inf_nan=False)
    reference_accuracy_m: float = Field(gt=0, allow_inf_nan=False)
    map_scale_denominator: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    reference_source_url: str = Field(min_length=10)
    reference_authorship_and_registration: str = Field(min_length=20)

    @model_validator(mode="after")
    def compatible_metric_frame(self):
        import math
        from pyproj import CRS
        from pyproj.exceptions import CRSError

        try:
            crs = CRS.from_user_input(self.metric_crs)
        except CRSError as error:
            raise ValueError("Invalid body-specific metric CRS") from error
        if not crs.is_projected or any(
            axis.unit_name != "metre" for axis in crs.axis_info
        ):
            raise ValueError(
                "Contact lines require a common projected metric coordinate frame"
            )
        radius = {"Earth": 6378137, "Mars": 3396190, "Moon": 1737400}[self.body]
        if abs(crs.ellipsoid.semi_major_metre - radius) > 1000:
            raise ValueError(
                "Contact coordinate frame does not match the declared body"
            )
        for line in [self.predicted, self.reference]:
            lengths = [
                math.hypot(b[0] - a[0], b[1] - a[1])
                for a, b in zip(line[:-1], line[1:])
            ]
            if (
                sum(lengths) == 0
                or sum(
                    max(1, math.ceil(length / (self.tolerance_m / 4)))
                    for length in lengths
                )
                > 100000
            ):
                raise ValueError(
                    "Line must have positive length and require at most100000 tolerance-scaled samples"
                )
        return self


@app.post("/v1/validation/contact")
def contact_validation(request: ContactRequest):
    import numpy as np

    result = boundary_f1(
        np.asarray(request.predicted),
        np.asarray(request.reference),
        request.tolerance_m,
        request.reference_accuracy_m,
        request.map_scale_denominator,
    )
    return {
        **result,
        "body": request.body,
        "metric_crs": request.metric_crs,
        "reference_source_url": request.reference_source_url,
        "reference_authorship_and_registration": request.reference_authorship_and_registration,
        "verification_status": "User-supplied reference provenance; not authenticated as independent geological expert truth",
    }


web = ROOT / "apps/web/dist"
if web.exists():
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
else:

    @app.get("/")
    def index():
        return {
            "message": "MIMESIS API is running. Build the client with npm run build to serve the application here.",
            "docs": "/docs",
        }
