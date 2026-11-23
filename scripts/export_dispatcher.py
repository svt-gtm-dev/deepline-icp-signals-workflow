"""Despachador de exportaciones (JSON, CSV, MCP/API), reporte en texto y visor HTML."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

SUPPORTED_CONNECTORS: dict[str, dict[str, str]] = {
    "hubspot-mcp": {
        "name": "HubSpot CRM",
        "transport": "MCP / Private App API",
        "env_endpoint": "HUBSPOT_API_URL",
        "env_token": "HUBSPOT_ACCESS_TOKEN",
        "mcp_tool": "hubspot.upsert_contacts_and_companies",
    },
    "lemlist-api": {
        "name": "Lemlist Outbound",
        "transport": "REST API / MCP",
        "env_endpoint": "LEMLIST_API_URL",
        "env_token": "LEMLIST_API_KEY",
        "mcp_tool": "lemlist.add_leads_to_campaign",
    },
    "clay-webhook": {
        "name": "Clay Table",
        "transport": "Webhook / HTTP API",
        "env_endpoint": "CLAY_WEBHOOK_URL",
        "env_token": "CLAY_WEBHOOK_TOKEN",
        "mcp_tool": "clay.push_rows_to_table",
    },
    "apollo-api": {
        "name": "Apollo.io",
        "transport": "REST API / MCP",
        "env_endpoint": "APOLLO_API_URL",
        "env_token": "APOLLO_API_KEY",
        "mcp_tool": "apollo.create_contact_list",
    },
    "salesforce-mcp": {
        "name": "Salesforce CRM",
        "transport": "MCP / REST API",
        "env_endpoint": "SALESFORCE_API_URL",
        "env_token": "SALESFORCE_ACCESS_TOKEN",
        "mcp_tool": "salesforce.upsert_leads",
    },
    "deepline-mcp": {
        "name": "Deepline Saved List",
        "transport": "MCP Server",
        "env_endpoint": "DEEPLINE_LIST_URL",
        "env_token": "DEEPLINE_API_KEY",
        "mcp_tool": "deepline.save_scored_lead_list",
    },
    "custom-api": {
        "name": "Plataforma / Webhook API Personalizado",
        "transport": "HTTP POST JSON",
        "env_endpoint": "CUSTOM_CONNECTOR_URL",
        "env_token": "CUSTOM_CONNECTOR_TOKEN",
        "mcp_tool": "custom_connector.push_contacts",
    },
}


def list_export_options() -> list[dict[str, Any]]:
    """Retorna el catálogo estructurado de opciones de resultado para el usuario."""
    return [
        {
            "option": "1",
            "format": "json",
            "label": "Archivo JSON estructurado",
            "description": (
                "Incluye auditoría de calidad del ICP, query para Deepline, pesos activos "
                "y lista completa de empresas/leads priorizados."
            ),
        },
        {
            "option": "2",
            "format": "csv",
            "label": "Archivo CSV tabular",
            "description": (
                "Tabla plana compatible con Excel, Google Sheets y cargas masivas de CRM."
            ),
        },
        {
            "option": "3",
            "format": "connector",
            "label": "Lista de contactos en plataforma con conexión MCP o API",
            "description": (
                "Genera el payload o sincroniza directo con una plataforma conectada "
                f"({', '.join(SUPPORTED_CONNECTORS.keys())})."
            ),
            "supported_targets": list(SUPPORTED_CONNECTORS.keys()),
        },
    ]


def format_export_options_menu() -> str:
    """Formatea en texto claro el menú de opciones de exportación para el usuario."""
    lines = [
        "=== OPCIONES DE RESULTADO DISPONIBLES ===",
        "Elige cómo deseas exportar los resultados (siempre recibirás además la revisión en texto):",
    ]
    for opt in list_export_options():
        lines.append(f"  [{opt['option']}] {opt['format'].upper()} — {opt['label']}")
        lines.append(f"      {opt['description']}")
    lines.append("  [4] ALL — Generar JSON, CSV y Payload MCP/API simultáneamente")
    return "\n".join(lines)


def render_text_review_report(
    icp_before: dict[str, Any],
    icp_after: dict[str, Any],
    deepline_result: dict[str, Any],
    scoring_result: dict[str, Any],
    export_summary: dict[str, Any] | None = None,
) -> str:
    """Genera siempre el reporte legible en texto para revisión del usuario."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"REPORTE DE SEÑALES E ICP (DEEPLINE WORKFLOW) — {icp_after['icp_name']}")
    lines.append("=" * 72)

    score_b = icp_before["quality_score"]
    score_a = icp_after["quality_score"]
    lines.append("")
    lines.append("1. AUDITORÍA Y CALIDAD DEL ICP (MODELO 1)")
    lines.append("-" * 72)
    if score_a != score_b:
        lines.append(
            f"Score de Calidad ICP: {score_b}/100 ({icp_before['readiness_tier']}) "
            f"-> Refinado a {score_a}/100 ({icp_after['readiness_tier']})"
        )
    else:
        lines.append(f"Score de Calidad ICP: {score_a}/100 ({icp_after['readiness_tier']})")

    for dim, info in icp_after["dimension_breakdown"].items():
        lines.append(
            f"  - {dim}: {info['score']}/{info['max_score']} ({info['pct']}%) [{info['status']}]"
        )

    if icp_before.get("clarifying_questions"):
        lines.append("Preguntas de ajuste detectadas sobre el ICP inicial:")
        for idx, q in enumerate(icp_before["clarifying_questions"], 1):
            lines.append(f"  {idx}. [{q['dimension']}] {q['question']}")

    if icp_before.get("agent_targeting_proposals"):
        lines.append("Propuestas de targeting del agente:")
        for prop in icp_before["agent_targeting_proposals"]:
            lines.append(f"  * {prop['action']}: {prop['summary']}")

    weights_meta = scoring_result["active_model_weights"]
    lines.append("")
    lines.append("2. EXTRACCIÓN DEEPLINE Y PESOS DEL MODELO DE SEÑALES (MODELO 2)")
    lines.append("-" * 72)
    lines.append(f"Fuente Deepline: {deepline_result.get('execution_mode', 'dataset')}")
    lines.append(f"Query CLI equivalente: {deepline_result['query_blueprint']['cli_preview']}")
    lines.append(
        f"Balance Composite Score: {int(weights_meta['icp_fit_blend'] * 100)}% Ajuste ICP + "
        f"{int(weights_meta['signal_score_blend'] * 100)}% Señales Positivas"
    )
    lines.append("Pesos activos de señales positivas (ajustables por el usuario):")
    for cat_key, weight_val in weights_meta["positive_signal_weights"].items():
        label = weights_meta["positive_signal_labels"].get(cat_key, cat_key)
        lines.append(f"  - {label} ({cat_key}): {weight_val}%")

    tiers = scoring_result["tier_summary"]
    lines.append("")
    lines.append(
        f"3. RESULTADO DE EMPRESAS Y LEADS PRIORIZADOS ({scoring_result['total_leads']} total | "
        f"Tier A: {tiers['tier_a']} | Tier B: {tiers['tier_b']} | Tier C: {tiers['tier_c']})"
    )
    lines.append("-" * 72)

    for rank, lead in enumerate(scoring_result["scored_leads"], 1):
        sc = lead["scoring"]
        lines.append(
            f"#{rank} | {lead['full_name']} — {lead['role']} @ {lead['company']} "
            f"({lead['employee_count']} emp · {lead['industry']} · {lead['country']})"
        )
        lines.append(
            f"     Score Total: {sc['composite_score']}/100 | Ajuste ICP: {sc['icp_fit_score']} | "
            f"Señales: {sc['signal_score']} | {sc['priority_tier']}"
        )
        if sc["positive_signals_matched"]:
            sig_parts = [
                f"[{s['status']}] {s['category_label']}: {s['summary']} (+{s['points_contributed']})"
                for s in sc["positive_signals_matched"]
            ]
            lines.append("     Señales positivas:")
            for sp in sig_parts:
                lines.append(f"       * {sp}")
        else:
            lines.append("     Señales positivas: Ninguna señal positiva fuerte detectada.")
        lines.append(f"     Ángulo sugerido: {sc['conversation_angle']}")

    lines.append("")
    lines.append("4. FORMATO DE ENTREGA Y OPCIONES DISPONIBLES")
    lines.append("-" * 72)
    lines.append(format_export_options_menu())
    if export_summary and export_summary.get("generated_files"):
        lines.append("")
        lines.append("Artefactos generados en esta ejecución:")
        for label, fpath in export_summary["generated_files"].items():
            lines.append(f"  - {label}: {fpath}")

    lines.append("=" * 72)
    return "\n".join(lines)


def _write_json_export(
    out_dir: Path,
    icp_before: dict[str, Any],
    icp_after: dict[str, Any],
    deepline_result: dict[str, Any],
    scoring_result: dict[str, Any],
) -> Path:
    path = out_dir / "scored_leads.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflow": "deepline-icp-signals-workflow",
        "icp_quality_before": {
            "quality_score": icp_before["quality_score"],
            "readiness_tier": icp_before["readiness_tier"],
            "clarifying_questions": icp_before["clarifying_questions"],
            "agent_targeting_proposals": icp_before["agent_targeting_proposals"],
        },
        "icp_refined": icp_after["normalized_icp"],
        "icp_quality_after": {
            "quality_score": icp_after["quality_score"],
            "readiness_tier": icp_after["readiness_tier"],
            "dimension_breakdown": icp_after["dimension_breakdown"],
        },
        "deepline_query_blueprint": deepline_result["query_blueprint"],
        "deepline_execution_mode": deepline_result["execution_mode"],
        "scoring_summary": {
            "total_leads": scoring_result["total_leads"],
            "tier_summary": scoring_result["tier_summary"],
            "active_model_weights": scoring_result["active_model_weights"],
        },
        "export_options_available": list_export_options(),
        "leads": scoring_result["scored_leads"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_csv_export(out_dir: Path, scored_leads: list[dict[str, Any]]) -> Path:
    path = out_dir / "scored_leads.csv"
    fieldnames = [
        "rank",
        "lead_id",
        "full_name",
        "role",
        "seniority",
        "department",
        "company",
        "domain",
        "industry",
        "sub_segment",
        "employee_count",
        "country",
        "language",
        "email_status",
        "linkedin_url",
        "composite_score",
        "icp_fit_score",
        "signal_score",
        "priority_tier",
        "positive_signal_categories",
        "top_signal_summary",
        "conversation_angle",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for rank, lead in enumerate(scored_leads, 1):
            sc = lead["scoring"]
            pos = sc["positive_signals_matched"]
            categories = "; ".join(sorted({s["category"] for s in pos}))
            top_sig = pos[0]["summary"] if pos else ""
            writer.writerow(
                {
                    "rank": rank,
                    "lead_id": lead["lead_id"],
                    "full_name": lead["full_name"],
                    "role": lead["role"],
                    "seniority": lead["seniority"],
                    "department": lead["department"],
                    "company": lead["company"],
                    "domain": lead["domain"],
                    "industry": lead["industry"],
                    "sub_segment": lead["sub_segment"],
                    "employee_count": lead["employee_count"],
                    "country": lead["country"],
                    "language": lead["language"],
                    "email_status": lead["email_status"],
                    "linkedin_url": lead["linkedin_url"],
                    "composite_score": sc["composite_score"],
                    "icp_fit_score": sc["icp_fit_score"],
                    "signal_score": sc["signal_score"],
                    "priority_tier": sc["priority_tier"],
                    "positive_signal_categories": categories,
                    "top_signal_summary": top_sig,
                    "conversation_angle": sc["conversation_angle"],
                }
            )
    return path


def build_connector_payload(
    target: str,
    scored_leads: list[dict[str, Any]],
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Construye el payload estándar de contactos para una plataforma MCP o API."""
    target_key = target.strip().lower()
    if target_key not in SUPPORTED_CONNECTORS:
        raise ValueError(
            f"Conector '{target}' no soportado. Opciones: {', '.join(SUPPORTED_CONNECTORS.keys())}"
        )

    meta = SUPPORTED_CONNECTORS[target_key]
    filtered = [
        lead for lead in scored_leads if lead["scoring"]["composite_score"] >= min_score
    ]
    contacts = []
    for lead in filtered:
        sc = lead["scoring"]
        contacts.append(
            {
                "external_id": lead["lead_id"],
                "full_name": lead["full_name"],
                "job_title": lead["role"],
                "company_name": lead["company"],
                "company_domain": lead["domain"],
                "industry": lead["industry"],
                "employee_count": lead["employee_count"],
                "country": lead["country"],
                "linkedin_url": lead["linkedin_url"],
                "email_status": lead["email_status"],
                "custom_fields": {
                    "gtm_composite_score": sc["composite_score"],
                    "gtm_icp_fit_score": sc["icp_fit_score"],
                    "gtm_signal_score": sc["signal_score"],
                    "gtm_priority_tier": sc["priority_tier"],
                    "gtm_positive_signals": [s["category"] for s in sc["positive_signals_matched"]],
                    "gtm_conversation_angle": sc["conversation_angle"],
                },
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "connector_target": target_key,
        "platform_name": meta["name"],
        "transport": meta["transport"],
        "mcp_tool": meta["mcp_tool"],
        "total_contacts": len(contacts),
        "min_score_filter": min_score,
        "contacts": contacts,
    }


def _write_connector_export(
    out_dir: Path,
    target: str,
    scored_leads: list[dict[str, Any]],
    min_score: float = 0.0,
    live_push: bool = False,
) -> tuple[Path, dict[str, Any]]:
    payload = build_connector_payload(target=target, scored_leads=scored_leads, min_score=min_score)
    meta = SUPPORTED_CONNECTORS[target.strip().lower()]

    delivery_status = "dry_run_ready"
    delivery_detail = (
        f"Payload listo para entregar vía {meta['transport']} ({meta['mcp_tool']}). "
        "Usa --live-push con endpoint configurado para enviar en vivo."
    )

    if live_push:
        endpoint = os.environ.get(meta["env_endpoint"], "").strip()
        token = os.environ.get(meta["env_token"], "").strip()
        if not endpoint:
            raise RuntimeError(
                f"Se solicitó --live-push para '{target}' pero falta la variable "
                f"de entorno {meta['env_endpoint']}."
            )
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                delivery_status = f"pushed_http_{resp.status}"
                delivery_detail = f"Sincronizados {payload['total_contacts']} contactos en vivo."
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Fallo al enviar a {meta['name']}: {exc}") from exc

    payload["delivery_status"] = delivery_status
    payload["delivery_detail"] = delivery_detail

    out_path = out_dir / f"connector_payload_{target.strip().lower()}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path, payload


def _safe_json_for_script(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_workflow_html(
    icp_before: dict[str, Any],
    icp_after: dict[str, Any],
    deepline_result: dict[str, Any],
    scoring_result: dict[str, Any],
    text_report: str,
) -> str:
    """Compila un dashboard HTML single-file interactivo con simulador de pesos de señales."""
    embedded = {
        "icp_name": icp_after["icp_name"],
        "icp_before": {
            "quality_score": icp_before["quality_score"],
            "readiness_tier": icp_before["readiness_tier"],
            "clarifying_questions": icp_before["clarifying_questions"],
            "agent_targeting_proposals": icp_before["agent_targeting_proposals"],
        },
        "icp_after": {
            "quality_score": icp_after["quality_score"],
            "readiness_tier": icp_after["readiness_tier"],
            "dimension_breakdown": icp_after["dimension_breakdown"],
            "normalized_icp": icp_after["normalized_icp"],
        },
        "deepline_query": deepline_result["query_blueprint"],
        "execution_mode": deepline_result["execution_mode"],
        "weights": scoring_result["active_model_weights"],
        "leads": scoring_result["scored_leads"],
        "connectors": SUPPORTED_CONNECTORS,
        "text_report": text_report,
    }
    json_blob = _safe_json_for_script(embedded)
    title_safe = html.escape(f"Deepline Signals Workflow — {icp_after['icp_name']}")

    return f"""<!doctype html>
<html lang="es" data-theme="light">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title_safe}</title>
<style>
:root{{--bg:#F8FAFC;--sf:#FFFFFF;--sf2:#F1F5F9;--bd:#E2E8F0;--tx:#0F172A;--mu:#475569;--ac:#0369A1;--ac2:#0F766E;--ok:#15803D;--warn:#B45309;--r:8px;--f:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--m:ui-monospace,SFMono-Regular,Menlo,monospace}}
[data-theme="dark"]{{--bg:#090D16;--sf:#111827;--sf2:#1E293B;--bd:#334155;--tx:#F8FAFC;--mu:#94A3B8;--ac:#38BDF8;--ac2:#2DD4BF;--ok:#4ADE80;--warn:#FBBF24}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);font-family:var(--f);line-height:1.5}}
button,select,input{{font:inherit;color:inherit}}
button:focus-visible,select:focus-visible,input:focus-visible{{outline:2px solid var(--ac);outline-offset:2px}}
.wrap{{max-width:1520px;margin:0 auto;padding:20px 24px 48px}}
.top{{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;padding-bottom:16px;border-bottom:1px solid var(--bd)}}
.brand h1{{margin:0;font-size:1.25rem;letter-spacing:-.02em}}
.brand p{{margin:2px 0 0;font-size:.86rem;color:var(--mu)}}
.actions{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.btn{{border:1px solid var(--bd);background:var(--sf);padding:7px 12px;border-radius:6px;cursor:pointer;font-size:.84rem;font-weight:600;display:inline-flex;align-items:center;gap:6px}}
.btn.pri{{background:var(--ac);border-color:var(--ac);color:#fff}}
.grid{{display:grid;grid-template-columns:360px minmax(0,1fr);gap:20px;margin-top:20px;align-items:start}}
@media(max-width:980px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);padding:16px}}
.card h2{{margin:0 0 10px;font-size:.98rem;display:flex;align-items:center;justify-content:space-between}}
.kpi{{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}}
.kpi strong{{font-size:1.9rem;color:var(--ac);letter-spacing:-.03em}}
.badge{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.75rem;font-weight:600;background:var(--sf2);border:1px solid var(--bd)}}
.badge.ok{{color:var(--ok)}}
.badge.warn{{color:var(--warn)}}
.dim-row{{margin:8px 0;font-size:.82rem}}
.dim-head{{display:flex;justify-content:space-between;margin-bottom:3px}}
.bar{{height:6px;background:var(--sf2);border-radius:4px;overflow:hidden}}
.bar>span{{display:block;height:100%;background:var(--ac)}}
.slider-row{{margin:10px 0;font-size:.83rem}}
.slider-row label{{display:flex;justify-content:space-between;margin-bottom:2px}}
.slider-row input[type=range]{{width:100%;accent-color:var(--ac)}}
.q-list{{margin:10px 0 0;padding-left:18px;font-size:.82rem;color:var(--mu)}}
.q-list li{{margin-bottom:6px}}
.toolbar{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:12px}}
.search{{padding:7px 11px;border:1px solid var(--bd);border-radius:6px;background:var(--sf);min-width:230px;font-size:.86rem}}
.lead-card{{background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);padding:14px 16px;margin-bottom:10px}}
.lead-top{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:10px;align-items:flex-start}}
.lead-title{{font-weight:700;font-size:1rem}}
.lead-meta{{font-size:.84rem;color:var(--mu);margin-top:2px}}
.scores{{display:flex;gap:8px;flex-wrap:wrap}}
.pill{{padding:4px 9px;border-radius:6px;background:var(--sf2);border:1px solid var(--bd);font-size:.8rem;font-weight:600}}
.pill.tot{{background:var(--ac);border-color:var(--ac);color:#fff}}
.sigs{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}
.sig-tag{{font-size:.77rem;padding:3px 8px;border-radius:5px;background:var(--sf2);border:1px solid var(--bd)}}
.sig-tag.ver{{border-left:3px solid var(--ok)}}
.sig-tag.hyp{{border-left:3px solid var(--warn)}}
.angle{{margin-top:10px;padding-top:9px;border-top:1px solid var(--bd);font-size:.84rem;color:var(--mu)}}
.export-box{{margin-top:16px;background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);padding:16px}}
pre{{background:var(--sf2);border:1px solid var(--bd);border-radius:6px;padding:12px;overflow:auto;font-family:var(--m);font-size:.78rem;max-height:280px;white-space:pre-wrap}}
@media(prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="brand">
      <h1 id="wf-title">Deepline ICP &amp; Signals Workflow</h1>
      <p id="wf-sub">Modelo de Calidad ICP + Extracción Deepline + Scoring Dual &amp; Exportación Multi-Formato</p>
    </div>
    <div class="actions">
      <button class="btn" id="btn-theme" type="button">Dark / Light</button>
      <button class="btn" id="btn-copy-txt" type="button">Copiar Reporte Texto</button>
      <button class="btn" id="btn-dl-json" type="button">Exportar JSON</button>
      <button class="btn" id="btn-dl-csv" type="button">Exportar CSV</button>
      <button class="btn pri" id="btn-show-mcp" type="button">Payload MCP / API</button>
    </div>
  </header>

  <main class="grid">
    <aside style="display:flex;flex-direction:column;gap:16px">
      <section class="card">
        <h2>Modelo 1: Calidad del ICP <span class="badge ok" id="icp-tier">ready</span></h2>
        <div class="kpi"><strong id="icp-score">0</strong><span style="color:var(--mu)">/ 100 pts (antes: <span id="icp-before">0</span>)</span></div>
        <div id="icp-dims"></div>
        <details style="margin-top:10px">
          <summary style="cursor:pointer;font-size:.83rem;font-weight:600">Preguntas y propuestas de ajuste del agente</summary>
          <ul class="q-list" id="icp-questions"></ul>
        </details>
      </section>

      <section class="card">
        <h2>Modelo 2: Pesos de Señales Positivas <button class="btn" id="btn-reset-w" type="button" style="padding:3px 8px;font-size:.74rem">Restaurar</button></h2>
        <p style="margin:0 0 8px;font-size:.8rem;color:var(--mu)">Ajusta la importancia de cada señal positiva para recalcular el ranking al instante.</p>
        <div id="weight-sliders"></div>
        <div class="slider-row" style="border-top:1px solid var(--bd);padding-top:8px">
          <label><span>Balance ICP Fit vs Señales</span><strong id="blend-lbl">55% / 45%</strong></label>
          <input id="blend-slider" type="range" min="10" max="90" value="55"/>
        </div>
      </section>
    </aside>

    <section>
      <div class="toolbar">
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <input id="search-box" class="search" type="search" placeholder="Filtrar empresa, cargo, industria o señal..."/>
          <select id="tier-filter" class="search" style="min-width:160px">
            <option value="all">Todos los Tiers</option>
            <option value="Tier A">Solo Tier A</option>
            <option value="Tier B">Solo Tier B</option>
            <option value="Tier C">Solo Tier C</option>
          </select>
        </div>
        <div id="tier-stats" style="font-size:.84rem;color:var(--mu)"></div>
      </div>

      <div id="leads-list"></div>

      <section class="export-box">
        <div class="toolbar" style="margin-bottom:8px">
          <strong style="font-size:.92rem">Revisión en Texto &amp; Vista Previa Conector MCP / API</strong>
          <div style="display:flex;gap:8px;align-items:center">
            <select id="connector-select" class="search" style="min-width:190px"></select>
          </div>
        </div>
        <pre id="preview-pane"></pre>
      </section>
    </section>
  </main>
</div>

<script id="dl-workflow-data" type="application/json">{json_blob}</script>
<script>
(function(){{
  const D = JSON.parse(document.getElementById("dl-workflow-data").textContent);
  const G = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);
  const state = {{
    weights: Object.assign({{}}, D.weights.positive_signal_weights),
    icpBlend: Math.round((D.weights.icp_fit_blend || 0.55) * 100),
    previewMode: "text"
  }};

  G("wf-title").textContent = "Deepline Signals — " + D.icp_name;
  G("wf-sub").textContent = "Fuente: " + D.execution_mode + " · " + D.leads.length + " leads evaluados";
  G("icp-score").textContent = D.icp_after.quality_score;
  G("icp-before").textContent = D.icp_before.quality_score;
  G("icp-tier").textContent = D.icp_after.readiness_tier;

  G("icp-dims").innerHTML = Object.entries(D.icp_after.dimension_breakdown).map(([k,v]) =>
    `<div class="dim-row"><div class="dim-head"><span>${{esc(k)}}</span><strong>${{v.score}}/${{v.max_score}}</strong></div><div class="bar"><span style="width:${{v.pct}}%"></span></div></div>`
  ).join("");

  const qItems = [];
  (D.icp_before.clarifying_questions || []).forEach(q => qItems.push(`<li><strong>[${{esc(q.dimension)}}]</strong> ${{esc(q.question)}}</li>`));
  (D.icp_before.agent_targeting_proposals || []).forEach(p => qItems.push(`<li><strong>Propuesta:</strong> ${{esc(p.summary)}}</li>`));
  G("icp-questions").innerHTML = qItems.join("") || "<li>ICP completo sin brechas detectadas.</li>";

  const connSel = G("connector-select");
  Object.entries(D.connectors).forEach(([k,v]) => {{
    const o = document.createElement("option");
    o.value = k;
    o.textContent = v.name + " (" + v.transport + ")";
    connSel.appendChild(o);
  }});

  function renderSliders(){{
    G("weight-sliders").innerHTML = Object.entries(state.weights).map(([k,v]) => {{
      const lbl = D.weights.positive_signal_labels[k] || k;
      return `<div class="slider-row"><label><span>${{esc(lbl)}}</span><strong id="wval-${{esc(k)}}">${{Math.round(v)}}</strong></label><input type="range" min="0" max="60" value="${{Math.round(v)}}" data-wkey="${{esc(k)}}"/></div>`;
    }}).join("");
    G("blend-slider").value = state.icpBlend;
    G("blend-lbl").textContent = state.icpBlend + "% / " + (100 - state.icpBlend) + "%";
  }}

  function recomputeLeads(){{
    const sumW = Object.values(state.weights).reduce((a,b) => a + Number(b), 0) || 100;
    const icpW = state.icpBlend / 100;
    const sigW = 1 - icpW;
    return D.leads.map(lead => {{
      const bestCat = {{}};
      const matched = (lead.scoring.positive_signals_matched || []).map(s => {{
        const normW = ((state.weights[s.category] || 0) / sumW) * 100;
        const conf = s.status === "verified" ? 1.0 : 0.6;
        const rec = s.recency_days <= 30 ? 1.0 : (s.recency_days <= 90 ? 0.85 : 0.65);
        const pts = Math.round(normW * conf * rec * 10) / 10;
        if (pts > (bestCat[s.category] || 0)) bestCat[s.category] = pts;
        return Object.assign({{}}, s, {{points_contributed: pts}});
      }});
      const bonus = Math.max(0, Object.keys(bestCat).length - 1) * 5;
      const sigScore = Math.min(100, Math.round((Object.values(bestCat).reduce((a,b)=>a+b,0) + bonus) * 10) / 10);
      const icpFit = lead.scoring.icp_fit_score;
      const disq = lead.scoring.icp_fit_breakdown && lead.scoring.icp_fit_breakdown.disqualified_by_exclusion;
      const comp = disq ? Math.min(25, icpFit) : Math.min(100, Math.round((icpW * icpFit + sigW * sigScore) * 10) / 10);
      const tier = comp >= 75 ? "Tier A — Alta Prioridad" : (comp >= 50 ? "Tier B — Prioridad Media" : "Tier C — Nurture / Bajo Ajuste");
      return Object.assign({{}}, lead, {{_live: {{composite: comp, icp: icpFit, signal: sigScore, tier, matched}}}});
    }}).sort((a,b) => b._live.composite - a._live.composite);
  }}

  function render(){{
    const q = G("search-box").value.trim().toLowerCase();
    const tf = G("tier-filter").value;
    const ranked = recomputeLeads();
    const filtered = ranked.filter(l => {{
      if (tf !== "all" && !l._live.tier.startsWith(tf)) return false;
      if (!q) return true;
      const hay = [l.full_name, l.role, l.company, l.industry, l.country, ...(l._live.matched.map(m => m.summary))].join(" ").toLowerCase();
      return hay.includes(q);
    }});

    const ta = ranked.filter(l => l._live.tier.startsWith("Tier A")).length;
    const tb = ranked.filter(l => l._live.tier.startsWith("Tier B")).length;
    G("tier-stats").textContent = `Mostrando ${{filtered.length}} de ${{ranked.length}} | Tier A: ${{ta}} · Tier B: ${{tb}}`;

    G("leads-list").innerHTML = filtered.map((l, idx) => {{
      const sc = l._live;
      const sigHtml = sc.matched.length
        ? sc.matched.map(m => `<span class="sig-tag ${{m.status === 'verified' ? 'ver' : 'hyp'}}"><b>${{esc(m.category_label)}}</b>: ${{esc(m.summary)}} (+${{m.points_contributed}})</span>`).join("")
        : `<span class="sig-tag">Sin señales positivas fuertes</span>`;
      return `<article class="lead-card">
        <div class="lead-top">
          <div>
            <div class="lead-title">#${{idx+1}} ${{esc(l.full_name)}} — ${{esc(l.role)}}</div>
            <div class="lead-meta">${{esc(l.company)}} · ${{esc(l.employee_count)}} emp · ${{esc(l.industry)}} · ${{esc(l.country)}}</div>
          </div>
          <div class="scores">
            <span class="pill tot">Total ${{sc.composite}}</span>
            <span class="pill">ICP ${{sc.icp}}</span>
            <span class="pill">Señales ${{sc.signal}}</span>
            <span class="pill">${{esc(sc.tier.split(" ")[0] + " " + sc.tier.split(" ")[1])}}</span>
          </div>
        </div>
        <div class="sigs">${{sigHtml}}</div>
        <div class="angle"><b>Ángulo sugerido:</b> ${{esc(l.scoring.conversation_angle)}}</div>
      </article>`;
    }}).join("");

    if (state.previewMode === "connector") {{
      const tgt = connSel.value;
      const meta = D.connectors[tgt];
      const payload = {{
        connector_target: tgt,
        mcp_tool: meta.mcp_tool,
        total_contacts: ranked.length,
        contacts: ranked.map(l => ({{
          full_name: l.full_name, role: l.role, company: l.company, domain: l.domain,
          composite_score: l._live.composite, icp_fit_score: l._live.icp, signal_score: l._live.signal,
          priority_tier: l._live.tier
        }}))
      }};
      G("preview-pane").textContent = JSON.stringify(payload, null, 2);
    }} else {{
      G("preview-pane").textContent = D.text_report;
    }}
  }}

  function downloadFile(name, mime, text){{
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], {{type: mime}}));
    a.download = name;
    a.click();
  }}

  document.addEventListener("input", e => {{
    if (e.target.dataset.wkey) {{
      state.weights[e.target.dataset.wkey] = Number(e.target.value);
      G("wval-" + e.target.dataset.wkey).textContent = e.target.value;
      render();
    }} else if (e.target.id === "blend-slider") {{
      state.icpBlend = Number(e.target.value);
      G("blend-lbl").textContent = state.icpBlend + "% / " + (100 - state.icpBlend) + "%";
      render();
    }} else if (e.target.id === "search-box") {{
      render();
    }}
  }});

  G("tier-filter").addEventListener("change", render);
  connSel.addEventListener("change", () => {{ state.previewMode = "connector"; render(); }});
  G("btn-show-mcp").addEventListener("click", () => {{ state.previewMode = state.previewMode === "connector" ? "text" : "connector"; render(); }});
  G("btn-reset-w").addEventListener("click", () => {{
    state.weights = Object.assign({{}}, D.weights.positive_signal_weights);
    state.icpBlend = Math.round((D.weights.icp_fit_blend || 0.55) * 100);
    renderSliders();
    render();
  }});
  G("btn-theme").addEventListener("click", () => {{
    const cur = document.documentElement.getAttribute("data-theme");
    document.documentElement.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
  }});
  G("btn-copy-txt").addEventListener("click", () => {{
    navigator.clipboard && navigator.clipboard.writeText(D.text_report);
    state.previewMode = "text";
    render();
  }});
  G("btn-dl-json").addEventListener("click", () => {{
    downloadFile("deepline_scored_leads.json", "application/json", JSON.stringify(recomputeLeads(), null, 2));
  }});
  G("btn-dl-csv").addEventListener("click", () => {{
    const rows = [["rank","full_name","role","company","industry","country","composite_score","icp_fit","signal_score","tier"]];
    recomputeLeads().forEach((l,i) => rows.push([i+1,l.full_name,l.role,l.company,l.industry,l.country,l._live.composite,l._live.icp,l._live.signal,l._live.tier]));
    const csvTxt = rows.map(r => r.map(v => '"' + String(v).replace(/"/g,'""') + '"').join(",")).join("\\n");
    downloadFile("deepline_scored_leads.csv", "text/csv;charset=utf-8", csvTxt);
  }});

  renderSliders();
  render();
}})();
</script>
</body>
</html>"""


def dispatch_export(
    out_dir: Path,
    export_format: str,
    icp_before: dict[str, Any],
    icp_after: dict[str, Any],
    deepline_result: dict[str, Any],
    scoring_result: dict[str, Any],
    connector_target: str = "hubspot-mcp",
    min_score: float = 0.0,
    live_push: bool = False,
    html_out: Path | None = None,
) -> dict[str, Any]:
    """Ejecuta la exportación elegida (json/csv/connector/all) y genera siempre texto + HTML."""
    fmt = export_format.strip().lower()
    if fmt not in {"json", "csv", "connector", "all"}:
        raise ValueError(f"Formato inválido '{export_format}'. Usa: json, csv, connector o all.")

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_files: dict[str, str] = {}
    connector_meta: dict[str, Any] | None = None

    if fmt in {"json", "all"}:
        j_path = _write_json_export(
            out_dir, icp_before, icp_after, deepline_result, scoring_result
        )
        generated_files["json"] = j_path.as_posix()

    if fmt in {"csv", "all"}:
        c_path = _write_csv_export(out_dir, scoring_result["scored_leads"])
        generated_files["csv"] = c_path.as_posix()

    if fmt in {"connector", "all"}:
        p_path, connector_meta = _write_connector_export(
            out_dir=out_dir,
            target=connector_target,
            scored_leads=scoring_result["scored_leads"],
            min_score=min_score,
            live_push=live_push,
        )
        generated_files[f"connector:{connector_target}"] = p_path.as_posix()

    txt_path = out_dir / "review_report.txt"
    generated_files["text_review_report"] = txt_path.as_posix()
    if html_out is not None:
        generated_files["html_dashboard"] = html_out.as_posix()

    summary_stub = {"generated_files": generated_files}
    text_report = render_text_review_report(
        icp_before=icp_before,
        icp_after=icp_after,
        deepline_result=deepline_result,
        scoring_result=scoring_result,
        export_summary=summary_stub,
    )
    txt_path.write_text(text_report, encoding="utf-8")

    if html_out is not None:
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_doc = render_workflow_html(
            icp_before=icp_before,
            icp_after=icp_after,
            deepline_result=deepline_result,
            scoring_result=scoring_result,
            text_report=text_report,
        )
        html_out.write_text(html_doc, encoding="utf-8")

    return {
        "export_format": fmt,
        "generated_files": generated_files,
        "text_report": text_report,
        "export_options": list_export_options(),
        "connector_meta": connector_meta,
    }
