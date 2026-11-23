---
name: deepline-icp-signals
description: >-
  Orquestador multiagéntico del plugin Deepline ICP & Signals Workflow. Evalúa la calidad
  del ICP inicial (preguntas y propuestas de targeting), extrae empresas/leads/señales con
  Deepline sin procesos MCP en background, aplica scoring dual configurable (Ajuste ICP +
  5 señales positivas) y entrega revisión obligatoria en texto más exportación a JSON, CSV
  o plataformas conectadas por MCP/API.
---

# Deepline ICP & Signals — Plugin Multiagéntico y Moldeable

Este plugin convierte el workflow en una unidad instalable y adaptable mediante `config/workflow.config.json` y 3 subagentes especializados que pueden correr en paralelo o en secuencia con distintos modelos (razonamiento para estrategia de ICP, modelos rápidos para captura Deepline y exportación).

---

## Arquitectura Multiagéntica (3 Roles Especializados)

| Subagente | Responsabilidad | Script / Herramienta | Perfil de modelo sugerido |
|---|---|---|---|
| `icp-strategist` | Audita el ICP (`0–100`), redacta preguntas aclaratorias e investiga propuestas de targeting | `scripts/icp_quality_scorer.py` | Modelo de razonamiento / estrategia |
| `deepline-signal-hunter` | Construye query Deepline, extrae cuentas/leads/señales vía Deepline MCP/CLI/API/Dataset y redacta PII | `scripts/deepline_provider.py` | Modelo rápido de ejecución |
| `gtm-scoring-exporter` | Ejecuta el scoring dual según `config/workflow.config.json`, entrega revisión en texto y despliega opciones `JSON`/`CSV`/`MCP-API` | `scripts/lead_signal_scorer.py` + `scripts/export_dispatcher.py` | Modelo rápido determinista |

---

## Configuración Moldeable (`config/workflow.config.json`)

El usuario puede adaptar todo el comportamiento del plugin editando únicamente `config/workflow.config.json`:
- `min_icp_quality_score`: umbral para pedir aclaraciones o propuestas antes de consultar Deepline (`80.0` por defecto).
- `apply_icp_proposals_by_default`: si se aplican automáticamente las propuestas del agente al refinar el ICP.
- `icp_weight` / `signal_weight`: balance entre ajuste ICP y fuerza de señales (`0.55` / `0.45`).
- `signal_weights`: pesos configurables para `company_expansion`, `recent_investment`, `active_hiring`, `new_facility_or_office` y `new_market_entry`.
- `custom_positive_signals`: señales positivas adicionales creadas por el usuario (`key`, `label`, `weight`, `keywords`).
- `default_export_format` y `default_connector_target`: formato por defecto (`json`, `csv`, `connector`, `all`) y plataforma destino (`hubspot-mcp`, `lemlist-api`, `clay-webhook`, `apollo-api`, `salesforce-mcp`, `deepline-mcp`, `custom-api`).

---

## Ejecución Rápida Unificada

```bash
python scripts/run_workflow.py \
  --icp examples/icp_industrial_latam.json \
  --config config/workflow.config.json \
  --deepline-input examples/sample_deepline_payload.json \
  --out-dir out \
  --html-out out/signals_dashboard.html
```

Cualquier flag explícito en terminal (`--export-format`, `--connector-target`, `--signal-weights`, `--min-score`, `--no-apply-proposals`) sobrescribe la configuración base de `--config`.
