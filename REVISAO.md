# Revisão do App Gestão de Chamados — out/2026 (atualização final)

## Estado atual (já implementado e revisado)

A versão em `app_versao_revisada/` cobre os pedidos principais:

- **Banco**: índices, tabelas `chamado_eventos`, `chamado_fotos`, `integracoes_log`.  
  Views: backlog, MTTR, tempo de resposta, peça parada, carga técnico, reincidência, preventivas vencidas, estoque crítico, custo manutenção, resposta por prioridade, conformidade preventiva.  
  Migrações dinâmicas via `_ensure_schema` / ALTER.  
  Script unificado: `schema_gestao_melhorado.sql` (idempotente).  
  Código formatado com black (line-length 100).

- **Relatórios** (em `relatorios_gestao.py` + `relatorios_indices.py`):
  - MTTR / SLA
  - Produtividade técnico (geral e por período)
  - Backlog aberto
  - Tempo de resposta
  - Peças paradas
  - Carga por técnico
  - Conformidade preventiva
  - Top reincidentes
  - Resposta média por prioridade
  - Custo por equipamento
  - **Novos**: First Time Fix Rate, Tendência MTTR mensal

- **WhatsApp**: Cloud API oficial (Meta) + fallback gateway (Evolution/Z-API).  
  Aviso automático ao solicitante na conclusão + histórico de eventos (até 6).  
  Logs em `integracoes_log`.  
  Secrets: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_AVISAR_SOLICITANTE=1` (padrão ligado).  
  Campo `contato_solicitante` obrigatório para o aviso.

- **Fotos**: Google Drive (recomendado e estável).  
  - Service Account (`google_midia.py`)  
  - Webhook Apps Script (`apps_script_drive_fotos.gs`)  
  **Google Fotos Library API NÃO serve** para álbum corporativo (desde abr/2025 a API só enxerga mídia criada pelo próprio app; scopes de leitura geral foram removidos; service accounts não são suportados).  
  Drive + backup do Drive no Fotos da conta dona da pasta é o caminho correto.

- PDF preventiva individualizado por tipo de equipamento + Excel.

## Recomendações práticas

### Banco
```bash
sqlite3 banco_chamados.db < schema_gestao_melhorado.sql
```
O app já cria o que falta na primeira execução (`_ensure_schema`).

### WhatsApp
- Preferir Cloud API oficial.  
- Manter `WHATSAPP_AVISAR_SOLICITANTE=1`.  
- Campo `contato_solicitante` na abertura do chamado é necessário para o aviso automático.  

### Fotos
- Usar Drive (pasta compartilhada + Apps Script ou Service Account).  
- Se o backup do Drive estiver ligado na conta dona da pasta, as fotos aparecem também no Google Fotos dessa conta.  
- Não usar Library API de Fotos para este caso de uso.

### Código
Já formatado com black. Para reaplicar:
```bash
python -m black --line-length 100 *.py
```

---
App publicado: https://appmanutencaogit-xp3czwrvazfigblbmjwjr2.streamlit.app
