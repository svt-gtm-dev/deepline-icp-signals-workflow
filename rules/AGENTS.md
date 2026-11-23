# Reglas del Plugin — Deepline ICP & Signals Workflow

Estas reglas aplican automáticamente mientras el plugin `deepline-icp-signals` esté habilitado:

1. **Auditar calidad del ICP antes de gastar créditos en Deepline.** Ejecuta siempre primero el Modelo 1 (`scripts/icp_quality_scorer.py`). Si el puntaje es menor a `min_icp_quality_score` configurado en `config/workflow.config.json` (por defecto `80`), haz primero las preguntas aclaratorias y presenta las propuestas de targeting al usuario antes de lanzar búsquedas en Deepline.
2. **Configuración moldeable por el usuario.** Respeta los pesos de `config/workflow.config.json` (tanto `icp_weight`/`signal_weight` como los pesos de las 5 señales positivas base y señales personalizadas en `custom_positive_signals`). Ofrece al usuario ajustarlos sin modificar código Python.
3. **Cero procesos MCP propios en background.** Los scripts Python corren bajo demanda (`on-demand`). Cuando el usuario ya tenga conectado un servidor MCP de Deepline o CRM (HubSpot, Salesforce, Lemlist, Apollo, Clay), aprovéchalo como herramienta existente o genera el payload listo para sincronizar.
4. **Entrega obligatoria en texto + menú de exportación.** Muestra siempre el resultado completo en texto (`review_report.txt`) para revisión humana y despliega explícitamente las opciones de salida: `json`, `csv` o `connector` (plataforma conectada vía MCP/API).
5. **Higiene NDA y PII estricta.** Nunca expongas correos electrónicos literales, credenciales ni API keys en reportes, JSONs, CSVs o payloads de demostración.
