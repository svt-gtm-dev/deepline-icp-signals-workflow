# Taxonomía de Señales Positivas e Integración con Deepline

Este documento especifica cómo **Deepline** entrega empresas/leads/señales y cómo **Modelo 2 (`lead_signal_scorer.py`)** evalúa su importancia para el usuario.

---

## 1. Catálogo de 5 Señales Positivas por Defecto

El usuario puede ajustar los pesos de estas 5 categorías o agregar señales nuevas según su momento comercial:

| Clave (`signal_type`) | Nombre legible | Peso Default | Palabras clave y disparadores (ES / PT / EN) |
|---|---|---:|---|
| `company_expansion` | Expansión de la empresa | `25` | `expansión`, `crecimiento`, `escala`, `nueva línea`, `expansão`, `expansion`, `scaling operations` |
| `recent_investment` | Inversiones recientes | `20` | `inversión`, `ronda`, `capital`, `serie a/b/c`, `capex`, `investimento`, `funding`, `raised` |
| `active_hiring` | Búsqueda activa de personal | `20` | `contratando`, `vacantes`, `búsqueda activa`, `reclutando`, `vagas`, `hiring`, `open roles` |
| `new_facility_or_office` | Apertura de nuevas fábricas, plantas u oficinas | `20` | `nueva planta`, `fábrica`, `bodega`, `cedis`, `nueva oficina`, `sede`, `nova fábrica`, `new plant`, `new office`, `warehouse` |
| `new_market_entry` | Expansión o entrada a nuevos mercados | `15` | `nuevo mercado`, `entrada a`, `internacionalización`, `lanzamiento en`, `novo mercado`, `new market`, `market entry` |

---

## 2. Cómo personaliza el usuario el modelo de Scoring

El usuario puede pasar un archivo JSON vía `--signal-weights` (ver `examples/signal_weights_custom.json`) con:
- **`signal_weights`**: reasigna importancia numérica a cada una de las 5 señales base (ej. poner `new_facility_or_office: 40` y `recent_investment: 5` si vende infraestructura industrial).
- **`icp_weight` / `signal_weight`**: ajusta el balance entre ajuste firmográfico/persona vs. intensidad de señales (default `0.55` / `0.45`).
- **`custom_positive_signals`**: lista de nuevas señales definidas por el usuario con `key`, `label`, `weight` y `keywords`.

---

## 3. Modos de Conexión con Deepline (`deepline_provider.py`)

1. **Deepline MCP Server (Agente en sesión):**
   El agente invoca las herramientas MCP de Deepline usando la query firmográfica y de señales construida por `build_deepline_query(icp_profile)`, guarda los resultados en JSON y los pasa al workflow vía `--deepline-input`.
2. **Deepline CLI (`deepline`):**
   Si el binario `deepline` está disponible en el `PATH` y se ejecuta con `--deepline-mode cli`, el proveedor lanza la consulta CLI y normaliza su salida JSON.
3. **Deepline REST API:**
   Si existe `DEEPLINE_API_KEY` en variables de entorno y se ejecuta con `--deepline-mode api`, consulta el endpoint configurado en `DEEPLINE_API_URL` enviando la credencial solo en memoria (nunca escrita en archivos).
4. **Dataset Local / Simulación (`dataset`):**
   Lee archivos locales (`examples/sample_deepline_payload.json`) para pruebas deterministas, demos offline y auditoría de puntajes sin consumo de créditos.
