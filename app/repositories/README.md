# app/repositories/

## Português (Brasil)
Camada de persistência MongoDB:
- `session_repository.py` -> coleção `sessions`
- `conversation_repository.py` -> coleção `conversation_history`
- `preference_repository.py` -> coleção `user_preferences`
- `pattern_repository.py` -> coleção `meeting_patterns`
- `action_log_repository.py` -> coleção `action_logs`

Responsabilidade: salvar estado, histórico e preferências sem misturar regra de negócio.

---
## English
MongoDB data access layer split by concern (sessions, history, preferences, patterns, logs).

---
## Español
Capa de acceso a MongoDB separada por responsabilidad (sesiones, historial, preferencias, patrones, logs).
