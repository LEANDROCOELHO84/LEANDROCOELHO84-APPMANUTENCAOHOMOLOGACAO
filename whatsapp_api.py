"""
Integração WhatsApp Cloud API (Meta) — avisos de chamado concluído + histórico.

Secrets (topo do .streamlit/secrets.toml):

  WHATSAPP_TOKEN = "EAAB..."
  WHATSAPP_PHONE_ID = "123456789012345"
  WHATSAPP_GRAPH_VERSION = "v21.0"          # opcional
  WHATSAPP_DESTINO_PADRAO = "5511999999999" # opcional (gestor)
  WHATSAPP_AVISAR_SOLICITANTE = "1"         # opcional

Número no formato internacional, só dígitos (ex.: 5511999999999).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

try:
    import streamlit as st
except Exception:
    st = None

import logging

logger = logging.getLogger("chamados_app")


def _secret(chave: str, default: str | None = None) -> str | None:
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
    if v and str(v).strip():
        return str(v).strip()
    return default


def whatsapp_configurado() -> bool:
    return bool(_secret("WHATSAPP_TOKEN") and _secret("WHATSAPP_PHONE_ID"))


def diagnostico_whatsapp() -> dict[str, Any]:
    """Retorna status legível da configuração (para tela Admin)."""
    token = _secret("WHATSAPP_TOKEN")
    phone_id = _secret("WHATSAPP_PHONE_ID")
    api_url = _secret("WHATSAPP_API_URL")
    padrao = _secret("WHATSAPP_DESTINO_PADRAO") or _secret("WHATSAPP_DEFAULT_TO")
    avisar = _secret("WHATSAPP_AVISAR_SOLICITANTE", "1")
    return {
        "cloud_api": bool(token and phone_id),
        "token_presente": bool(token),
        "token_preview": (
            (token[:8] + "…") if token and len(token) > 8 else ("(vazio)" if not token else token)
        ),
        "phone_id": phone_id or "(vazio)",
        "gateway_url": bool(api_url),
        "destino_padrao": padrao or "(não definido)",
        "avisar_solicitante": avisar or "1",
        "ok": bool((token and phone_id) or api_url),
    }


def normalizar_telefone(raw: str | None) -> str | None:
    if not raw:
        return None
    dig = re.sub(r"\D+", "", str(raw))
    if not dig:
        return None
    if dig.startswith("00"):
        dig = dig[2:]
    if len(dig) == 11 or len(dig) == 10:
        dig = "55" + dig
    if len(dig) < 12:
        return None
    return dig


def _post_graph(payload: dict) -> tuple[bool, str]:
    token = _secret("WHATSAPP_TOKEN")
    phone_id = _secret("WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        return False, "WhatsApp não configurado (WHATSAPP_TOKEN / WHATSAPP_PHONE_ID)."
    ver = _secret("WHATSAPP_GRAPH_VERSION", "v21.0") or "v21.0"
    url = f"https://graph.facebook.com/{ver}/{phone_id}/messages"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, body
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        logger.error("WhatsApp HTTP %s: %s", e.code, err)
        return False, err
    except Exception as e:
        logger.exception("WhatsApp falhou: %s", e)
        return False, str(e)


def enviar_texto(destino: str, texto: str) -> tuple[bool, str]:
    fone = normalizar_telefone(destino)
    if not fone:
        return False, f"Telefone inválido: {destino}"
    payload = {
        "messaging_product": "whatsapp",
        "to": fone,
        "type": "text",
        "text": {"preview_url": False, "body": texto[:4096]},
    }
    return _post_graph(payload)


def montar_mensagem_conclusao(chamado: dict, historico: list | None = None) -> str:
    cid = chamado.get("id", "?")
    eq = chamado.get("equipamento") or "—"
    setor = chamado.get("setor") or "—"
    execu = chamado.get("executante") or "—"
    sol = (chamado.get("solucao_descricao") or "").strip()
    com = (chamado.get("comentario_conclusao") or "").strip()
    abert = chamado.get("data_hora_abertura") or "—"
    fim = chamado.get("data_hora_conclusao") or "—"
    pri = chamado.get("prioridade") or "—"
    foto = chamado.get("foto_url") or chamado.get("foto_solucao_url") or ""
    linhas = [
        f"✅ *Chamado Nº {cid} concluído*",
        f"Setor: {setor}",
        f"Equipamento: {eq}",
        f"Prioridade: {pri}",
        f"Técnico: {execu}",
        f"Aberto: {abert}",
        f"Concluído: {fim}",
        "",
        f"*Solução:* {sol or '—'}",
    ]
    if com:
        linhas.append(f"*Obs.:* {com}")
    if foto:
        linhas.append(f"Foto: {foto}")
    eventos = historico or chamado.get("historico") or []
    if eventos:
        linhas.append("")
        linhas.append("*Histórico:*")
        for ev in eventos[-6:]:
            if isinstance(ev, dict):
                quando = ev.get("data_hora") or ev.get("quando") or ""
                tipo = ev.get("tipo") or ev.get("evento") or ""
                det = (ev.get("detalhe") or ev.get("descricao") or "")[:120]
                linhas.append(f"• {quando} {tipo} {det}".strip())
            else:
                linhas.append(f"• {str(ev)[:140]}")
    linhas.append("")
    linhas.append("CRN DISTRIBUIDORA — Gestão de Manutenção")
    return "\n".join(linhas)[:4000]


def destinos_do_chamado(chamado: dict, equipe: list[dict] | None = None) -> list[str]:
    """
    Monta lista de destinos WhatsApp:
      1) WHATSAPP_DESTINO_PADRAO (gestor / coordenação)
      2) Solicitante — padrão LIGADO (desliga só com WHATSAPP_AVISAR_SOLICITANTE=0)
      3) Gestores/coordenadores da equipe + executante do chamado
    """
    destinos: list[str] = []
    padrao = _secret("WHATSAPP_DESTINO_PADRAO")
    if padrao:
        n = normalizar_telefone(padrao)
        if n:
            destinos.append(n)

    # Padrão: avisar solicitante automaticamente
    avisar_sol = str(_secret("WHATSAPP_AVISAR_SOLICITANTE", "1") or "1").strip().lower()
    if avisar_sol not in ("0", "false", "nao", "não", "off"):
        n = normalizar_telefone(
            chamado.get("contato_solicitante")
            or chamado.get("telefone_solicitante")
            or chamado.get("solicitante")
        )
        if n:
            destinos.append(n)

    nome_exec = (chamado.get("executante") or "").strip().lower()
    for m in equipe or []:
        if not m:
            continue
        contato = m.get("whatsapp") or m.get("contato")
        n = normalizar_telefone(contato)
        if not n:
            continue
        if (m.get("funcao") or "").lower() in ("gestor", "coordenador", "supervisor", "admin"):
            destinos.append(n)
        elif nome_exec and (m.get("nome") or "").strip().lower() == nome_exec:
            destinos.append(n)

    vistos = set()
    unicos = []
    for d in destinos:
        if d not in vistos:
            vistos.add(d)
            unicos.append(d)
    return unicos


def _log_integracao(destino: str, chamado_id: Any, ok: bool, detalhe: str) -> None:
    try:
        from database import get_local_connection, _ensure_schema
        from datetime import datetime

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
                "whatsapp_cloud",
                (destino or "")[:180],
                chamado_id,
                1 if ok else 0,
                (detalhe or "")[:500],
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("integracoes_log (whatsapp_api) | %s", e)


def notificar_chamado_concluido(chamado: dict, equipe: list[dict] | None = None) -> dict[str, Any]:
    """Envia histórico resumido do chamado concluído. Não levanta exceção."""
    cid = chamado.get("id")
    if not whatsapp_configurado():
        logger.warning(
            "WhatsApp NÃO configurado | OS=%s | defina WHATSAPP_TOKEN + WHATSAPP_PHONE_ID nos secrets",
            cid,
        )
        _log_integracao("", cid, False, "nao_configurado: faltam WHATSAPP_TOKEN/PHONE_ID")
        return {"ok": False, "motivo": "nao_configurado", "enviados": 0}
    if str(chamado.get("status") or "") != "Concluído":
        logger.info(
            "WhatsApp ignorado | OS=%s status=%s (não é Concluído)", cid, chamado.get("status")
        )
        return {"ok": False, "motivo": "status_nao_concluido", "enviados": 0}
    destinos = destinos_do_chamado(chamado, equipe)
    if not destinos:
        logger.warning(
            "WhatsApp sem destinos | OS=%s | contato_solicitante=%r destino_padrao=%r",
            cid,
            chamado.get("contato_solicitante"),
            _secret("WHATSAPP_DESTINO_PADRAO"),
        )
        _log_integracao(
            "",
            cid,
            False,
            "sem_destinos: preencha WhatsApp do solicitante ou WHATSAPP_DESTINO_PADRAO",
        )
        return {"ok": False, "motivo": "sem_destinos", "enviados": 0, "erros": []}
    texto = montar_mensagem_conclusao(chamado)
    enviados = 0
    erros = []
    logger.info("WhatsApp enviando | OS=%s destinos=%s", cid, destinos)
    for dest in destinos:
        ok, det = enviar_texto(dest, texto)
        _log_integracao(dest, cid, ok, det if not ok else "enviado")
        if ok:
            enviados += 1
            logger.info("WhatsApp OK | OS=%s → %s", cid, dest)
        else:
            erros.append({"destino": dest, "erro": det})
            logger.error("WhatsApp FALHOU | OS=%s → %s | %s", cid, dest, det[:200])
    return {
        "ok": enviados > 0,
        "enviados": enviados,
        "erros": erros,
        "destinos": destinos,
        "motivo": "ok" if enviados > 0 else "falha_envio",
    }
