---
name: deepline-icp-signals-workflow
description: >-
  Blueprint y workflow ejecutable de GTM Engineering para automatizar señales B2B con
  Deepline. Recibe un ICP inicial del usuario (tamaño, segmento/industria, buyer persona
  y señales sugeridas), ejecuta un modelo Python de pesos y calidad del ICP para hacer
  preguntas de ajuste y propuestas de targeting, extrae empresas y leads mediante Deepline
  (CLI, MCP, API o dataset local), aplica un segundo modelo dual de scoring (Ajuste ICP +
  señales positivas configurables: expansiones, inversiones recientes, búsqueda activa de
  personal, apertura de nuevas fábricas/plantas/oficinas y entrada a nuevos mercados) y
  despliega opciones de entrega (JSON, CSV o plataforma con conexión MCP/API) junto con
  un reporte completo en texto para revisión del usuario.
---

# Deepline ICP & Signals Workflow — Automatización de Señales B2B

Usa este workflow cuando el usuario quiera **calificar su ICP, descubrir empresas/leads con señales activas vía Deepline y priorizar cuentas listas para outbound** sin perder trazabilidad ni depender de cajas negras.

---

## Flujo del Blueprint en 4 Etapas

### Etapa 1 — Recepción, Auditoría de Calidad y Refinamiento del ICP
El usuario entrega su definición inicial de ICP (en JSON o lenguaje natural):
- **Tamaño de empresa objetivo:** rango de empleados, facturación estimada o segmento.
- **Segmento / Industria:** verticales objetivo, sub-segmentos, palabras clave y exclusiones.
- **Buyer Persona:** cargos, seniority, departamentos, dolores, características y KPIs.
- **Señales sugeridas:** eventos que suelen despertar interés para iniciar conversación.
- **Geografía y mercado:** países/regiones e idiomas.

Ejecuta el primer modelo Python de calidad (`scripts/icp_quality_scorer.py`):
```bash
python scripts/icp_quality_scorer.py --icp examples/icp_incomplete_draft.json --output out/icp_audit.json --apply-proposals
```
- **Regla de interacción del agente:** Si `quality_score < 80` (o si hay dimensiones en estado `partial` o `missing`), presenta al usuario:
  1. El desglose de pesos y puntaje por dimensión (`0–100`).
  2. Las **preguntas adicionales** (`clarifying_questions`) para cerrar brechas.
  3. Las **propuestas de targeting enriquecido** (`agent_targeting_proposals`) basadas en investigación GTM (cargos equivalentes, filtros firmográficos y señales positivas recomendadas) para que el usuario apruebe o ajuste antes de consultar Deepline.

Consulta los detalles del modelo en [icp_scoring_model.md](./references/icp_scoring_model.md).

---

### Etapa 2 — Adquisición de Empresas, Leads y Señales con Deepline
Con el ICP ajustado, ejecuta `scripts/deepline_provider.py` para construir la query estructurada de Deepline y traer cuentas + contactos + señales:
```bash
python scripts/deepline_provider.py --icp out/icp_refined.json --deepline-input examples/sample_deepline_payload.json --output out/deepline_leads.json
```
Modos soportados automáticamente por el proveedor:
1. **Deepline MCP Server** (cuando el agente tiene el servidor MCP de Deepline conectado en sesión: ejecuta las búsquedas/waterfalls de cuentas, contactos y señales y pasa la salida normalizada).
2. **Deepline CLI** (`deepline` detectado en terminal).
3. **Deepline REST API** (`DEEPLINE_API_KEY` en variables de entorno, sin guardar secretos en disco).
4. **Dataset local / Modo offline** (`--deepline-input` o fallback al dataset de ejemplo para pruebas y demostraciones sin consumo de créditos).

> **Higiene NDA y PII:** `deepline_provider.py` redacta direcciones de correo literales en las salidas públicas para evitar filtración accidental de PII en artefactos compartidos, preservando el estado de verificación (`email_status`) y URLs públicas de LinkedIn/empresa.

---

### Etapa 3 — Modelo Dual de Scoring (Ajuste ICP + Señales Positivas Configurables)
Ejecuta `scripts/lead_signal_scorer.py` para puntuar cada empresa y lead en dos ejes (`0–100`) y calcular su puntaje compuesto:
1. **ICP Fit Score (`55%` por defecto):** ajuste contra industria/segmento (`35%`), tamaño de empresa (`25%`), características/cargo/seniority del buyer persona (`30%`) y geografía (`10%`).
2. **Signal Score (`45%` por defecto):** evalúa las señales positivas detectadas según su peso para el usuario, estado de verificación (`verified` = `1.0x`, `hypothesis` = `0.6x`) y frescura.

**Señales positivas base (pesos ajustables por el usuario):**
| Categoría | Qué detecta | Peso default |
|---|---|---|
| `company_expansion` | Expansiones de la empresa, crecimiento operativo o nuevas líneas | `25` |
| `recent_investment` | Inversiones recientes, rondas de capital o CAPEX | `20` |
| `active_hiring` | Búsqueda activa de personal y vacantes clave del área | `20` |
| `new_facility_or_office` | Apertura de nuevas fábricas, plantas, bodegas u oficinas | `20` |
| `new_market_entry` | Expansión o entrada a nuevos mercados, países o regiones | `15` |

El usuario puede modificar estos pesos (o añadir señales personalizadas) editando `signal_weights` / `custom_signal_weights` en el JSON o pasando `--signal-weights examples/signal_weights_custom.json`. Consulta [deepline_signals_taxonomy.md](./references/deepline_signals_taxonomy.md).

```bash
python scripts/lead_signal_scorer.py --icp out/icp_refined.json --leads out/deepline_leads.json --signal-weights examples/signal_weights_custom.json --output out/scored_leads.json
```

---

### Etapa 4 — Despliegue de Opciones de Exportación + Revisión en Texto
Antes o al finalizar la corrida, el workflow **despliega las opciones disponibles para que el usuario decida el formato de entrega** (`--export-format` o selección interactiva `--interactive`):
1. **`json`** — Exporta el payload estructurado completo (`scored_leads.json`) con auditoría ICP, scores y señales.
2. **`csv`** — Exporta tabla plana (`scored_leads.csv`) lista para CRM, hojas de cálculo o secuenciadores.
3. **`connector`** — Prepara o envía la lista de contactos hacia una plataforma conectada con **MCP o API** dentro del entorno del usuario (`hubspot-mcp`, `lemlist-api`, `clay-webhook`, `apollo-api`, `salesforce-mcp`, `deepline-mcp`, `custom-api`). Opera en `dry-run` seguro por defecto salvo que el usuario autorice `--live-push`.
4. **`all`** — Genera los tres artefactos de exportación de una vez.

**Entrega obligatoria en texto:** Independientemente del formato elegido (`json`, `csv` o `connector`), el script **siempre** genera y muestra el **resultado completo en texto** (`review_report.txt` + salida en consola) para que el usuario revise el Score del ICP, las señales positivas encontradas y los mejores leads antes de activar campañas. Opcionalmente compila también el tablero interactivo HTML (`demo/index.html`).

```bash
python scripts/run_workflow.py \
  --icp examples/icp_industrial_latam.json \
  --deepline-input examples/sample_deepline_payload.json \
  --export-format all \
  --connector-target hubspot-mcp \
  --out-dir out \
  --html-out out/signals_dashboard.html
```

---

## Adaptadores Multi-Agente
- Claude Code / Projects: [claude_prompt.md](./adapters/claude_prompt.md)
- ChatGPT (Code Interpreter / Web): [chatgpt_prompt.md](./adapters/chatgpt_prompt.md)
- Gemini (Gems / Antigravity): [gemini_prompt.md](./adapters/gemini_prompt.md)

---

## Checklist antes de entregar al usuario
1. ¿Se evaluó la calidad del ICP con `icp_quality_scorer.py` y se presentaron preguntas/propuestas de mejora si faltaba precisión?
2. ¿Las empresas, leads y señales traídas desde Deepline mantienen trazabilidad (`verified` vs `hypothesis`) y cero credenciales expuestas?
3. ¿Se aplicaron las 5 señales positivas configurables (expansión, inversión, contratación, nuevas fábricas/plantas/oficinas, nuevos mercados) permitiendo al usuario reajustar pesos?
4. ¿Se desplegaron al usuario las 3 opciones de resultado (`JSON`, `CSV`, `Plataforma MCP/API`) y se entregó además el resumen completo en texto para su revisión?
