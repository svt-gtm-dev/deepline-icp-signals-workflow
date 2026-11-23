"""Orquestador CLI extremo a extremo del workflow Deepline ICP & Signals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from deepline_provider import fetch_deepline_records
from export_dispatcher import (
    SUPPORTED_CONNECTORS,
    dispatch_export,
    format_export_options_menu,
)
from icp_quality_scorer import refine_icp_profile
from lead_signal_scorer import score_leads


def _prompt_interactive_export(default_format: str, default_connector: str) -> tuple[str, str]:
    """Despliega las opciones al usuario en consola y captura su elección."""
    print()
    print(format_export_options_menu())
    choice = input("Selecciona una opción [1=json, 2=csv, 3=connector, 4=all] (Enter=4): ").strip()
    mapping = {"1": "json", "2": "csv", "3": "connector", "4": "all"}
    chosen_fmt = mapping.get(choice, choice.lower() if choice.lower() in mapping.values() else default_format)

    chosen_conn = default_connector
    if chosen_fmt in {"connector", "all"}:
        conn_keys = ", ".join(SUPPORTED_CONNECTORS.keys())
        conn_in = input(
            f"Plataforma MCP/API destino ({conn_keys}) [Enter={default_connector}]: "
        ).strip()
        if conn_in in SUPPORTED_CONNECTORS:
            chosen_conn = conn_in
    return chosen_fmt, chosen_conn


def _merge_weights_config(
    plugin_cfg: dict[str, Any],
    override_cfg: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Combina los pesos base del plugin con un archivo --signal-weights opcional."""
    base: dict[str, Any] = {}
    for key in ("icp_weight", "signal_weight", "signal_weights", "custom_positive_signals"):
        if key in plugin_cfg:
            base[key] = plugin_cfg[key]

    if override_cfg:
        for key, val in override_cfg.items():
            if key == "signal_weights" and isinstance(val, dict) and isinstance(base.get(key), dict):
                merged_sw = dict(base[key])
                merged_sw.update(val)
                base[key] = merged_sw
            else:
                base[key] = val

    return base or None


def run_workflow(
    icp_path: Path,
    out_dir: Path,
    config_path: Path | None = None,
    deepline_mode: str = "auto",
    deepline_input: Path | None = None,
    signal_weights_path: Path | None = None,
    apply_icp_proposals: bool | None = None,
    export_format: str | None = None,
    connector_target: str | None = None,
    min_score: float | None = None,
    live_push: bool = False,
    html_out: Path | None = None,
    interactive: bool = False,
) -> dict[str, Any]:
    """Ejecuta las 4 etapas completas del workflow de señales con Deepline."""
    plugin_cfg: dict[str, Any] = {}
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(f"No existe archivo de configuración del plugin: {config_path}")
        plugin_cfg = json.loads(config_path.read_text(encoding="utf-8"))

    eff_apply = (
        apply_icp_proposals
        if apply_icp_proposals is not None
        else bool(plugin_cfg.get("apply_icp_proposals_by_default", True))
    )
    eff_format = (
        export_format
        if export_format is not None
        else str(plugin_cfg.get("default_export_format", "all"))
    )
    eff_conn = (
        connector_target
        if connector_target is not None
        else str(plugin_cfg.get("default_connector_target", "hubspot-mcp"))
    )
    eff_min_score = (
        min_score
        if min_score is not None
        else float(plugin_cfg.get("min_export_score", 0.0))
    )

    raw_icp = json.loads(icp_path.read_text(encoding="utf-8"))
    icp_refinement = refine_icp_profile(raw_icp, apply_proposals=eff_apply)
    icp_before = icp_refinement["before_audit"]
    icp_after = icp_refinement["after_audit"]
    refined_icp = icp_refinement["refined_icp"]

    deepline_result = fetch_deepline_records(
        icp_profile=refined_icp,
        mode=deepline_mode,
        deepline_input=deepline_input,
    )

    override_weights = (
        json.loads(signal_weights_path.read_text(encoding="utf-8"))
        if signal_weights_path
        else None
    )
    weights_cfg = _merge_weights_config(plugin_cfg, override_weights)

    scoring_result = score_leads(
        icp_profile=refined_icp,
        leads=deepline_result["leads"],
        weights_config=weights_cfg,
    )

    chosen_fmt = eff_format
    chosen_conn = eff_conn
    if interactive:
        chosen_fmt, chosen_conn = _prompt_interactive_export(eff_format, eff_conn)

    export_res = dispatch_export(
        out_dir=out_dir,
        export_format=chosen_fmt,
        icp_before=icp_before,
        icp_after=icp_after,
        deepline_result=deepline_result,
        scoring_result=scoring_result,
        connector_target=chosen_conn,
        min_score=eff_min_score,
        live_push=live_push,
        html_out=html_out,
    )

    return {
        "icp_quality_before": icp_before["quality_score"],
        "icp_quality_after": icp_after["quality_score"],
        "total_leads": scoring_result["total_leads"],
        "tier_summary": scoring_result["tier_summary"],
        "export_format": export_res["export_format"],
        "generated_files": export_res["generated_files"],
        "text_report": export_res["text_report"],
        "export_options": export_res["export_options"],
    }


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada CLI del workflow completo."""
    parser = argparse.ArgumentParser(
        description="Ejecuta el workflow completo Deepline ICP & Signals (Modelo 1 -> Deepline -> Modelo 2 -> Export)."
    )
    parser.add_argument("--icp", required=True, help="JSON con definición inicial del ICP.")
    parser.add_argument(
        "--config",
        default="",
        help="JSON de configuración moldeable del plugin (ej. config/workflow.config.json).",
    )
    parser.add_argument(
        "--no-apply-proposals",
        action="store_true",
        default=None,
        help="No aplica automáticamente las propuestas de targeting del agente sobre el ICP.",
    )
    parser.add_argument(
        "--deepline-mode",
        choices=["auto", "dataset", "cli", "api"],
        default="auto",
        help="Modo de extracción en Deepline.",
    )
    parser.add_argument(
        "--deepline-input",
        default="",
        help="Archivo JSON/JSONL opcional proveniente de Deepline CLI o MCP.",
    )
    parser.add_argument(
        "--signal-weights",
        default="",
        help="JSON opcional con pesos personalizados para señales positivas.",
    )
    parser.add_argument(
        "--export-format",
        choices=["json", "csv", "connector", "all"],
        default=None,
        help="Formato de exportación elegido por el usuario.",
    )
    parser.add_argument(
        "--connector-target",
        choices=list(SUPPORTED_CONNECTORS.keys()),
        default=None,
        help="Plataforma MCP o API destino cuando export-format incluye connector.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Score mínimo (0-100) para incluir leads en el payload del conector MCP/API.",
    )
    parser.add_argument(
        "--live-push",
        action="store_true",
        help="Envía en vivo el payload del conector usando variables de entorno de endpoint/token.",
    )
    parser.add_argument(
        "--out-dir",
        default="out",
        help="Carpeta destino para reporte en texto y artefactos exportados.",
    )
    parser.add_argument(
        "--html-out",
        default="",
        help="Ruta opcional para compilar el simulador HTML interactivo.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Despliega el menú de formatos en terminal para elegir en vivo.",
    )

    args = parser.parse_args(argv)
    icp_path = Path(args.icp)
    if not icp_path.exists():
        print(f"[ERROR] No existe archivo ICP: {icp_path}", file=sys.stderr)
        return 1

    apply_override = False if args.no_apply_proposals else None
    try:
        summary = run_workflow(
            icp_path=icp_path,
            out_dir=Path(args.out_dir),
            config_path=Path(args.config) if args.config else None,
            deepline_mode=args.deepline_mode,
            deepline_input=Path(args.deepline_input) if args.deepline_input else None,
            signal_weights_path=Path(args.signal_weights) if args.signal_weights else None,
            apply_icp_proposals=apply_override,
            export_format=args.export_format,
            connector_target=args.connector_target,
            min_score=args.min_score,
            live_push=args.live_push,
            html_out=Path(args.html_out) if args.html_out else None,
            interactive=args.interactive,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(summary["text_report"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
