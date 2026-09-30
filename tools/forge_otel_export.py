#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_otel_export.py — export OTLP des spans Nokido → Jaeger (Gantt distribué).

Exporte un span OpenTelemetry portant le `nokido.trace_id` (W3C 32-hex) vers un
collecteur OTLP (Jaeger). Recherche Jaeger par l'attribut nokido.trace_id →
timeline Gantt Hub ↔ workers à travers le LAN.

INERTE + FAIL-OPEN tant que :
  - opentelemetry-sdk / -exporter-otlp absents de l'env, OU
  - OTEL_EXPORTER_OTLP_ENDPOINT non défini.
→ aucune exception ne remonte, ne casse jamais le chemin appelant.

Roadmap observabilité chantier #6 (« lourd, après »). Activation :
  1. pip install opentelemetry-sdk opentelemetry-exporter-otlp  (dans py314)
  2. Jaeger all-in-one (docker run ... jaegertracing/all-in-one, OTLP :4317/4318)
  3. export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
  4. Câbler export_span() au sink forge_audit_log.persist (trace_id/parent_id/
     duration_ms déjà présents) — comme le hook Langfuse.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger("forge_otel_export")

_tracer = None
_lock = threading.Lock()
_disabled_reason: str | None = None


def _get_tracer():
    global _tracer, _disabled_reason
    if _tracer is not None:
        return _tracer
    if _disabled_reason is not None:
        return None
    # Backend OTLP HTTP. Défaut = Jaeger (Apache 2.0, LIBRE) :4318. Override via env.
    # PAS Arize Phoenix : Elastic License 2.0 (non-libre) -> bloqué forge_license_guard
    # + incompatible AGPLv3. Jaeger all-in-one : OTLP gRPC :4317 / HTTP :4318.
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "http://127.0.0.1:4318"
    with _lock:
        if _tracer is not None:
            return _tracer
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider = TracerProvider(resource=Resource.create(
                {"service.name": os.environ.get("OTEL_SERVICE_NAME", "laforge-hub")}))
            provider.add_span_processor(BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
            trace.set_tracer_provider(provider)
            _tracer = trace.get_tracer("laforge")
            logger.info("[otel] actif endpoint=%s", endpoint)
        except Exception as exc:  # noqa: BLE001 - sdk absent → inerte
            _disabled_reason = f"opentelemetry indisponible: {exc}"
            logger.info("[otel] inerte: %s", _disabled_reason)
            _tracer = None
    return _tracer


def export_span(name: str, trace_id: str, duration_ms: float = 0.0,
                agent: str = "", target: str = "", status_ok: bool = True,
                attributes: dict | None = None) -> None:
    """Émet un span OTLP corrélé par nokido.trace_id. Fail-open."""
    try:
        tracer = _get_tracer()
        if tracer is None:
            return
        from opentelemetry.trace import Status, StatusCode
        with tracer.start_as_current_span(name) as span:
            span.set_attribute("nokido.trace_id", trace_id or "")
            if agent:
                span.set_attribute("nokido.agent", agent)
            if target:
                span.set_attribute("nokido.target", target)
            span.set_attribute("nokido.duration_ms", float(duration_ms or 0))
            for k, v in (attributes or {}).items():
                try:
                    span.set_attribute(f"nokido.{k}", v)
                except Exception:
                    pass
            if not status_ok:
                span.set_status(Status(StatusCode.ERROR))
    except Exception as exc:  # noqa: BLE001 - ne jamais casser l'appelant
        logger.debug("[otel] export skip: %s", exc)


def status() -> dict:
    return {
        "active": _tracer is not None,
        "disabled_reason": _disabled_reason,
        "endpoint": os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    }
