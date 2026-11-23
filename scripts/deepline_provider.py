"""Adaptador Deepline para construcción de queries, consulta y normalización segura de leads."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request

_EMAIL_PATTERN: re.Pattern[str] = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
)

_SENSITIVE_TOKEN_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:sk-[a-zA-Z0-9_-]{8,}|clay_[a-zA-Z0-9_-]{4,}|lemlist_[a-zA-Z0-9_-]{4,}|"
    r"Bearer\s+[a-zA-Z0-9._\-]{8,})\b",
    re.IGNORECASE,
)

DEFAULT_SAMPLE_PAYLOAD = (
    Path(__file__).resolve().parent.parent / "examples" / "sample_deepline_payload.json"
)


def _redact_text(text: str) -> str:
    """Elimina emails o credenciales literales para preservar higiene NDA."""
    cleaned = _EMAIL_PATTERN.sub("[email-redacted]", text)
    cleaned = _SENSITIVE_TOKEN_PATTERN.sub("[credential-redacted]", cleaned)
    return cleaned


def build_deepline_query(icp_profile: dict[str, Any]) -> dict[str, Any]:
    """Construye el blueprint de búsqueda y señales para Deepline CLI, MCP o API."""
    size = icp_profile.get("company_size", {})
    industry = icp_profile.get("industry_segment", {})
    persona = icp_profile.get("buyer_persona", {})
    geo = icp_profile.get("geography_and_market", {})

    industries = industry.get("target_industries", [])
    sub_segments = industry.get("sub_segments", [])
    exclusions = industry.get("excluded_industries", [])
    titles = persona.get("titles", [])
    seniorities = persona.get("seniority", [])
    countries = geo.get("countries", [])
    signals = icp_profile.get("suggested_signals", [])

    min_emp = size.get("min_employees") or 50
    max_emp = size.get("max_employees") or 5000

    filters = {
        "firmographics": {
            "industries": industries,
            "sub_segments": sub_segments,
            "excluded_industries": exclusions,
            "employee_count_min": min_emp,
            "employee_count_max": max_emp,
            "countries": countries,
        },
        "persona": {
            "titles": titles,
            "seniority": seniorities,
            "departments": persona.get("departments", []),
            "characteristics": persona.get("characteristics", []),
        },
        "signal_monitors": [
            "company_expansion",
            "recent_investment",
            "active_hiring",
            "new_facility_or_office",
            "new_market_entry",
        ],
        "user_suggested_signals": signals,
    }

    ind_arg = ",".join(industries[:3]) if industries else "B2B"
    titles_arg = ",".join(titles[:3]) if titles else "Operations Director"
    countries_arg = ",".join(countries[:3]) if countries else "LATAM"

    return {
        "provider": "deepline",
        "icp_name": icp_profile.get("icp_name", "ICP Personalizado"),
        "filters": filters,
        "cli_preview": (
            f'deepline enrich waterfall --industries "{ind_arg}" '
            f'--employees "{min_emp}:{max_emp}" --titles "{titles_arg}" '
            f'--countries "{countries_arg}" --signals "expansion,investment,hiring,facility,market"'
        ),
        "mcp_tool_plan": [
            "deepline.search_companies(filters.firmographics)",
            "deepline.find_contacts(company_domains, filters.persona)",
            "deepline.fetch_signals(company_domains, filters.signal_monitors)",
        ],
    }


def _normalize_signal_entry(raw_signal: Any) -> dict[str, Any]:
    if isinstance(raw_signal, str):
        return {
            "signal_type": "auto_detect",
            "summary": _redact_text(raw_signal.strip()),
            "status": "hypothesis",
            "source": "deepline:signal_feed",
            "recency_days": 30,
        }
    if not isinstance(raw_signal, dict):
        return {
            "signal_type": "auto_detect",
            "summary": "",
            "status": "hypothesis",
            "source": "deepline:signal_feed",
            "recency_days": 45,
        }
    status_val = str(raw_signal.get("status") or "verified").strip().lower()
    if status_val not in {"verified", "hypothesis"}:
        status_val = "verified"
    recency = raw_signal.get("recency_days", 30)
    try:
        recency_days = max(0, int(recency))
    except (TypeError, ValueError):
        recency_days = 30
    return {
        "signal_type": str(raw_signal.get("signal_type") or raw_signal.get("type") or "auto_detect").strip(),
        "summary": _redact_text(
            str(raw_signal.get("summary") or raw_signal.get("detail") or raw_signal.get("label") or "").strip()
        ),
        "status": status_val,
        "source": _redact_text(str(raw_signal.get("source") or "deepline:enrichment").strip()),
        "recency_days": recency_days,
    }


def normalize_deepline_record(
    raw: dict[str, Any],
    company_lookup: dict[str, dict[str, Any]] | None = None,
    index: int = 1,
) -> dict[str, Any]:
    """Normaliza un lead/empresa proveniente de Deepline eliminando PII sensible."""
    company_name = str(raw.get("company") or raw.get("company_name") or "").strip()
    domain = str(raw.get("domain") or raw.get("website") or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain).split("/")[0]

    comp_meta: dict[str, Any] = {}
    if company_lookup:
        comp_meta = company_lookup.get(domain) or company_lookup.get(company_name.lower()) or {}

    if not company_name:
        company_name = str(comp_meta.get("company") or comp_meta.get("name") or "Empresa Sin Nombre").strip()
    if not domain:
        domain = str(comp_meta.get("domain") or "").strip().lower()

    raw_signals = list(comp_meta.get("signals", [])) + list(raw.get("signals", []))
    signals = [_normalize_signal_entry(s) for s in raw_signals if s]
    signals = [s for s in signals if s["summary"]]

    emp_raw = raw.get("employee_count") or raw.get("employees") or comp_meta.get("employee_count") or 0
    try:
        employee_count = max(0, int(emp_raw))
    except (TypeError, ValueError):
        employee_count = 0

    email_status = str(raw.get("email_status") or "").strip().lower()
    if not email_status:
        email_status = "verified" if raw.get("email") or raw.get("work_email") else "unknown"
    if email_status not in {"verified", "catch_all", "unknown"}:
        email_status = "verified"

    country = str(raw.get("country") or comp_meta.get("country") or "").strip()
    lang = str(raw.get("language") or comp_meta.get("language") or "").strip().lower()
    if lang not in {"es", "pt", "en"}:
        if "brasil" in country.lower() or domain.endswith(".br"):
            lang = "pt"
        elif any(tok in country.lower() for tok in ("usa", "united states", "uk", "canada")):
            lang = "en"
        else:
            lang = "es"

    characteristics_raw = raw.get("characteristics") or raw.get("persona_attributes") or []
    if isinstance(characteristics_raw, str):
        characteristics = [c.strip() for c in characteristics_raw.split(",") if c.strip()]
    else:
        characteristics = [str(c).strip() for c in characteristics_raw if str(c).strip()]

    return {
        "lead_id": str(raw.get("lead_id") or raw.get("id") or f"dl-{index:03d}").strip(),
        "full_name": _redact_text(str(raw.get("full_name") or raw.get("name") or "").strip()),
        "role": _redact_text(str(raw.get("role") or raw.get("title") or "").strip()),
        "seniority": str(raw.get("seniority") or "").strip(),
        "department": str(raw.get("department") or "").strip(),
        "characteristics": characteristics,
        "company": _redact_text(company_name),
        "domain": domain,
        "industry": str(raw.get("industry") or comp_meta.get("industry") or "").strip(),
        "sub_segment": str(raw.get("sub_segment") or comp_meta.get("sub_segment") or "").strip(),
        "employee_count": employee_count,
        "country": country,
        "language": lang,
        "email_status": email_status,
        "email_reference": "[email-verified-via-deepline]" if email_status == "verified" else "[pending-enrichment]",
        "linkedin_url": _redact_text(str(raw.get("linkedin_url") or "").strip()),
        "source_provider": str(raw.get("source_provider") or "deepline").strip(),
        "signals": signals,
    }


def _parse_payload_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [normalize_deepline_record(item, index=idx) for idx, item in enumerate(payload, 1) if isinstance(item, dict)]

    if not isinstance(payload, dict):
        raise ValueError("El payload de Deepline debe ser un objeto JSON o una lista de leads.")

    company_lookup: dict[str, dict[str, Any]] = {}
    for comp in payload.get("companies", []):
        if not isinstance(comp, dict):
            continue
        c_name = str(comp.get("company") or comp.get("name") or "").strip().lower()
        c_dom = str(comp.get("domain") or "").strip().lower()
        c_dom = re.sub(r"^https?://", "", c_dom).split("/")[0]
        if c_dom:
            company_lookup[c_dom] = comp
        if c_name:
            company_lookup[c_name] = comp

    raw_leads = payload.get("leads") or payload.get("records") or payload.get("prospects") or []
    if not raw_leads and payload.get("companies"):
        raw_leads = payload["companies"]

    return [
        normalize_deepline_record(item, company_lookup=company_lookup, index=idx)
        for idx, item in enumerate(raw_leads, 1)
        if isinstance(item, dict)
    ]


def _load_dataset_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        return _parse_payload_records(rows)
    return _parse_payload_records(json.loads(text))


def _invoke_deepline_cli(query_blueprint: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    binary = shutil.which("deepline")
    if not binary:
        raise RuntimeError(
            "No se encontró el binario 'deepline' en el PATH. "
            "Usa --deepline-mode dataset o proporciona --deepline-input."
        )
    proc = subprocess.run(
        [binary, "query", "--json", json.dumps(query_blueprint["filters"], ensure_ascii=False)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Deepline CLI retornó error ({proc.returncode}): {proc.stderr.strip()}")
    return _parse_payload_records(json.loads(proc.stdout))


def _invoke_deepline_api(query_blueprint: dict[str, Any], timeout: float) -> list[dict[str, Any]]:
    token = os.environ.get("DEEPLINE_API_KEY", "").strip()
    if not token:
        raise RuntimeError(
            "La variable de entorno DEEPLINE_API_KEY no está configurada para modo 'api'."
        )
    endpoint = os.environ.get(
        "DEEPLINE_API_URL", "https://api.deepline.com/v1/workflows/signals"
    ).strip()
    body = json.dumps(query_blueprint["filters"], ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return _parse_payload_records(payload)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Error consultando Deepline API: {exc}") from exc


def fetch_deepline_records(
    icp_profile: dict[str, Any],
    mode: str = "auto",
    deepline_input: Path | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Obtiene empresas, leads y señales desde Deepline (Dataset, CLI o REST API)."""
    query_blueprint = build_deepline_query(icp_profile)
    chosen_mode = mode.strip().lower()

    if chosen_mode not in {"auto", "dataset", "cli", "api"}:
        raise ValueError(f"Modo de Deepline inválido: {mode}")

    if chosen_mode == "dataset" or deepline_input is not None:
        source_path = deepline_input or DEFAULT_SAMPLE_PAYLOAD
        if not source_path.exists():
            raise FileNotFoundError(f"No se encontró dataset de Deepline: {source_path}")
        leads = _load_dataset_file(source_path)
        exec_mode = f"dataset:{source_path.name}"
    elif chosen_mode == "cli":
        leads = _invoke_deepline_cli(query_blueprint, timeout=timeout)
        exec_mode = "deepline_cli"
    elif chosen_mode == "api":
        leads = _invoke_deepline_api(query_blueprint, timeout=timeout)
        exec_mode = "deepline_api"
    else:
        if os.environ.get("DEEPLINE_API_KEY", "").strip():
            leads = _invoke_deepline_api(query_blueprint, timeout=timeout)
            exec_mode = "deepline_api"
        elif shutil.which("deepline"):
            leads = _invoke_deepline_cli(query_blueprint, timeout=timeout)
            exec_mode = "deepline_cli"
        else:
            leads = _load_dataset_file(DEFAULT_SAMPLE_PAYLOAD)
            exec_mode = f"dataset_fallback:{DEFAULT_SAMPLE_PAYLOAD.name}"

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "provider": "deepline",
        "execution_mode": exec_mode,
        "query_blueprint": query_blueprint,
        "total_leads": len(leads),
        "leads": leads,
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI para generar queries y extraer leads vía Deepline."""
    parser = argparse.ArgumentParser(
        description="Extrae y normaliza empresas, leads y señales desde Deepline."
    )
    parser.add_argument("--icp", required=True, help="JSON de ICP (idealmente refinado).")
    parser.add_argument(
        "--deepline-mode",
        choices=["auto", "dataset", "cli", "api"],
        default="auto",
        help="Fuente de ejecución de Deepline.",
    )
    parser.add_argument(
        "--deepline-input",
        default="",
        help="Archivo JSON/JSONL exportado de Deepline CLI o MCP.",
    )
    parser.add_argument("--output", required=True, help="Ruta de salida para leads normalizados.")
    args = parser.parse_args(argv)

    icp_raw = json.loads(Path(args.icp).read_text(encoding="utf-8"))
    icp_profile = icp_raw.get("refined_icp") or icp_raw.get("normalized_icp") or icp_raw
    dl_path = Path(args.deepline_input) if args.deepline_input else None

    result = fetch_deepline_records(
        icp_profile=icp_profile,
        mode=args.deepline_mode,
        deepline_input=dl_path,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Deepline ({result['execution_mode']}): {result['total_leads']} leads -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
