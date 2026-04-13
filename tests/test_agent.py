import pytest
from unittest.mock import MagicMock, patch


def _make_mock_endpoint(path="/items", method="GET", has_docs=True, has_examples=False):
    ep = MagicMock()
    ep.path = path
    ep.method = method
    ep.summary = "Summary" if has_docs else None
    ep.description = "Desc" if has_docs else None
    ep.ai_request_example = '{"id": 1}' if has_examples else None
    ep.ai_response_example = '{"ok": true}' if has_examples else None
    return ep


def _make_mock_service(endpoints=None):
    svc = MagicMock()
    svc.endpoints = endpoints or []
    return svc


_PARSED = {"title": "Test", "version": "1.0", "base_url": "http://test.com", "endpoints": []}


# ---------------------------------------------------------------------------
# TestRunSwaggerAnalysis
# ---------------------------------------------------------------------------


class TestRunSwaggerAnalysis:
    """Tests for the direct pipeline in run_swagger_analysis."""

    def test_returns_string(self):
        svc = _make_mock_service([_make_mock_endpoint()])
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved 3 endpoints."
            ma.return_value = "Analysis complete."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_pipeline_calls_all_steps_in_order(self):
        svc = _make_mock_service([_make_mock_endpoint()])
        call_order = []

        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.side_effect = lambda url: call_order.append("fetch") or {"openapi": "3.0.0", "paths": {}}
            mp.side_effect = lambda data, **kw: call_order.append("parse") or _PARSED
            ms.side_effect = lambda sid, data: call_order.append("save") or "Saved."
            ma.side_effect = lambda sid, data: call_order.append("analyze") or "Done."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            run_swagger_analysis(1, "http://test.com/swagger.json")

        assert call_order == ["fetch", "parse", "save", "analyze"]

    def test_fetch_failure_returns_error_and_stops(self):
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud"):
            mf.return_value = "Could not fetch Swagger document from any URL variant."  # error string

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://bad.url/swagger.json")

        mp.assert_not_called()
        ms.assert_not_called()
        ma.assert_not_called()
        assert "Could not fetch" in result or "error" in result.lower()

    def test_parse_failure_returns_error_and_stops(self):
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud"):
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = "Invalid JSON: unexpected token"  # error string

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json")

        ms.assert_not_called()
        ma.assert_not_called()
        assert isinstance(result, str)

    def test_parsed_data_passed_to_save_and_analysis(self):
        svc = _make_mock_service([_make_mock_endpoint()])
        parsed = {"title": "MyAPI", "version": "2.0", "base_url": "http://api.com", "endpoints": []}
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = parsed
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            run_swagger_analysis(1, "http://test.com/swagger.json")

        # The same dict is passed to both save and analyze
        assert ms.call_args.args[1] is parsed
        assert ma.call_args.args[1] is parsed

    def test_analysis_failure_does_not_abort_pipeline(self):
        """If LLM analysis fails, save already happened so result still returns."""
        svc = _make_mock_service([_make_mock_endpoint()])
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved 2 endpoints."
            ma.return_value = "LLM analysis skipped: no API key configured"
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json")

        ms.assert_called_once()
        assert isinstance(result, str)
        assert "Saved" in result

    def test_deep_analysis_called_for_endpoints_without_examples(self):
        ep1 = _make_mock_endpoint("/a", "GET", has_docs=True, has_examples=False)
        ep2 = _make_mock_endpoint("/b", "POST", has_docs=True, has_examples=True)
        svc = _make_mock_service([ep1, ep2])

        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm") as md, \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            md.return_value = "Deep analyzed."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            run_swagger_analysis(1, "http://test.com/swagger.json")

        md.assert_called_once()
        assert md.call_args.args[1] == "/a"
        assert md.call_args.args[2] == "GET"

    def test_deep_analysis_capped_at_max(self):
        """Deep analysis is capped at MAX_DEEP (50) endpoints."""
        endpoints = [_make_mock_endpoint(f"/ep/{i}", "GET", has_examples=False) for i in range(55)]
        svc = _make_mock_service(endpoints)

        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm") as md, \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            md.return_value = "Deep analyzed."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            run_swagger_analysis(1, "http://test.com/swagger.json")

        assert md.call_count == 50

    def test_deep_analysis_skipped_when_all_have_examples(self):
        endpoints = [_make_mock_endpoint(f"/ep/{i}", "GET", has_examples=True) for i in range(5)]
        svc = _make_mock_service(endpoints)

        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm") as md, \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            run_swagger_analysis(1, "http://test.com/swagger.json")

        md.assert_not_called()

    def test_exception_returns_error_string(self):
        with patch("app.agent.fetch_swagger_json") as mf:
            mf.side_effect = RuntimeError("Network failure")

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json")

        assert isinstance(result, str)
        assert "error" in result.lower() or "Pipeline" in result

    def test_no_changes_returns_sentinel_when_endpoints_unchanged(self):
        """When no endpoint changes detected and force=False, returns 'no_changes'."""
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            mc.get_endpoints.return_value = []
            mc.endpoints_have_changed.return_value = False  # no change

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json", force=False)

        assert result == "no_changes"
        ms.assert_not_called()
        ma.assert_not_called()

    def test_force_skips_change_detection(self):
        """When force=True, change detection is bypassed and full pipeline runs."""
        svc = _make_mock_service([_make_mock_endpoint()])
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json", force=True)

        # endpoints_have_changed must not be consulted
        mc.endpoints_have_changed.assert_not_called()
        ms.assert_called_once()
        assert result != "no_changes"

    def test_changes_detected_runs_full_pipeline(self):
        """When endpoints have changed, full pipeline still runs (default force=False)."""
        svc = _make_mock_service([_make_mock_endpoint()])
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            mc.get_endpoints.return_value = []
            mc.endpoints_have_changed.return_value = True  # change detected
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            result = run_swagger_analysis(1, "http://test.com/swagger.json")

        ms.assert_called_once()
        ma.assert_called_once()
        assert result != "no_changes"

    def test_service_id_and_url_passed_correctly(self):
        svc = _make_mock_service([_make_mock_endpoint()])
        with patch("app.agent.fetch_swagger_json") as mf, \
             patch("app.agent.parse_swagger_document") as mp, \
             patch("app.agent.save_service_data") as ms, \
             patch("app.agent.analyze_service_with_llm") as ma, \
             patch("app.agent.analyze_endpoint_with_llm"), \
             patch("app.agent.SessionLocal"), \
             patch("app.agent.crud") as mc:
            mf.return_value = {"openapi": "3.0.0", "paths": {}}
            mp.return_value = _PARSED
            ms.return_value = "Saved."
            ma.return_value = "Analyzed."
            mc.get_service.return_value = svc

            from app.agent import run_swagger_analysis
            run_swagger_analysis(42, "http://unique.example.com/api")

        assert mf.call_args.args[0] == "http://unique.example.com/api"
        assert ms.call_args.args[0] == 42
        assert ma.call_args.args[0] == 42
