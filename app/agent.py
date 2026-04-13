from __future__ import annotations

import logging

from app import crud
from app.database import SessionLocal
from app.analysis import compute_auth_required, compute_auth_type
from app.tools import (
    analyze_endpoint_with_llm,
    analyze_service_with_llm,
    fetch_swagger_json,
    parse_swagger_document,
    save_service_data,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline runner — no LLM for steps 1-4
# ---------------------------------------------------------------------------


def run_swagger_analysis(service_id: int, swagger_url: str, force: bool = False, max_steps: int = 80) -> str:
    """Runs the Swagger analysis pipeline for a single service.

    Steps 1-5 (fetch / parse / save / verify) are pure Python — zero LLM calls.
    Only step 6 (service analysis) and step 7 (per-endpoint deep analysis)
    invoke the LLM via LangChain.
    """
    try:
        # ------------------------------------------------------------------
        # Step 1 — Fetch
        # ------------------------------------------------------------------
        swagger_data = fetch_swagger_json(swagger_url)
        if isinstance(swagger_data, str):
            logger.error("Fetch failed for service_id=%d url=%s: %s", service_id, swagger_url, swagger_data)
            return swagger_data

        # ------------------------------------------------------------------
        # Step 2 — Parse
        # ------------------------------------------------------------------
        parsed_data = parse_swagger_document(swagger_data, swagger_url=swagger_url)
        if isinstance(parsed_data, str):
            logger.error("Parse failed for service_id=%d url=%s: %s", service_id, swagger_url, parsed_data)
            return parsed_data

        # ------------------------------------------------------------------
        # Step 3 — Change detection (skipped when force=True)
        # ------------------------------------------------------------------
        if not force:
            db = SessionLocal()
            try:
                existing = crud.get_endpoints(db, service_id)
                if not crud.endpoints_have_changed(existing, parsed_data.get("endpoints", [])):
                    logger.info(
                        "No endpoint changes detected for service_id=%d, skipping save+LLM",
                        service_id,
                    )
                    return "no_changes"
            finally:
                db.close()

        # ------------------------------------------------------------------
        # Step 4 — Enrich + Save
        # Compute auth_type and per-endpoint auth_required from the spec before
        # persisting so a single save_service_data call writes everything.
        # ------------------------------------------------------------------
        parsed_data["auth_type"] = compute_auth_type(
            parsed_data.get("security_schemes", {})
        )
        for ep in parsed_data.get("endpoints", []):
            ep["auth_required"] = compute_auth_required(
                ep.get("security_json"),
                ep.get("path", ""),
                ep.get("method", ""),
                ep.get("parameters_json"),
            )

        save_result: str = save_service_data(service_id, parsed_data)

        # ------------------------------------------------------------------
        # Step 5 — Verify
        # ------------------------------------------------------------------
        db = SessionLocal()
        try:
            service = crud.get_service(db, service_id)
            endpoints = service.endpoints if service else []
            endpoint_count = len(endpoints)
            undocumented = [
                ep for ep in endpoints if not ep.summary and not ep.description
            ]
        finally:
            db.close()

        # ------------------------------------------------------------------
        # Step 6 — LLM analysis: overview, use-cases, quality score (gpt-5-mini)
        # ------------------------------------------------------------------
        analysis_result: str = analyze_service_with_llm(service_id, parsed_data)

        # ------------------------------------------------------------------
        # Step 7 — Deep per-endpoint analysis (gpt-5-mini)
        # Generate request/response examples for endpoints that lack them.
        # Capped at MAX_DEEP to control LLM costs on large APIs.
        # ------------------------------------------------------------------
        MAX_DEEP = 50
        deep_count = 0
        needs_examples = [
            ep for ep in endpoints
            if not ep.ai_request_example or not ep.ai_response_example
        ]
        for ep in needs_examples[:MAX_DEEP]:
            analyze_endpoint_with_llm(service_id, ep.path, ep.method)
            deep_count += 1

        # ------------------------------------------------------------------
        # Final summary
        # ------------------------------------------------------------------
        summary_parts = [
            f"Pipeline complete for service {service_id}.",
            save_result,
            analysis_result,
        ]
        if deep_count:
            summary_parts.append(f"Deep endpoint analysis run on {deep_count} undocumented endpoint(s).")

        output = " ".join(summary_parts)
        logger.info("Pipeline complete for service_id=%d url=%s output=%r", service_id, swagger_url, output)
        return output

    except Exception as e:
        error_msg = f"Pipeline error for service_id={service_id}: {e}"
        logger.exception("Pipeline error for service_id=%d url=%s", service_id, swagger_url)
        return error_msg
