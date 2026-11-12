"""
Integrações opcionais — WhatsApp + armazenamento de fotos na nuvem.

Google Fotos:
  A Library API oficial da Google é restrita a apps de consumidor e
  não serve bem para um sistema de manutenção. O caminho estável é
  enviar as fotos para uma pasta no Google Drive (que o Google Fotos
  pode espelhar, se o backup do Drive estiver ativo) via:
    1) Webhook (Google Apps Script) — recomendado no Streamlit Cloud
    2) Service Account (google-api-python-client), se instalado

WhatsApp:
    1) Cloud API oficial (Meta): WHATSAPP_TOKEN + WHATSAPP_PHONE_ID
    2) Gateway genérico (Evolution / Z-API / CallMeBot): WHATSAPP_API_URL
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("chamados_app")


def _secrets_get(chave: str) -> str | None:
    try:
        import streamlit as st

        v = st.secrets.get(chave)
        if v and str(v).strip():
            return str(v).strip()
        admin = st.secrets.get("admin", {}) or {}
        if hasattr(admin, "get"):
            v = admin.get(chave)
            if v and str(v).strip():
                return str(v).strip()
    except Exception:
        pass
    v = os.getenv(chave)
    return v.strip() if v and str(v).strip() else None


def _log_db(canal: str, destino: str, chamado_id: Any, ok: bool, detalhe: str) -> None:
    try:
        from database import get_local_connection, _ensure_schema

        conn = get_local_connection()
        _ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO integracoes_log (data_hora, canal, destino, chamado_id, ok, detalhe)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                canal,
                (destino or "")[:180],
                chamado_id,
                1 if ok else 0,
                (detalhe or "")[:500],
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("integracoes_log | %s", e)


def registrar_evento_chamado(
    chamado_id: Any, tipo: str, usuario: str = "", detalhe: str = ""
) -> None:
    try:
        from database import get_local_connection, _ensure_schema

        conn = get_local_connection()
        _ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chamado_eventos (chamado_id, data_hora, tipo, usuario, detalhe)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chamado_id,
                datetime.now().isoformat(timespec="seconds"),
                tipo,
                usuario or "",
                (detalhe or "")[:800],
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("registrar_evento_chamado | %s", e)


def registrar_foto_chamado(
    chamado_id: Any,
    tipo: str,
    path_local: str | None,
    url_remota: str | None = None,
    destino: str = "local",
) -> None:
    try:
        from database import get_local_connection, _ensure_schema

        conn = get_local_connection()
        _ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chamado_fotos (chamado_id, tipo, path_local, url_remota, destino, data_envio)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                chamado_id,
                tipo,
                path_local or "",
                url_remota or "",
                destino,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("registrar_foto_chamado | %s", e)


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------
def whatsapp_configurado() -> bool:
    return bool(
        (_secrets_get("WHATSAPP_TOKEN") and _secrets_get("WHATSAPP_PHONE_ID"))
        or _secrets_get("WHATSAPP_API_URL")
    )


def _limpar_telefone(raw: str) -> str:
    dig = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not dig:
        return ""
    if len(dig) == 11 and not dig.startswith("55"):
        dig = "55" + dig
    elif len(dig) == 10 and not dig.startswith("55"):
        dig = "55" + dig
    return dig


def enviar_whatsapp(telefone: str, mensagem: str, chamado_id: Any = None) -> bool:
    """
    Envia texto. Ordem:
      1) Cloud API Meta (WHATSAPP_TOKEN + WHATSAPP_PHONE_ID)
      2) URL genérica WHATSAPP_API_URL (Evolution/Z-API)
    """
    dest = _limpar_telefone(telefone)
    if not dest or not mensagem:
        return False

    token = _secrets_get("WHATSAPP_TOKEN")
    phone_id = _secrets_get("WHATSAPP_PHONE_ID")
    if token and phone_id:
        url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": dest,
            "type": "text",
            "text": {"preview_url": False, "body": mensagem[:4000]},
        }
        ok, det = _post_json(url, payload, headers={"Authorization": f"Bearer {token}"})
        _log_db("whatsapp_cloud", dest, chamado_id, ok, det)
        return ok

    api_url = _secrets_get("WHATSAPP_API_URL")
    if api_url:
        instance = _secrets_get("WHATSAPP_INSTANCE") or ""
        apikey = _secrets_get("WHATSAPP_APIKEY") or ""
        payload = {
            "number": dest,
            "text": mensagem[:4000],
            "instance": instance,
        }
        headers = {}
        if apikey:
            headers["apikey"] = apikey
            headers["Authorization"] = f"Bearer {apikey}"
        ok, det = _post_json(api_url, payload, headers=headers)
        _log_db("whatsapp_gateway", dest, chamado_id, ok, det)
        return ok

    logger.info("WhatsApp não configurado (secrets ausentes).")
    return False


def montar_mensagem_conclusao(chamado: dict, historico: list | None = None) -> str:
    cid = chamado.get("id")
    eq = chamado.get("equipamento") or "—"
    setor = chamado.get("setor") or "—"
    execu = chamado.get("executante") or "—"
    sol = (chamado.get("solucao_descricao") or chamado.get("comentario_conclusao") or "—").strip()
    if len(sol) > 280:
        sol = sol[:277] + "..."
    abertura = chamado.get("data_hora_abertura") or ""
    fim = chamado.get("data_hora_conclusao") or datetime.now().strftime("%Y-%m-%d %H:%M")
    linhas = [
        f"*OS #{cid} concluída*",
        f"Equipamento: {eq}",
        f"Setor: {setor}",
        f"Técnico: {execu}",
        f"Abertura: {abertura}",
        f"Conclusão: {fim}",
        f"Solução: {sol}",
    ]
    eventos = historico or chamado.get("historico") or []
    for ev in eventos[-5:]:
        if isinstance(ev, dict):
            linhas.append(
                f"- {ev.get('data_hora', '')} {ev.get('tipo', '')} {(ev.get('detalhe') or '')[:100]}".strip()
            )
    linhas.append("— Gestão de Chamados CRN")
    return "\n".join(linhas)[:4000]


def notificar_conclusao_whatsapp(chamado: dict, equipe: list | None = None) -> bool:
    """
    Envia para:
      - WHATSAPP_DEFAULT_TO / WHATSAPP_DESTINO_PADRAO (gestor)
      - contato do solicitante (padrão ligado)
      - contato do executante na tabela equipe, se houver
    """
    if not whatsapp_configurado():
        return False
    msg = montar_mensagem_conclusao(chamado)
    enviados = 0
    destinos: list[str] = []
    padrao = _secrets_get("WHATSAPP_DEFAULT_TO") or _secrets_get("WHATSAPP_DESTINO_PADRAO")
    if padrao:
        destinos.append(padrao)

    # Solicitante — padrão ligado
    avisar_sol = str(_secrets_get("WHATSAPP_AVISAR_SOLICITANTE") or "1").strip().lower()
    if avisar_sol not in ("0", "false", "nao", "não", "off"):
        sol_tel = chamado.get("contato_solicitante") or chamado.get("telefone_solicitante") or ""
        if sol_tel:
            destinos.append(str(sol_tel))

    nome_exec = str(chamado.get("executante") or "").strip().lower()
    for membro in equipe or []:
        if str(membro.get("nome") or "").strip().lower() == nome_exec:
            c = membro.get("contato") or ""
            if c:
                destinos.append(str(c))
    vistos = set()
    for d in destinos:
        chave = _limpar_telefone(d)
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        if enviar_whatsapp(d, msg, chamado.get("id")):
            enviados += 1
    return enviados > 0


# ---------------------------------------------------------------------------
# Fotos → Drive / webhook (espelho Google Fotos)
# ---------------------------------------------------------------------------
def fotos_nuvem_configurado() -> bool:
    return bool(
        _secrets_get("DRIVE_WEBHOOK_URL")
        or _secrets_get("GPHOTOS_WEBHOOK_URL")
        or _secrets_get("GOOGLE_DRIVE_FOLDER_ID")
    )


def enviar_foto_nuvem(
    path_local: str,
    chamado_id: Any,
    tipo: str = "abertura",
) -> str | None:
    """
    Envia JPEG local para o webhook configurado.
    Retorna URL remota se o serviço devolver {url: ...}.
    """
    if not path_local or not Path(path_local).is_file():
        return None
    webhook = _secrets_get("DRIVE_WEBHOOK_URL") or _secrets_get("GPHOTOS_WEBHOOK_URL")
    if not webhook:
        logger.info("Upload nuvem não configurado. Foto permanece em %s", path_local)
        registrar_foto_chamado(chamado_id, tipo, path_local, None, "local")
        return None
    try:
        data = Path(path_local).read_bytes()
        boundary = "----GestaoChamadosBoundary"
        filename = Path(path_local).name
        meta = json.dumps(
            {
                "chamado_id": chamado_id,
                "tipo": tipo,
                "filename": filename,
                "pasta": _secrets_get("GOOGLE_DRIVE_FOLDER_ID") or "chamados",
            }
        ).encode("utf-8")
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="meta"\r\n'
                f"Content-Type: application/json\r\n\r\n"
            ).encode("utf-8")
            + meta
            + (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: image/jpeg\r\n\r\n"
            ).encode("utf-8")
            + data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        req = urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        token = _secrets_get("DRIVE_WEBHOOK_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        url_remota = None
        try:
            parsed = json.loads(raw)
            url_remota = parsed.get("url") or parsed.get("webViewLink")
        except Exception:
            if raw.startswith("http"):
                url_remota = raw.strip()
        registrar_foto_chamado(chamado_id, tipo, path_local, url_remota, "drive")
        _log_db("fotos_nuvem", webhook[:80], chamado_id, True, url_remota or "ok")
        return url_remota
    except Exception as e:
        _log_db("fotos_nuvem", webhook[:80] if webhook else "", chamado_id, False, str(e)[:200])
        logger.warning("enviar_foto_nuvem | %s", e)
        registrar_foto_chamado(chamado_id, tipo, path_local, None, "local")
        return None


def apos_salvar_foto(path_local: str | None, chamado_id: Any, tipo: str) -> None:
    if not path_local:
        return
    registrar_foto_chamado(chamado_id, tipo, path_local, None, "local")
    if fotos_nuvem_configurado():
        try:
            enviar_foto_nuvem(path_local, chamado_id, tipo)
        except Exception as e:
            logger.warning("apos_salvar_foto | %s", e)


def apos_concluir_chamado(chamado: dict, equipe: list | None = None) -> None:
    registrar_evento_chamado(
        chamado.get("id"),
        "concluido",
        str(chamado.get("executante") or ""),
        chamado.get("solucao_descricao") or "",
    )
    foto_sol = chamado.get("foto_solucao_path")
    if foto_sol:
        apos_salvar_foto(foto_sol, chamado.get("id"), "solucao")
    try:
        notificar_conclusao_whatsapp(chamado, equipe)
    except Exception as e:
        logger.warning("whatsapp conclusao | %s", e)


def _post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[bool, str]:
    body = json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update({k: v for k, v in headers.items() if v})
    req = urllib.request.Request(url, data=body, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return 200 <= int(getattr(resp, "status", 200) or 200) < 300, raw[:300]
    except urllib.error.HTTPError as e:
        det = e.read().decode("utf-8", errors="replace")[:300] if e.fp else str(e)
        logger.warning("HTTP %s | %s", e.code, det)
        return False, det
    except Exception as e:
        return False, str(e)[:300]
