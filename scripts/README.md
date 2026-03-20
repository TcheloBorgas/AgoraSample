# scripts/

## Português (Brasil)
Scripts de apoio:
- `google_oauth_local_login.py`: abre o browser no PC e gera `data/google_token.json` para colar em **`GOOGLE_TOKEN_JSON`** no Render.
- `simulate_sessions.py`: simula múltiplas sessões e fluxos de criação/listagem/reagendamento/cancelamento.
- `test_proactive_suggestions.py`: valida geração de sugestões proativas.

Uso:
```bash
python scripts/google_oauth_local_login.py
python -m scripts.simulate_sessions
python -m scripts.test_proactive_suggestions
```

---
## English
Support scripts for local simulation and proactive suggestion validation.

---
## Español
Scripts de apoyo para simulación local y validación de sugerencias proactivas.
