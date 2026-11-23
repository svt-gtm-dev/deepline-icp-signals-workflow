"""Modelo 1: Evaluador ponderado de calidad del ICP, preguntas y propuestas de targeting."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

ICP_DIMENSION_WEIGHTS: dict[str, float] = {
    "company_size": 20.0,
    "industry_segment": 25.0,
    "buyer_persona": 25.0,
    "suggested_signals": 20.0,
    "geography_and_market": 10.0,
}

_INDUSTRY_PROPOSAL_MAP: dict[str, dict[str, Any]] = {
    "manufactura": {
        "sub_segments": ["Autopartes", "Alimentos y Bebidas", "Empaques Industriales"],
        "keywords": ["planta de producción", "mantenimiento industrial", "operaciones"],
        "titles": ["Gerente de Planta", "Director de Operaciones", "Jefe de Mantenimiento"],
    },
    "logistica": {
        "sub_segments": ["Operador 3PL", "Cadena de Frío", "Distribución Última Milla"],
        "keywords": ["centro de distribución", "CEDIS", "flota logística"],
        "titles": ["Director de Logística", "VP Supply Chain", "Gerente de Operaciones"],
    },
    "saas": {
        "sub_segments": ["B2B SaaS", "Fintech B2B", "Automatización Empresarial"],
        "keywords": ["revenue operations", "growth", "enterprise sales"],
        "titles": ["VP of Sales", "Head of RevOps", "Chief Revenue Officer"],
    },
    "alimentos": {
        "sub_segments": ["Procesamiento de Alimentos", "Bebidas", "Agroindustria"],
        "keywords": ["planta procesadora", "inocuidad", "línea de envasado"],
        "titles": ["Gerente de Planta", "Director Industrial", "Gerente de Producción"],
    },
}

_DEFAULT_EXCLUSIONS: list[str] = ["Gobierno", "Freelancers", "Consultoras unipersonales"]

_POSITIVE_SIGNAL_RECOMMENDATIONS: list[dict[str, str]] = [
    {
        "category": "company_expansion",
        "text": "Expansión operativa o crecimiento acelerado de la empresa",
        "keywords": "expan,crecim,ampliac,escala,growth,scaling",
    },
    {
        "category": "recent_investment",
        "text": "Inversión reciente, ronda de capital o presupuesto CAPEX aprobado",
        "keywords": "invers,ronda,capital,serie,funding,capex,investimento",
    },
    {
        "category": "active_hiring",
        "text": "Búsqueda activa de personal clave en el área del buyer persona",
        "keywords": "contrat,vacant,personal,hiring,reclut,vagas,talent",
    },
    {
        "category": "new_facility_or_office",
        "text": "Apertura de nuevas fábricas, plantas, CEDIS u oficinas",
        "keywords": "fabrica,fábrica,planta,oficina,sede,cedis,bodega,facility,office",
    },
    {
        "category": "new_market_entry",
        "text": "Expansión o entrada a nuevos mercados o países",
        "keywords": "mercado,país,pais,internacional,market entry,novo mercado",
    },
]


def _clean_str_list(value: Any) -> list[str]:
    """Normaliza una lista de strings sin duplicados ni vacíos."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(part).strip() for part in value]
    else:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def _to_int(value: Any) -> int | None:
    """Convierte valores numéricos de empleados a entero seguro."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = int(value)
        return parsed if parsed > 0 else None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    parsed = int(digits)
    return parsed if parsed > 0 else None


def normalize_icp_input(raw_icp: dict[str, Any]) -> dict[str, Any]:
    """Normaliza un ICP aceptando formato estructurado o llaves planas."""
    raw = raw_icp if isinstance(raw_icp, dict) else {}
    size_in = raw.get("company_size") if isinstance(raw.get("company_size"), dict) else {}
    ind_in = raw.get("industry_segment") if isinstance(raw.get("industry_segment"), dict) else {}
    pers_in = raw.get("buyer_persona") if isinstance(raw.get("buyer_persona"), dict) else {}
    geo_in = (
        raw.get("geography_and_market")
        if isinstance(raw.get("geography_and_market"), dict)
        else {}
    )

    min_emp = _to_int(size_in.get("min_employees") or raw.get("min_employees"))
    max_emp = _to_int(size_in.get("max_employees") or raw.get("max_employees"))

    normalized: dict[str, Any] = {
        "icp_name": str(raw.get("icp_name") or raw.get("name") or "ICP B2B Personalizado").strip(),
        "company_size": {
            "min_employees": min_emp,
            "max_employees": max_emp,
            "revenue_range_usd": str(
                size_in.get("revenue_range_usd") or raw.get("revenue_range_usd") or ""
            ).strip(),
            "company_stage": str(
                size_in.get("company_stage") or raw.get("company_stage") or ""
            ).strip(),
        },
        "industry_segment": {
            "target_industries": _clean_str_list(
                ind_in.get("target_industries") or raw.get("industries")
            ),
            "sub_segments": _clean_str_list(
                ind_in.get("sub_segments") or raw.get("sub_segments")
            ),
            "keywords": _clean_str_list(ind_in.get("keywords") or raw.get("keywords")),
            "excluded_industries": _clean_str_list(
                ind_in.get("excluded_industries") or raw.get("excluded_industries")
            ),
        },
        "buyer_persona": {
            "titles": _clean_str_list(pers_in.get("titles") or raw.get("titles")),
            "seniority": _clean_str_list(pers_in.get("seniority") or raw.get("seniority")),
            "departments": _clean_str_list(pers_in.get("departments") or raw.get("departments")),
            "pain_points": _clean_str_list(pers_in.get("pain_points") or raw.get("pain_points")),
            "characteristics": _clean_str_list(
                pers_in.get("characteristics") or raw.get("characteristics")
            ),
            "kpis": _clean_str_list(pers_in.get("kpis") or raw.get("kpis")),
        },
        "suggested_signals": _clean_str_list(
            raw.get("suggested_signals") or raw.get("signals")
        ),
        "geography_and_market": {
            "countries": _clean_str_list(geo_in.get("countries") or raw.get("countries")),
            "languages": [
                lang.lower()
                for lang in _clean_str_list(geo_in.get("languages") or raw.get("languages"))
                if lang.lower() in {"es", "pt", "en"}
            ],
        },
    }

    if isinstance(raw.get("signal_weights"), dict):
        normalized["signal_weights"] = dict(raw["signal_weights"])
    if isinstance(raw.get("custom_positive_signals"), list):
        normalized["custom_positive_signals"] = list(raw["custom_positive_signals"])

    return normalized


def _status_from_pct(pct: float) -> str:
    if pct >= 80.0:
        return "strong"
    if pct >= 40.0:
        return "partial"
    return "missing"


def _score_company_size(
    size_cfg: dict[str, Any],
    questions: list[dict[str, str]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    max_pts = ICP_DIMENSION_WEIGHTS["company_size"]
    score = 0.0
    gaps: list[str] = []

    min_emp = size_cfg.get("min_employees")
    max_emp = size_cfg.get("max_employees")
    revenue = size_cfg.get("revenue_range_usd", "")
    stage = size_cfg.get("company_stage", "")

    if min_emp is not None:
        score += 7.0
    else:
        gaps.append("Falta definir mínimo de empleados (min_employees).")

    if max_emp is not None and (min_emp is None or max_emp >= min_emp):
        score += 6.0
    elif max_emp is not None and min_emp is not None and max_emp < min_emp:
        gaps.append("El rango max_employees es menor que min_employees.")
    else:
        gaps.append("Falta acotar techo de empleados (max_employees).")

    if revenue or stage:
        score += 7.0
    else:
        gaps.append("Falta contexto de revenue o etapa (company_stage / revenue_range_usd).")

    if gaps:
        questions.append(
            {
                "dimension": "company_size",
                "priority": "high" if score < 10.0 else "medium",
                "question": (
                    "¿Cuál es el rango exacto de empleados (mínimo y máximo) y tamaño "
                    "financiero donde tu solución cierra más rápido?"
                ),
                "why_it_matters": (
                    "Evita gastar créditos de Deepline en empresas demasiado pequeñas "
                    "sin presupuesto o corporativos fuera de alcance."
                ),
            }
        )
        proposed_min = min_emp or 100
        proposed_max = max_emp if (max_emp and max_emp >= proposed_min) else max(proposed_min * 10, 1500)
        proposals.append(
            {
                "id": "prop_company_size",
                "dimension": "company_size",
                "action": "Acotar banda firmográfica para Deepline",
                "summary": (
                    f"Fijar banda sugerida de {proposed_min}–{proposed_max} empleados "
                    f"y etapa 'Mid-Market / Enterprise'."
                ),
                "suggested_patch": {
                    "company_size": {
                        "min_employees": proposed_min,
                        "max_employees": proposed_max,
                        "company_stage": stage or "Mid-Market & Enterprise",
                        "revenue_range_usd": revenue or "$15M - $250M",
                    }
                },
            }
        )

    pct = round((score / max_pts) * 100.0, 1)
    return {
        "score": round(score, 1),
        "max_score": max_pts,
        "pct": pct,
        "status": _status_from_pct(pct),
        "gaps": gaps,
    }


def _match_industry_template(industries: list[str]) -> dict[str, Any]:
    joined = " ".join(industries).lower()
    for key, template in _INDUSTRY_PROPOSAL_MAP.items():
        if key in joined:
            return template
    return {
        "sub_segments": ["Operaciones B2B", "Multi-sede / Regional"],
        "keywords": ["operaciones", "crecimiento", "eficiencia"],
        "titles": ["Director de Operaciones", "COO", "Head of Operations"],
    }


def _score_industry_segment(
    ind_cfg: dict[str, Any],
    questions: list[dict[str, str]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    max_pts = ICP_DIMENSION_WEIGHTS["industry_segment"]
    score = 0.0
    gaps: list[str] = []

    industries = ind_cfg.get("target_industries", [])
    sub_segments = ind_cfg.get("sub_segments", [])
    keywords = ind_cfg.get("keywords", [])
    exclusions = ind_cfg.get("excluded_industries", [])

    if len(industries) >= 2:
        score += 10.0
    elif len(industries) == 1:
        score += 8.0 if len(industries[0]) > 4 else 5.0
    else:
        gaps.append("No se especificaron industrias o segmentos objetivo.")

    if sub_segments and keywords:
        score += 9.0
    elif sub_segments or keywords:
        score += 5.0
        gaps.append("Faltan sub-segmentos o palabras clave para afinar búsquedas en Deepline.")
    else:
        gaps.append("Faltan sub-segmentos y keywords de nicho.")

    if exclusions:
        score += 6.0
    else:
        gaps.append("No hay industrias excluidas para filtrar falsos positivos.")

    if gaps:
        template = _match_industry_template(industries)
        questions.append(
            {
                "dimension": "industry_segment",
                "priority": "high" if not industries else "medium",
                "question": (
                    "¿Qué sub-verticales específicas funcionan mejor dentro de tu segmento "
                    "y qué industrias deberíamos excluir explícitamente?"
                ),
                "why_it_matters": (
                    "Deepline filtra mucho mejor cuando se combinan verticales concretas, "
                    "keywords operativas y exclusiones negativas."
                ),
            }
        )
        proposals.append(
            {
                "id": "prop_industry_segment",
                "dimension": "industry_segment",
                "action": "Enriquecer nicho y exclusiones de segmento",
                "summary": (
                    f"Añadir sub-segmentos sugeridos ({', '.join(template['sub_segments'][:2])}) "
                    f"y exclusiones base ({', '.join(_DEFAULT_EXCLUSIONS[:2])})."
                ),
                "suggested_patch": {
                    "industry_segment": {
                        "target_industries": industries or ["Manufactura", "Logística B2B"],
                        "sub_segments": sub_segments or template["sub_segments"],
                        "keywords": keywords or template["keywords"],
                        "excluded_industries": exclusions or _DEFAULT_EXCLUSIONS,
                    }
                },
            }
        )

    pct = round((score / max_pts) * 100.0, 1)
    return {
        "score": round(score, 1),
        "max_score": max_pts,
        "pct": pct,
        "status": _status_from_pct(pct),
        "gaps": gaps,
    }


def _score_buyer_persona(
    pers_cfg: dict[str, Any],
    industries: list[str],
    questions: list[dict[str, str]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    max_pts = ICP_DIMENSION_WEIGHTS["buyer_persona"]
    score = 0.0
    gaps: list[str] = []

    titles = pers_cfg.get("titles", [])
    seniority = pers_cfg.get("seniority", [])
    departments = pers_cfg.get("departments", [])
    pain_points = pers_cfg.get("pain_points", [])
    characteristics = pers_cfg.get("characteristics", [])
    kpis = pers_cfg.get("kpis", [])

    if len(titles) >= 2:
        score += 8.0
    elif len(titles) == 1:
        score += 5.0
        gaps.append("Solo hay 1 cargo definido; conviene incluir títulos equivalentes.")
    else:
        gaps.append("Faltan cargos (titles) del buyer persona.")

    if seniority and departments:
        score += 6.0
    elif seniority or departments:
        score += 3.0
        gaps.append("Falta precisar seniority o departamento del buyer persona.")
    else:
        gaps.append("Falta nivel de seniority y área/departamento.")

    if len(pain_points) >= 2:
        score += 6.0
    elif len(pain_points) == 1:
        score += 4.0
    else:
        gaps.append("No se especificaron dolores operativos del buyer persona.")

    if characteristics and kpis:
        score += 5.0
    elif characteristics or kpis:
        score += 3.0
    else:
        gaps.append("Faltan características o KPIs propios del buyer persona.")

    if gaps:
        template = _match_industry_template(industries)
        questions.append(
            {
                "dimension": "buyer_persona",
                "priority": "high" if score < 13.0 else "medium",
                "question": (
                    "¿Qué dolores concretos y características de responsabilidad tiene tu buyer "
                    "persona (p. ej. KPIs que le miden, poder de presupuesto o gestión multi-sede)?"
                ),
                "why_it_matters": (
                    "Permite al segundo modelo distinguir entre un contacto genérico y un "
                    "decisor real con autoridad."
                ),
            }
        )
        merged_titles = _clean_str_list(titles + template["titles"])
        proposals.append(
            {
                "id": "prop_buyer_persona",
                "dimension": "buyer_persona",
                "action": "Expandir cargos equivalentes y atributos de buyer persona",
                "summary": (
                    f"Proponer títulos equivalentes ({', '.join(merged_titles[:3])}), "
                    "seniority Director/VP/Gerente y características de presupuesto."
                ),
                "suggested_patch": {
                    "buyer_persona": {
                        "titles": merged_titles,
                        "seniority": seniority or ["Director", "VP", "Gerente", "C-Level"],
                        "departments": departments or ["Operaciones", "Dirección General"],
                        "pain_points": pain_points
                        or [
                            "Cuellos de botella operativos al escalar nuevas sedes o líneas",
                            "Falta de visibilidad en tiempo real para ejecutar rápido",
                        ],
                        "characteristics": characteristics
                        or [
                            "Responsable de eficiencia operativa y expansión multi-sede",
                            "Influye o aprueba presupuesto de mejora e infraestructura",
                        ],
                        "kpis": kpis or ["Eficiencia operativa", "Tiempo de respuesta / SLA"],
                    }
                },
            }
        )

    pct = round((score / max_pts) * 100.0, 1)
    return {
        "score": round(score, 1),
        "max_score": max_pts,
        "pct": pct,
        "status": _status_from_pct(pct),
        "gaps": gaps,
    }


def _score_suggested_signals(
    signals: list[str],
    questions: list[dict[str, str]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    max_pts = ICP_DIMENSION_WEIGHTS["suggested_signals"]
    score = 0.0
    gaps: list[str] = []

    if len(signals) >= 3:
        score += 10.0
    elif len(signals) == 2:
        score += 8.0
    elif len(signals) == 1:
        score += 5.0
        gaps.append("Solo incluiste 1 señal sugerida; conviene diversificar disparadores.")
    else:
        gaps.append("No se indicaron señales sugeridas para iniciar conversación.")

    matched_categories: set[str] = set()
    for sig in signals:
        low = sig.lower()
        for rec in _POSITIVE_SIGNAL_RECOMMENDATIONS:
            kws = rec["keywords"].split(",")
            if any(kw in low for kw in kws):
                matched_categories.add(rec["category"])

    if len(matched_categories) >= 3:
        score += 10.0
    elif len(matched_categories) == 2:
        score += 8.0
    elif len(matched_categories) == 1:
        score += 5.0
        gaps.append("Las señales cubren solo 1 categoría positiva accionable en Deepline.")
    else:
        gaps.append(
            "Las señales actuales no están mapeadas a eventos detectables "
            "(expansiones, inversiones, contratación, nuevas plantas/oficinas o nuevos mercados)."
        )

    missing_recs = [
        rec for rec in _POSITIVE_SIGNAL_RECOMMENDATIONS if rec["category"] not in matched_categories
    ]
    if gaps or len(matched_categories) < 3:
        suggested_additions = [rec["text"] for rec in missing_recs[:3]]
        questions.append(
            {
                "dimension": "suggested_signals",
                "priority": "high" if not signals else "medium",
                "question": (
                    "¿Qué señales pesan más hoy para priorizar un contacto: aperturas de "
                    "plantas/oficinas, rondas de inversión, contrataciones o entrada a nuevos mercados?"
                ),
                "why_it_matters": (
                    "Calibra los pesos iniciales del segundo modelo de scoring y evita "
                    "alertas ruidosas sin intención comercial."
                ),
            }
        )
        proposals.append(
            {
                "id": "prop_suggested_signals",
                "dimension": "suggested_signals",
                "action": "Activar catálogo de señales positivas detectables en Deepline",
                "summary": (
                    "Incorporar señales de alta intención faltantes: "
                    + "; ".join(suggested_additions)
                ),
                "suggested_patch": {
                    "suggested_signals": _clean_str_list(signals + suggested_additions)
                },
            }
        )

    pct = round((score / max_pts) * 100.0, 1)
    return {
        "score": round(score, 1),
        "max_score": max_pts,
        "pct": pct,
        "status": _status_from_pct(pct),
        "gaps": gaps,
        "matched_signal_categories": sorted(matched_categories),
    }


def _infer_languages_from_countries(countries: list[str]) -> list[str]:
    langs: list[str] = []
    for country in countries:
        low = country.lower()
        if any(tok in low for tok in ("brasil", "brazil", "portugal")):
            if "pt" not in langs:
                langs.append("pt")
        elif any(tok in low for tok in ("usa", "united states", "estados unidos", "uk", "canada")):
            if "en" not in langs:
                langs.append("en")
        else:
            if "es" not in langs:
                langs.append("es")
    return langs or ["es"]


def _score_geography(
    geo_cfg: dict[str, Any],
    questions: list[dict[str, str]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    max_pts = ICP_DIMENSION_WEIGHTS["geography_and_market"]
    score = 0.0
    gaps: list[str] = []

    countries = geo_cfg.get("countries", [])
    languages = geo_cfg.get("languages", [])

    if countries:
        score += 6.0
    else:
        gaps.append("Falta delimitar países o regiones objetivo.")

    if languages:
        score += 4.0
    else:
        gaps.append("Falta idioma de prospección (es / pt / en).")

    if gaps:
        target_countries = countries or ["México", "Colombia", "Chile", "Brasil"]
        inferred_langs = languages or _infer_languages_from_countries(target_countries)
        questions.append(
            {
                "dimension": "geography_and_market",
                "priority": "medium",
                "question": "¿En qué países prioritarios y en qué idiomas quieres prospectar?",
                "why_it_matters": (
                    "Ajusta el filtro geográfico en Deepline y las palabras clave de señales locales."
                ),
            }
        )
        proposals.append(
            {
                "id": "prop_geography",
                "dimension": "geography_and_market",
                "action": "Definir cobertura geográfica e idiomas",
                "summary": (
                    f"Configurar países ({', '.join(target_countries)}) "
                    f"e idiomas ({', '.join(inferred_langs)})."
                ),
                "suggested_patch": {
                    "geography_and_market": {
                        "countries": target_countries,
                        "languages": inferred_langs,
                    }
                },
            }
        )

    pct = round((score / max_pts) * 100.0, 1)
    return {
        "score": round(score, 1),
        "max_score": max_pts,
        "pct": pct,
        "status": _status_from_pct(pct),
        "gaps": gaps,
    }


def evaluate_icp_quality(raw_icp: dict[str, Any]) -> dict[str, Any]:
    """Evalúa la calidad de un ICP (0-100) y genera preguntas y propuestas del agente."""
    normalized = normalize_icp_input(raw_icp)
    questions: list[dict[str, str]] = []
    proposals: list[dict[str, Any]] = []

    breakdown = {
        "company_size": _score_company_size(normalized["company_size"], questions, proposals),
        "industry_segment": _score_industry_segment(
            normalized["industry_segment"], questions, proposals
        ),
        "buyer_persona": _score_buyer_persona(
            normalized["buyer_persona"],
            normalized["industry_segment"]["target_industries"],
            questions,
            proposals,
        ),
        "suggested_signals": _score_suggested_signals(
            normalized["suggested_signals"], questions, proposals
        ),
        "geography_and_market": _score_geography(
            normalized["geography_and_market"], questions, proposals
        ),
    }

    total_score = round(sum(item["score"] for item in breakdown.values()), 1)
    if total_score >= 80.0:
        tier = "ready"
    elif total_score >= 50.0:
        tier = "needs_tuning"
    else:
        tier = "incomplete"

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "icp_name": normalized["icp_name"],
        "quality_score": total_score,
        "max_score": 100.0,
        "readiness_tier": tier,
        "dimension_weights": dict(ICP_DIMENSION_WEIGHTS),
        "dimension_breakdown": breakdown,
        "clarifying_questions": questions,
        "agent_targeting_proposals": proposals,
        "normalized_icp": normalized,
    }


def _deep_merge_icp(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            for sub_k, sub_v in val.items():
                if isinstance(sub_v, list):
                    result[key][sub_k] = _clean_str_list(result[key].get(sub_k, []) + sub_v)
                elif sub_v not in (None, ""):
                    if not result[key].get(sub_k):
                        result[key][sub_k] = sub_v
        elif isinstance(val, list):
            result[key] = _clean_str_list(result.get(key, []) + val)
        elif val not in (None, ""):
            result[key] = val
    return result


def refine_icp_profile(
    raw_icp: dict[str, Any],
    user_overrides: dict[str, Any] | None = None,
    apply_proposals: bool = True,
) -> dict[str, Any]:
    """Refina un ICP aplicando respuestas del usuario y/o propuestas del agente."""
    before_audit = evaluate_icp_quality(raw_icp)
    working = deepcopy(before_audit["normalized_icp"])

    if user_overrides:
        working = _deep_merge_icp(working, normalize_icp_input(user_overrides))

    applied_ids: list[str] = []
    if apply_proposals:
        current_audit = evaluate_icp_quality(working) if user_overrides else before_audit
        for proposal in current_audit["agent_targeting_proposals"]:
            patch = proposal.get("suggested_patch", {})
            working = _deep_merge_icp(working, patch)
            applied_ids.append(proposal["id"])

    after_audit = evaluate_icp_quality(working)
    return {
        "before_audit": before_audit,
        "after_audit": after_audit,
        "applied_proposals": applied_ids,
        "refined_icp": after_audit["normalized_icp"],
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI para auditar y refinar la calidad del ICP."""
    parser = argparse.ArgumentParser(
        description="Modelo 1: Evalúa calidad del ICP (0-100) y propone ajustes de targeting."
    )
    parser.add_argument("--icp", required=True, help="Archivo JSON con la definición inicial del ICP.")
    parser.add_argument(
        "--apply-proposals",
        action="store_true",
        help="Aplica automáticamente las propuestas de targeting del agente sobre el ICP.",
    )
    parser.add_argument("--output", default="", help="Ruta opcional para guardar auditoría/ICP JSON.")
    args = parser.parse_args(argv)

    icp_path = Path(args.icp)
    if not icp_path.exists():
        print(f"[ERROR] No existe archivo ICP: {icp_path}", file=sys.stderr)
        return 1

    raw_icp = json.loads(icp_path.read_text(encoding="utf-8"))
    if args.apply_proposals:
        result = refine_icp_profile(raw_icp, apply_proposals=True)
        score_after = result["after_audit"]["quality_score"]
        score_before = result["before_audit"]["quality_score"]
        payload: dict[str, Any] = result
        print(
            f"[OK] ICP auditado y refinado: {score_before} -> {score_after}/100 "
            f"(tier: {result['after_audit']['readiness_tier']})"
        )
    else:
        audit = evaluate_icp_quality(raw_icp)
        payload = audit
        print(
            f"[OK] Calidad del ICP '{audit['icp_name']}': {audit['quality_score']}/100 "
            f"(tier: {audit['readiness_tier']}, preguntas: {len(audit['clarifying_questions'])})"
        )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
