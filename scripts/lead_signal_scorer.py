"""Modelo 2: Scoring dual de ajuste ICP + señales de intención positivas configurables."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

DEFAULT_POSITIVE_SIGNAL_WEIGHTS: dict[str, float] = {
    "company_expansion": 25.0,
    "recent_investment": 20.0,
    "active_hiring": 20.0,
    "new_facility_or_office": 20.0,
    "new_market_entry": 15.0,
}

SIGNAL_CATEGORY_LABELS: dict[str, str] = {
    "company_expansion": "Expansión de la empresa",
    "recent_investment": "Inversiones recientes",
    "active_hiring": "Búsqueda activa de personal",
    "new_facility_or_office": "Apertura de fábricas, plantas u oficinas",
    "new_market_entry": "Expansión / entrada a nuevos mercados",
}

# El orden importa: categorías específicas preceden a 'company_expansion'.
_SIGNAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "new_facility_or_office",
        (
            "nueva fábrica",
            "nueva fabrica",
            "nuevas fábricas",
            "nuevas fabricas",
            "nueva planta",
            "nuevas plantas",
            "nueva oficina",
            "nuevas oficinas",
            "nueva sede",
            "nuevo centro de distribución",
            "nuevo cedis",
            "apertura de planta",
            "apertura de fábrica",
            "apertura de oficina",
            "inauguración de planta",
            "nova fábrica",
            "nova planta",
            "novo escritório",
            "new factory",
            "new plant",
            "new facility",
            "new office",
            "new warehouse",
            "distribution center",
        ),
    ),
    (
        "new_market_entry",
        (
            "nuevo mercado",
            "nuevos mercados",
            "entrada a",
            "entrada en",
            "expansión internacional",
            "expansión a ",
            "desembarco en",
            "apertura comercial en",
            "novo mercado",
            "novos mercados",
            "entrada no mercado",
            "new market",
            "new markets",
            "market entry",
            "international expansion",
            "entering ",
        ),
    ),
    (
        "recent_investment",
        (
            "inversión",
            "inversiones",
            "ronda",
            "serie a",
            "serie b",
            "serie c",
            "levantamiento",
            "capital",
            "capex",
            "financiamiento",
            "investimento",
            "rodada",
            "investment",
            "funding",
            "raised",
            "series a",
            "series b",
        ),
    ),
    (
        "active_hiring",
        (
            "búsqueda activa de personal",
            "busqueda activa de personal",
            "contratando",
            "contratación",
            "vacantes",
            "reclutando",
            "búsqueda de talento",
            "vagas abertas",
            "contratando",
            "hiring",
            "actively hiring",
            "open roles",
            "headcount growth",
            "recruiting",
        ),
    ),
    (
        "company_expansion",
        (
            "expansión",
            "expansion",
            "expansão",
            "crecimiento",
            "ampliación",
            "escalando operaciones",
            "duplicando capacidad",
            "scaling operations",
            "expanding operations",
        ),
    ),
)


def _norm_weights(
    weights_config: dict[str, Any] | None,
    icp_profile: dict[str, Any],
) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[str, ...]], float, float]:
    cfg = weights_config or {}
    icp_sig_weights = icp_profile.get("signal_weights", {})

    raw_weights: dict[str, float] = dict(DEFAULT_POSITIVE_SIGNAL_WEIGHTS)
    for source in (icp_sig_weights, cfg.get("signal_weights", {})):
        if isinstance(source, dict):
            for key, val in source.items():
                try:
                    raw_weights[str(key).strip()] = max(0.0, float(val))
                except (TypeError, ValueError):
                    continue

    labels = dict(SIGNAL_CATEGORY_LABELS)
    custom_kw_rules: dict[str, tuple[str, ...]] = {}

    custom_list = list(icp_profile.get("custom_positive_signals", [])) + list(
        cfg.get("custom_positive_signals", [])
    )
    for item in custom_list:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        labels[key] = str(item.get("label") or key).strip()
        try:
            raw_weights[key] = max(0.0, float(item.get("weight", 15.0)))
        except (TypeError, ValueError):
            raw_weights[key] = 15.0
        kws = tuple(str(k).strip().lower() for k in item.get("keywords", []) if str(k).strip())
        if kws:
            custom_kw_rules[key] = kws

    total_w = sum(raw_weights.values()) or 100.0
    normalized_signal_weights = {k: round((v / total_w) * 100.0, 2) for k, v in raw_weights.items()}

    try:
        icp_w = max(0.0, float(cfg.get("icp_weight", 0.55)))
    except (TypeError, ValueError):
        icp_w = 0.55
    try:
        sig_w = max(0.0, float(cfg.get("signal_weight", 0.45)))
    except (TypeError, ValueError):
        sig_w = 0.45
    blend_total = (icp_w + sig_w) or 1.0

    return (
        normalized_signal_weights,
        labels,
        custom_kw_rules,
        icp_w / blend_total,
        sig_w / blend_total,
    )


def classify_signal_category(
    summary: str,
    explicit_type: str = "",
    custom_rules: dict[str, tuple[str, ...]] | None = None,
    valid_categories: set[str] | None = None,
) -> str:
    """Clasifica una señal textual o estructurada hacia las categorías positivas."""
    explicit = explicit_type.strip().lower()
    allowed = valid_categories or set(DEFAULT_POSITIVE_SIGNAL_WEIGHTS.keys())
    if explicit and explicit != "auto_detect" and explicit in allowed:
        return explicit

    low = summary.lower()
    if custom_rules:
        for cat_key, kws in custom_rules.items():
            if any(kw in low for kw in kws):
                return cat_key

    for cat_key, kws in _SIGNAL_KEYWORDS:
        if any(kw in low for kw in kws):
            return cat_key

    return "neutral"


def _token_overlap(candidate: str, targets: list[str]) -> float:
    if not candidate or not targets:
        return 0.0
    cand_low = candidate.lower().strip()
    cand_tokens = {tok for tok in cand_low.replace("/", " ").replace("-", " ").split() if len(tok) > 2}

    best = 0.0
    for target in targets:
        t_low = target.lower().strip()
        if t_low == cand_low or t_low in cand_low or cand_low in t_low:
            return 1.0
        t_tokens = {tok for tok in t_low.replace("/", " ").replace("-", " ").split() if len(tok) > 2}
        if cand_tokens and t_tokens:
            overlap = len(cand_tokens & t_tokens) / max(1, min(len(cand_tokens), len(t_tokens)))
            best = max(best, overlap)
    return round(min(1.0, best), 2)


def _score_icp_fit(lead: dict[str, Any], icp_profile: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    ind_cfg = icp_profile.get("industry_segment", {})
    size_cfg = icp_profile.get("company_size", {})
    pers_cfg = icp_profile.get("buyer_persona", {})
    geo_cfg = icp_profile.get("geography_and_market", {})

    lead_ind = lead.get("industry", "")
    lead_sub = lead.get("sub_segment", "")
    exclusions = ind_cfg.get("excluded_industries", [])
    if lead_ind and exclusions:
        if _token_overlap(lead_ind, exclusions) >= 0.8:
            return 12.0, {
                "industry_pts": 0.0,
                "size_pts": 0.0,
                "persona_pts": 0.0,
                "geography_pts": 0.0,
                "disqualified_by_exclusion": True,
                "reason": f"Industria '{lead_ind}' figura en exclusiones del ICP.",
            }

    # 1. Industria y sub-segmento (35 pts)
    targets = ind_cfg.get("target_industries", []) + ind_cfg.get("sub_segments", [])
    ind_ratio = max(
        _token_overlap(lead_ind, targets),
        _token_overlap(lead_sub, targets),
    )
    ind_pts = round(ind_ratio * 35.0, 1)

    # 2. Tamaño de empresa (25 pts)
    emp = lead.get("employee_count", 0)
    min_emp = size_cfg.get("min_employees") or 1
    max_emp = size_cfg.get("max_employees") or 100000
    if emp <= 0:
        size_pts = 10.0
    elif min_emp <= emp <= max_emp:
        size_pts = 25.0
    elif (min_emp * 0.6) <= emp <= (max_emp * 1.5):
        size_pts = 15.0
    else:
        size_pts = 4.0

    # 3. Buyer persona: cargo (15) + seniority/depto (8) + características (7) = 30 pts
    role_ratio = _token_overlap(lead.get("role", ""), pers_cfg.get("titles", []))
    sen_ratio = _token_overlap(lead.get("seniority", ""), pers_cfg.get("seniority", []))
    dept_ratio = _token_overlap(lead.get("department", ""), pers_cfg.get("departments", []))
    sen_dept_pts = round(max(sen_ratio, dept_ratio) * 8.0, 1)
    char_list = lead.get("characteristics", [])
    char_targets = pers_cfg.get("characteristics", []) + pers_cfg.get("pain_points", [])
    if char_list and char_targets:
        char_ratio = max(_token_overlap(ch, char_targets) for ch in char_list)
    elif char_list:
        char_ratio = 0.5
    else:
        char_ratio = 0.0
    persona_pts = round(role_ratio * 15.0 + sen_dept_pts + char_ratio * 7.0, 1)

    # 4. Geografía (10 pts)
    countries = geo_cfg.get("countries", [])
    geo_ratio = _token_overlap(lead.get("country", ""), countries) if countries else 0.7
    geo_pts = round(geo_ratio * 10.0, 1)

    total_fit = round(min(100.0, ind_pts + size_pts + persona_pts + geo_pts), 1)
    return total_fit, {
        "industry_pts": ind_pts,
        "size_pts": size_pts,
        "persona_pts": persona_pts,
        "geography_pts": geo_pts,
        "disqualified_by_exclusion": False,
    }


def _recency_factor(days: int) -> float:
    if days <= 30:
        return 1.0
    if days <= 90:
        return 0.85
    return 0.65


def _score_signals(
    lead: dict[str, Any],
    norm_weights: dict[str, float],
    labels: dict[str, str],
    custom_rules: dict[str, tuple[str, ...]],
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    valid_cats = set(norm_weights.keys())
    best_by_category: dict[str, float] = {}
    matched_positive: list[dict[str, Any]] = []
    other_signals: list[dict[str, Any]] = []

    for sig in lead.get("signals", []):
        summary = str(sig.get("summary") or "").strip()
        if not summary:
            continue
        cat = classify_signal_category(
            summary=summary,
            explicit_type=str(sig.get("signal_type") or ""),
            custom_rules=custom_rules,
            valid_categories=valid_cats,
        )
        status = str(sig.get("status") or "hypothesis").lower()
        conf_mult = 1.0 if status == "verified" else 0.6
        rec_days = int(sig.get("recency_days", 30))
        rec_mult = _recency_factor(rec_days)

        if cat in norm_weights and norm_weights[cat] > 0:
            cat_weight = norm_weights[cat]
            contribution = round(cat_weight * conf_mult * rec_mult, 1)
            prev_best = best_by_category.get(cat, 0.0)
            if contribution > prev_best:
                best_by_category[cat] = contribution

            matched_positive.append(
                {
                    "category": cat,
                    "category_label": labels.get(cat, cat),
                    "summary": summary,
                    "status": status,
                    "source": sig.get("source", "deepline"),
                    "recency_days": rec_days,
                    "weight_pct": cat_weight,
                    "points_contributed": contribution,
                }
            )
        else:
            other_signals.append(
                {
                    "category": cat,
                    "summary": summary,
                    "status": status,
                    "source": sig.get("source", "deepline"),
                }
            )

    base_signal_pts = sum(best_by_category.values())
    multi_signal_bonus = max(0, len(best_by_category) - 1) * 5.0
    total_signal = round(min(100.0, base_signal_pts + multi_signal_bonus), 1)
    return total_signal, matched_positive, other_signals


def _build_conversation_angle(
    lead: dict[str, Any],
    matched_signals: list[dict[str, Any]],
    icp_profile: dict[str, Any],
) -> str:
    pains = icp_profile.get("buyer_persona", {}).get("pain_points", [])
    pain_ref = pains[0] if pains else "coordinación operativa entre áreas"
    lang = lead.get("language", "es")
    company = lead.get("company", "su empresa")

    if matched_signals:
        top_sig = max(matched_signals, key=lambda s: s["points_contributed"])
        sig_text = top_sig["summary"]
        if lang == "pt":
            return (
                f"Acompanhei que a {company} ativou o sinal '{sig_text}'. "
                "Nessa fase de crescimento, lideranças operacionais costumam priorizar "
                "visibilidade e coordenação entre plantas e áreas."
            )
        if lang == "en":
            return (
                f"Noticed {company} triggered '{sig_text}'. "
                "At this expansion stage, operations leaders usually prioritize "
                "cross-site coordination and execution speed."
            )
        return (
            f"Vi que en {company} tienen activa la señal '{sig_text}'. "
            f"En esta etapa suele volverse prioritario resolver {pain_ref.lower()}."
        )

    if lang == "pt":
        return f"Sem sinal forte recente; abordagem consultiva pelo cargo ({lead.get('role', 'liderança')})."
    if lang == "en":
        return f"No strong recent trigger; consultative outreach anchored on {lead.get('role', 'role')} priorities."
    return f"Sin señal disparadora fuerte; apertura consultiva enfocada en prioridades de {lead.get('role', 'cargo')}."


def score_leads(
    icp_profile: dict[str, Any],
    leads: list[dict[str, Any]],
    weights_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evalúa todos los leads por Ajuste ICP + Señales Positivas y devuelve ranking."""
    norm_weights, labels, custom_rules, icp_w, sig_w = _norm_weights(weights_config, icp_profile)
    scored: list[dict[str, Any]] = []

    for lead in leads:
        icp_fit, icp_breakdown = _score_icp_fit(lead, icp_profile)
        signal_score, matched_pos, other_sigs = _score_signals(
            lead, norm_weights, labels, custom_rules
        )

        if icp_breakdown.get("disqualified_by_exclusion"):
            composite = round(min(25.0, icp_fit), 1)
        else:
            composite = round(min(100.0, icp_w * icp_fit + sig_w * signal_score), 1)

        if composite >= 75.0:
            tier = "Tier A — Alta Prioridad"
        elif composite >= 50.0:
            tier = "Tier B — Prioridad Media"
        else:
            tier = "Tier C — Nurture / Bajo Ajuste"

        enriched_lead = dict(lead)
        enriched_lead["scoring"] = {
            "composite_score": composite,
            "icp_fit_score": icp_fit,
            "signal_score": signal_score,
            "priority_tier": tier,
            "icp_fit_breakdown": icp_breakdown,
            "positive_signals_matched": matched_pos,
            "other_signals": other_sigs,
            "conversation_angle": _build_conversation_angle(lead, matched_pos, icp_profile),
        }
        scored.append(enriched_lead)

    scored.sort(
        key=lambda item: (
            item["scoring"]["composite_score"],
            item["scoring"]["signal_score"],
            item["scoring"]["icp_fit_score"],
        ),
        reverse=True,
    )

    tier_counts = {
        "tier_a": sum(1 for l in scored if l["scoring"]["priority_tier"].startswith("Tier A")),
        "tier_b": sum(1 for l in scored if l["scoring"]["priority_tier"].startswith("Tier B")),
        "tier_c": sum(1 for l in scored if l["scoring"]["priority_tier"].startswith("Tier C")),
    }

    return {
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "total_leads": len(scored),
        "tier_summary": tier_counts,
        "active_model_weights": {
            "icp_fit_blend": round(icp_w, 2),
            "signal_score_blend": round(sig_w, 2),
            "positive_signal_weights": norm_weights,
            "positive_signal_labels": labels,
        },
        "scored_leads": scored,
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI para calificar leads según Ajuste ICP y Señales Positivas."""
    parser = argparse.ArgumentParser(
        description="Modelo 2: Califica leads de Deepline por ICP Fit + Señales Positivas."
    )
    parser.add_argument("--icp", required=True, help="JSON de ICP refinado.")
    parser.add_argument("--leads", required=True, help="JSON normalizado de Deepline.")
    parser.add_argument(
        "--signal-weights",
        default="",
        help="JSON opcional para reajustar pesos de señales positivas y blend ICP/Señales.",
    )
    parser.add_argument("--output", required=True, help="Ruta de salida para leads calificados.")
    args = parser.parse_args(argv)

    icp_raw = json.loads(Path(args.icp).read_text(encoding="utf-8"))
    icp_profile = icp_raw.get("refined_icp") or icp_raw.get("normalized_icp") or icp_raw

    leads_raw = json.loads(Path(args.leads).read_text(encoding="utf-8"))
    leads = leads_raw.get("leads", leads_raw) if isinstance(leads_raw, dict) else leads_raw

    weights_cfg = None
    if args.signal_weights:
        weights_cfg = json.loads(Path(args.signal_weights).read_text(encoding="utf-8"))

    result = score_leads(icp_profile=icp_profile, leads=leads, weights_config=weights_cfg)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[OK] {result['total_leads']} leads calificados "
        f"(Tier A: {result['tier_summary']['tier_a']}, Tier B: {result['tier_summary']['tier_b']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
