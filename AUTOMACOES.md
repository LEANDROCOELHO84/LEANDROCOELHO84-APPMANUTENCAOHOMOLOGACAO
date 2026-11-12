# Automações do App — Guia consolidado

App: https://appmanutencaogit-xp3czwrvazfigblbmjwjr2.streamlit.app

Objetivo: reduzir trabalho manual de quem solicita e de quem executa,
com avisos automáticos, fotos na nuvem, PDF/Excel e indicadores.

---

## 1. WhatsApp (conclusão de OS)

**Arquivos:** `whatsapp_api.py`, `integracoes.py`

**Fluxo**
1. Técnico conclui o chamado no app.
2. Sistema monta mensagem com OS, setor, equipamento e resumo.
3. Envia WhatsApp ao **solicitante** (`contato_solicitante`) se
   `WHATSAPP_AVISAR_SOLICITANTE=1` (padrão ligado).
4. Registra resultado em `integracoes_log`.

**Secrets** (`.streamlit/secrets.toml`)
```
WHATSAPP_TOKEN = "token_meta"
WHATSAPP_PHONE_ID = "id_do_numero"
WHATSAPP_AVISAR_SOLICITANTE = "1"
```
Fallback gateway (Evolution / Z-API):
```
WHATSAPP_API_URL = "https://..."
WHATSAPP_INSTANCE = "..."
WHATSAPP_APIKEY = "..."
```

**Admin:** aba Logs Integrações — diagnóstico e teste de envio.

---

## 2. Fotos na nuvem (Google Drive)

**Arquivos:** `google_midia.py`, `apps_script_drive_fotos.gs`, `integracoes.py`

**Por quê Drive e não Google Fotos?**  
A Library API do Google Fotos só enxerga mídia criada pelo próprio app
e não aceita service account corporativo. Drive é o caminho estável.

**Opção A — Service Account**
```
GOOGLE_SERVICE_ACCOUNT_JSON = "{...json...}"
DRIVE_FOLDER_ID = "id_da_pasta"
```

**Opção B — Apps Script (webhook)**  
Publicar o script `apps_script_drive_fotos.gs` e configurar a URL no secrets.

Fotos de abertura/solução são enviadas e registradas em `chamado_fotos`.

---

## 3. Eventos e histórico do chamado

**Tabelas:** `chamado_eventos`, `integracoes_log`, `chamado_fotos`

Cada mudança relevante (abertura, início, conclusão, peça, WhatsApp)
pode ser registrada para auditoria e para enriquecer a mensagem ao solicitante.

---

## 4. PDF de preventiva (automação documental)

**Arquivo:** `gerar_relatorio_preventiva.py`

Ao concluir preventiva:
- checklist SIM/NÃO + observações por item
- PDF individualizado (layout CRN)
- download no histórico do equipamento

---

## 5. Exportação Excel

**Arquivo:** `exportar_excel.py`

Dashboard e cadastros:
- Exportar tudo (várias abas)
- Chamados, compras, manutenções, equipamentos, almoxarifado

---

## 6. Relatórios e índices (otimizar equipe)

**Arquivos:** `relatorios_gestao.py`, `relatorios_indices.py`, `schema_gestao_melhorado.sql`

Indicadores prontos:
- MTTR / SLA / tendência mensal
- First Time Fix Rate (FTFR)
- Backlog aberto
- Tempo de resposta (geral e por prioridade)
- Peças paradas
- Carga e produtividade por técnico
- Conformidade preventiva
- Top reincidentes
- Custo por equipamento

Views SQL criadas/atualizadas automaticamente no `_ensure_schema`.

---

## 7. Notificações no app

**Arquivo:** `notificacoes.py`

Alertas sonoros, preferências do usuário e feedback visual ao concluir OS/preventiva.

---

## Ordem sugerida de ativação

1. Subir o app com o banco atual (`banco_chamados.db`).
2. Configurar admin em `secrets.toml`.
3. Ativar WhatsApp (token + phone id) e testar na aba Integrações.
4. Configurar pasta Drive para fotos.
5. Usar relatórios no Admin para acompanhar a equipe diariamente.
6. Gerar PDF de preventiva e Excel conforme necessidade.

## Modelos extras

Pasta `modelos_documentos/`:
- Exemplo de relatório de preventiva (PDF)
- Termo de troca/entrega de item — fone LEF-1006 (PDF + Word, papel timbrado CRN)
