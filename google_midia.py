"""
Arquivo de fotos dos chamados.

Google Photos Library API NÃO serve como álbum geral da empresa:
a API só gerencia mídia criada pelo próprio app e o upload "para o
Google Fotos do usuário" está restrito. O caminho estável para o
Streamlit Cloud é o Google Drive (pasta compartilhada).

Secrets:

  GOOGLE_DRIVE_FOLDER_ID = "1abc..."
  GOOGLE_SERVICE_ACCOUNT_JSON = '''{ ... json da service account ... }'''

A service account precisa ter permissão de Editor na pasta.
Fotos locais continuam em fotos_chamados/; o Drive fica como backup
e gera um link público/compartilhado gravado em foto_url.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except Exception:
    st = None

logger = logging.getLogger("chamados_app")

FOTOS_DIR = Path("fotos_chamados")


def _secret(chave: str) -> str | None:
    if st is not None:
        try:
            v = st.secrets.get(chave)
            if v and str(v).strip():
                return str(v).strip()
        except Exception:
            pass
        try:
            admin = st.secrets.get("admin", {}) or {}
            v = admin.get(chave) if hasattr(admin, "get") else None
            if v and str(v).strip():
                return str(v).strip()
        except Exception:
            pass
    v = os.getenv(chave)
    return v.strip() if v and str(v).strip() else None


def drive_configurado() -> bool:
    return bool(_secret("GOOGLE_DRIVE_FOLDER_ID") and _secret("GOOGLE_SERVICE_ACCOUNT_JSON"))


def _creds():
    raw = _secret("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        from google.oauth2 import service_account

        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
    except Exception as e:
        logger.error("Credencial Google inválida: %s", e)
        return None


def enviar_foto_drive(caminho_local: str, nome_remoto: str | None = None) -> dict[str, Any]:
    """
    Envia um arquivo local para a pasta do Drive.
    Retorna {ok, file_id, web_view_link, erro}.
    """
    if not drive_configurado():
        return {"ok": False, "erro": "Drive não configurado"}
    path = Path(caminho_local)
    if not path.is_file():
        return {"ok": False, "erro": f"Arquivo inexistente: {caminho_local}"}
    creds = _creds()
    if creds is None:
        return {"ok": False, "erro": "Falha ao montar credencial"}
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        folder = _secret("GOOGLE_DRIVE_FOLDER_ID")
        meta = {
            "name": nome_remoto or path.name,
            "parents": [folder],
        }
        media = MediaFileUpload(str(path), resumable=False)
        created = (
            service.files()
            .create(
                body=meta,
                media_body=media,
                fields="id, webViewLink, webContentLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        file_id = created.get("id")
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                supportsAllDrives=True,
            ).execute()
        except Exception as e:
            logger.warning("Não foi possível deixar o arquivo público: %s", e)
        link = created.get("webViewLink") or (f"https://drive.google.com/file/d/{file_id}/view")
        return {
            "ok": True,
            "file_id": file_id,
            "web_view_link": link,
            "web_content_link": created.get("webContentLink"),
        }
    except Exception as e:
        logger.exception("Upload Drive falhou")
        return {"ok": False, "erro": str(e)}


def sincronizar_foto_chamado(chamado: dict, campo_path: str, campo_url: str) -> dict:
    """Se o chamado tem arquivo local e ainda não tem URL, envia ao Drive."""
    local = chamado.get(campo_path)
    if not local or chamado.get(campo_url):
        return chamado
    res = enviar_foto_drive(str(local), nome_remoto=Path(str(local)).name)
    if res.get("ok") and res.get("web_view_link"):
        chamado[campo_url] = res["web_view_link"]
    return chamado
