# Revisão do App Gestão de Chamados — 23/11/2026

## Estado atual (já implementado e revisado)

A versão consolidada cobre os pedidos principais e as melhorias apuradas desde a última atualização (14/11/2026):

- **Banco**: índices, tabelas `chamado_eventos`, `chamado_fotos`, `integracoes_log`.  
  Views: backlog, MTTR, tempo de resposta, peça parada, carga técnico, reincidência, preventivas vencidas, estoque crítico, custo manutenção, resposta por prioridade, conformidade preventiva.  
  Migrações dinâmicas via `_ensure_schema` / ALTER.  
  Script unificado: `schema_gestao_melhorado.sql` (idempotente).  
  Código formatado com black (line-length 100).

- **Relatórios** (em `relatorios_gestao.py` + `relatorios_indices.py` + aba **Relatórios Gestão**):
  - MTTR / SLA detalhado
  - **Conformidade SLA por prioridade** (% dentro do SLA)
  - Produtividade técnico (geral e por período)
  - Backlog aberto
  - Tempo de resposta
  - Peças paradas + **Tempo aguardando peça** (ordenado por espera)
  - Carga por técnico
  - Conformidade preventiva
  - Top reincidentes
  - Resposta média por prioridade
  - Custo por equipamento
  - First Time Fix Rate
  - Tendência MTTR mensal (melhorada: fallback abertura → início)
  - Volume mensal por setor
  - **Preventiva vs Corretiva** (proporção no período)
  - **Resumo de alertas** no topo da aba (backlog > 48h, alta aberta, aguardando peça, preventivas vencidas / 15 dias)

- **WhatsApp**: Cloud API oficial (Meta) + fallback gateway (Evolution/Z-API).  
  Aviso automático ao solicitante na conclusão + histórico de eventos (até 6).  
  Logs em `integracoes_log`.  
  Secrets: `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_AVISAR_SOLICITANTE=1` (padrão ligado).  
  Campo `contato_solicitante` obrigatório para o aviso.

- **Fotos**: Google Drive (recomendado e estável).  
  - Service Account (`google_midia.py`)  
  - Webhook Apps Script (`apps_script_drive_fotos.gs`)  
  **Google Fotos Library API NÃO serve** para álbum corporativo (desde abr/2025 a API só enxerga mídia criada pelo próprio app; scopes de leitura geral foram removidos; **service accounts não são suportados**).  
  Drive + backup do Drive no Fotos da conta dona da pasta é o caminho correto e estável.

- PDF preventiva individualizado por tipo de equipamento + Excel.

## Melhorias desta revisão (desde 14/11)

1. Pacote completo unificado (base com aba Relatórios Gestão + novos relatórios).
2. Resumo de alertas no topo da aba Relatórios Gestão (métricas de atenção imediata).
3. Relatório **Tempo aguardando peça** (operação).
4. Relatório **Conformidade SLA por prioridade** (tempos).
5. Relatório **Preventiva vs Corretiva** (preventivas).
6. Tendência MTTR mais robusta (usa abertura quando não há data de início).
7. Export Excel por bloco mantido em todos os relatórios.

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
