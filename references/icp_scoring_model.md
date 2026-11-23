# Modelo de Calidad y Refinamiento del ICP (`icp_quality_scorer.py`)

Este documento define las reglas del **Modelo 1**, encargado de auditar el ICP entregado por el usuario antes de consultar **Deepline**.

---

## 1. Dimensiones y Pesos (Total: 100 puntos)

| Dimensión | Peso Máximo | Sub-criterios evaluados |
|---|---:|---|
| `company_size` | `20` | `min_employees` definido (`+7`), `max_employees` acotado y consistente (`+6`), `revenue_range_usd` o `company_stage` (`+7`) |
| `industry_segment` | `25` | `target_industries` con al menos 1 vertical clara (`+10`), `sub_segments` o `keywords` (`+9`), `excluded_industries` para filtrar ruido (`+6`) |
| `buyer_persona` | `25` | `titles` con cargos concretos (`+8`), `seniority` y `departments` (`+6`), `pain_points` (`+6`), `characteristics` o `kpis` (`+5`) |
| `suggested_signals` | `20` | Presencia de señales sugeridas (`+10`), especificidad y mapeo a señales positivas accionables en Deepline (`+10`) |
| `geography_and_market` | `10` | `countries` o regiones definidas (`+6`), `languages` declarados (`+4`) |

---

## 2. Niveles de Madurez (`readiness_tier`)

- **`ready` (`80 – 100` pts):** El ICP es suficientemente específico para consultar Deepline con alto retorno sobre créditos.
- **`needs_tuning` (`50 – 79.9` pts):** El ICP es operable, pero tiene brechas (p. ej. falta rango máximo de empleados, dolores del buyer persona o exclusiones). El agente **debe** presentar preguntas aclaratorias y propuestas antes de lanzar la búsqueda completa.
- **`incomplete` (`< 50` pts):** Alto riesgo de traer leads irrelevantes. El agente **debe** detenerse, hacer las preguntas prioritarias al usuario y ofrecer un borrador de targeting propuesto para su validación.

---

## 3. Protocolo de Preguntas y Propuestas del Agente

Cuando una dimensión obtenga menos del `80%` de su puntaje máximo:
1. **`clarifying_questions`**: Se generan preguntas concretas orientadas a cerrar cada hueco detectado (por ejemplo: *"¿Qué rango mínimo y máximo de empleados define mejor tu sweet spot?"* o *"¿Qué características del día a día o KPIs distinguen a tu buyer persona ideal?"*).
2. **`agent_targeting_proposals`**: El agente investiga la industria/cargo entregado y propone añadidos accionables:
   - Cargos equivalentes por país/idioma (ej. `Gerente de Planta` -> `Director de Operaciones`, `Plant Manager`, `Diretor Industrial`).
   - Exclusiones preventivas comunes (`Agencias`, `Freelancers`, `Sector Público` si no aplica).
   - Señales positivas recomendadas del catálogo base (`company_expansion`, `recent_investment`, `active_hiring`, `new_facility_or_office`, `new_market_entry`).

El usuario puede:
- Responder a las preguntas y actualizar su ICP manualmente, o
- Aceptar las propuestas con `--apply-proposals` para enriquecer el ICP automáticamente antes de pasar a Deepline.
