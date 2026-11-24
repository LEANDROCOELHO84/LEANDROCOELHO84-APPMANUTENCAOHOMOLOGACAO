# Deploy Homologação — Checklist rápido

## 1. Código (este pacote)

- Conteúdo da pasta = raiz do repositório Git conectado ao Streamlit.
- Main file: `app.py`
- Requirements: `requirements.txt` (já inclui `sqlitecloud`)

## 2. Secrets no Streamlit Cloud

**Settings → Secrets** — cole e preencha:

```toml
SQLITECLOUD_URL = "sqlitecloud://SEU_HOST/banco_chamados.db?apikey=SUA_CHAVE"

[admin]
username = "admin"
password_hash = "SEU_HASH_AQUI"

WHATSAPP_TOKEN = "EAAB..."
WHATSAPP_PHONE_ID = "123456789012345"
WHATSAPP_DESTINO_PADRAO = "5511999999999"
WHATSAPP_AVISAR_SOLICITANTE = "1"
```

- `SQLITECLOUD_URL` **deve ficar no topo** (fora de `[admin]`), senão o dual-write não ativa.
- Sem essa chave o app mostra: *"💾 Somente Local — configure SQLITECLOUD_URL nos secrets"*

## 3. Após o deploy

1. Abra o app e confira o sidebar:
   - Ideal: `☁️ Local + SQLite Cloud (dual-write)`
2. Entre com perfil Admin.
3. Aba **Relatórios Gestão** → deve aparecer o **Resumo de alertas** no topo.
4. Teste:
   - Abrir chamado com WhatsApp preenchido
   - Concluir OS → verificar aviso automático ao solicitante
   - Logs de integrações na aba Admin

## 4. Fotos (Google Drive)

- Configure `GOOGLE_DRIVE_FOLDER_ID` + Service Account JSON nos secrets.
- Ou use o Apps Script (`apps_script_drive_fotos.gs`) como webhook.

## 5. Não versionar

- `.streamlit/secrets.toml` (use só o `.example`)
- `banco_chamados.db`
- Arquivos em `logs/` e `fotos_chamados/` com dados reais
