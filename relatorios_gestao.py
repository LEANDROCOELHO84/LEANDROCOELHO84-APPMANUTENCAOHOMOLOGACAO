"""
Relatórios gerenciais que ajudam a otimizar a equipe de manutenção.
Todos retornam DataFrame pronto para tela / Excel.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


def _dt(s) -> pd.Timestamp | pd.NaT:
    return pd.to_datetime(s, errors="coerce")


def relatorio_sla_e_mttr(chamados: list[dict], sla_min: dict | None = None) -> pd.DataFrame:
    """
    Por chamado concluído: tempo de atendimento, se estourou SLA, MTTR.
    """
    sla_min = sla_min or {"Alta": 120, "Média": 480, "Baixa": 1440}
    rows = []
    for c in chamados or []:
        if str(c.get("status") or "") != "Concluído":
            continue
        ini = _dt(c.get("data_hora_abertura"))
        fim = _dt(c.get("data_hora_conclusao"))
        if pd.isna(ini) or pd.isna(fim):
            continue
        minutos = max(0.0, (fim - ini).total_seconds() / 60.0)
        pri = str(c.get("prioridade") or "Média")
        alvo = float(sla_min.get(pri, sla_min.get("Média", 480)) or 480)
        rows.append(
            {
                "OS": c.get("id"),
                "Equipamento": c.get("equipamento"),
                "Setor": c.get("setor"),
                "Prioridade": pri,
                "Técnico": c.get("executante"),
                "Abertura": ini,
                "Conclusão": fim,
                "Minutos": round(minutos, 1),
                "SLA alvo (min)": alvo,
                "No SLA": "Sim" if minutos <= alvo else "Não",
                "Estouro (min)": round(max(0.0, minutos - alvo), 1),
            }
        )
    return pd.DataFrame(rows)


def relatorio_produtividade_tecnico(chamados: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(chamados or [])
    if df.empty:
        return pd.DataFrame()
    df["status"] = df["status"].astype(str)
    g = (
        df.groupby(df["executante"].fillna("—").replace("", "—"))
        .agg(
            total=("id", "count"),
            concluidos=("status", lambda s: int((s == "Concluído").sum())),
            em_atendimento=("status", lambda s: int((s == "Em Atendimento").sum())),
            aguardando_peca=("status", lambda s: int((s == "Aguardando Peça").sum())),
            abertos=("status", lambda s: int((s == "Aberto").sum())),
        )
        .reset_index()
        .rename(columns={"executante": "Técnico"})
    )
    g["% concluídos"] = (g["concluidos"] / g["total"] * 100).round(1)
    return g.sort_values("concluidos", ascending=False)


def relatorio_backlog_aberto(chamados: list[dict]) -> pd.DataFrame:
    agora = datetime.now()
    rows = []
    for c in chamados or []:
        st = str(c.get("status") or "")
        if st == "Concluído":
            continue
        ini = _dt(c.get("data_hora_abertura"))
        idade = None
        if not pd.isna(ini):
            idade = round((agora - ini.to_pydatetime()).total_seconds() / 3600.0, 1)
        rows.append(
            {
                "OS": c.get("id"),
                "Status": st,
                "Prioridade": c.get("prioridade"),
                "Setor": c.get("setor"),
                "Equipamento": c.get("equipamento"),
                "Técnico": c.get("executante") or "—",
                "Idade (h)": idade,
                "Peça": c.get("peca_solicitada") or "",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    ordem = {"Alta": 0, "Média": 1, "Media": 1, "Baixa": 2}
    out["_o"] = out["Prioridade"].map(ordem).fillna(9)
    return out.sort_values(["_o", "Idade (h)"], ascending=[True, False]).drop(columns="_o")


def relatorio_preventivas_vencidas(equipamentos: list[dict]) -> pd.DataFrame:
    hoje = datetime.now().date()
    rows = []
    for e in equipamentos or []:
        prox = _dt(e.get("proxima_preventiva"))
        if pd.isna(prox):
            sit = "Sem data"
            dias = None
        else:
            d = prox.date() - hoje
            dias = d.days
            if dias < 0:
                sit = "Vencida"
            elif dias <= 15:
                sit = "Vence em 15 dias"
            else:
                sit = "No prazo"
        rows.append(
            {
                "ID": e.get("id"),
                "Equipamento": e.get("nome"),
                "Setor": e.get("setor"),
                "Última preventiva": e.get("ultima_preventiva"),
                "Próxima preventiva": e.get("proxima_preventiva"),
                "Dias": dias,
                "Situação": sit,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    ordem = {"Vencida": 0, "Vence em 15 dias": 1, "Sem data": 2, "No prazo": 3}
    out["_o"] = out["Situação"].map(ordem).fillna(9)
    return out.sort_values(["_o", "Dias"], ascending=[True, True]).drop(columns="_o")


def relatorio_compras_pendentes(compras: list[dict]) -> pd.DataFrame:
    rows = []
    for c in compras or []:
        st = str(c.get("status") or c.get("aprovado") or "")
        if st.lower() in {"recebido", "concluído", "concluido", "entregue"}:
            continue
        rows.append(
            {
                "ID": c.get("id"),
                "OS": c.get("chamado_id"),
                "Item": c.get("item_nome"),
                "Equipamento": c.get("equipamento"),
                "Prioridade": c.get("prioridade"),
                "Status": c.get("status"),
                "Aprovado": c.get("aprovado"),
                "Solicitação": c.get("data_solicitacao"),
                "Prazo": c.get("prazo_recebimento"),
                "Valor": c.get("valor_item"),
            }
        )
    return pd.DataFrame(rows)


def relatorio_almox_abaixo_minimo(itens: list[dict]) -> pd.DataFrame:
    rows = []
    for i in itens or []:
        try:
            qtd = float(i.get("quantidade") or 0)
            minimo = float(i.get("estoque_min") or 0)
        except (TypeError, ValueError):
            continue
        if minimo > 0 and qtd <= minimo:
            rows.append(
                {
                    "Código": i.get("codigo"),
                    "Item": i.get("nome"),
                    "Qtd": qtd,
                    "Mínimo": minimo,
                    "Local": i.get("localizacao"),
                    "Setor": i.get("setor"),
                    "Equipamento": i.get("equipamento_ref"),
                }
            )
    return pd.DataFrame(rows)


def relatorio_reincidencia_equipamento(chamados: list[dict], dias: int = 90) -> pd.DataFrame:
    corte = datetime.now() - timedelta(days=dias)
    cont: dict[str, int] = {}
    for c in chamados or []:
        ini = _dt(c.get("data_hora_abertura"))
        if pd.isna(ini) or ini.to_pydatetime() < corte:
            continue
        nome = str(c.get("equipamento") or "—")
        cont[nome] = cont.get(nome, 0) + 1
    rows = [{"Equipamento": k, f"OS em {dias} dias": v} for k, v in cont.items()]
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(f"OS em {dias} dias", ascending=False)


def relatorio_tempo_resposta(chamados: list[dict]) -> pd.DataFrame:
    """Abertura até o técnico iniciar. Mostra fila antes do reparo."""
    rows = []
    for c in chamados or []:
        ini = _dt(c.get("data_hora_abertura"))
        at = _dt(c.get("data_hora_inicio"))
        if pd.isna(ini) or pd.isna(at):
            continue
        horas = max(0.0, (at - ini).total_seconds() / 3600.0)
        rows.append(
            {
                "OS": c.get("id"),
                "Setor": c.get("setor"),
                "Equipamento": c.get("equipamento"),
                "Prioridade": c.get("prioridade"),
                "Técnico": c.get("executante") or "—",
                "Resposta (h)": round(horas, 2),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("Resposta (h)", ascending=False)


def relatorio_pecas_paradas(chamados: list[dict]) -> pd.DataFrame:
    """OS em Aguardando Peça, ordenadas pela parada mais longa."""
    agora = datetime.now()
    rows = []
    for c in chamados or []:
        if str(c.get("status") or "") != "Aguardando Peça":
            continue
        ref = _dt(c.get("data_solicitacao_peca") or c.get("data_hora_abertura"))
        horas = None
        if not pd.isna(ref):
            horas = round((agora - ref.to_pydatetime()).total_seconds() / 3600.0, 1)
        rows.append(
            {
                "OS": c.get("id"),
                "Setor": c.get("setor"),
                "Equipamento": c.get("equipamento"),
                "Peça": c.get("peca_solicitada") or "",
                "Técnico": c.get("executante") or "—",
                "Horas parada": horas,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("Horas parada", ascending=False)


def relatorio_carga_tecnico(chamados: list[dict]) -> pd.DataFrame:
    """WIP atual: o que cada técnico ainda tem na mão."""
    df = pd.DataFrame(chamados or [])
    if df.empty or "status" not in df.columns:
        return pd.DataFrame()
    ativos = df[df["status"].isin(["Aberto", "Em Atendimento", "Aguardando Peça"])].copy()
    if ativos.empty:
        return pd.DataFrame()
    ativos["Técnico"] = ativos["executante"].fillna("").replace("", "(sem técnico)")
    g = (
        ativos.groupby("Técnico")
        .agg(
            abertos=("status", lambda s: int((s == "Aberto").sum())),
            em_atendimento=("status", lambda s: int((s == "Em Atendimento").sum())),
            aguardando_peca=("status", lambda s: int((s == "Aguardando Peça").sum())),
            wip=("id", "count"),
        )
        .reset_index()
    )
    return g.sort_values("wip", ascending=False)


def relatorio_conformidade_preventiva(equipamentos: list[dict]) -> pd.DataFrame:
    """Equipamentos com preventiva vencida ou próxima (próximos 15 dias)."""
    agora = datetime.now().date()
    rows = []
    for e in equipamentos or []:
        prox = _dt(e.get("proxima_preventiva"))
        if pd.isna(prox):
            continue
        prox_d = prox.date()
        dias = (prox_d - agora).days
        status = "Vencida" if dias < 0 else ("Próxima" if dias <= 15 else "Em dia")
        if status == "Em dia":
            continue
        rows.append(
            {
                "Equipamento": e.get("nome"),
                "Setor": e.get("setor"),
                "Patrimônio": e.get("numero_patrimonio"),
                "Próxima": prox_d,
                "Dias": dias,
                "Status": status,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["Status", "Dias"])


def relatorio_top_reincidentes(chamados: list[dict], dias: int = 90, top: int = 10) -> pd.DataFrame:
    """Equipamentos com mais chamados no período (foco em reincidência)."""
    corte = datetime.now() - timedelta(days=dias)
    rows = []
    for c in chamados or []:
        ab = _dt(c.get("data_hora_abertura"))
        if pd.isna(ab) or ab < pd.Timestamp(corte):
            continue
        eq = str(c.get("equipamento") or "").strip()
        if not eq:
            continue
        rows.append({"Equipamento": eq, "Setor": c.get("setor"), "Status": c.get("status")})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby("Equipamento")
        .agg(
            total=("Status", "count"),
            concluidos=("Status", lambda s: int((s == "Concluído").sum())),
            setor=("Setor", "first"),
        )
        .reset_index()
        .sort_values("total", ascending=False)
        .head(top)
    )
    g["% concluídos"] = (g["concluidos"] / g["total"] * 100).round(1)
    return g


def relatorio_produtividade_periodo(chamados: list[dict], dias: int = 30) -> pd.DataFrame:
    """Produtividade por técnico no período: concluídos, MTTR médio, backlog atual."""
    corte = datetime.now() - timedelta(days=dias)
    rows = []
    for c in chamados or []:
        ab = _dt(c.get("data_hora_abertura"))
        fim = _dt(c.get("data_hora_conclusao"))
        ini = _dt(c.get("data_hora_inicio"))
        tec = str(c.get("executante") or "").strip() or "(sem técnico)"
        if not pd.isna(fim) and fim >= pd.Timestamp(corte) and str(c.get("status")) == "Concluído":
            mttr = None
            if not pd.isna(ini):
                mttr = (fim - ini).total_seconds() / 3600.0
            rows.append({"Técnico": tec, "tipo": "concluido", "mttr": mttr})
        elif str(c.get("status")) in ("Aberto", "Em Atendimento", "Aguardando Peça"):
            rows.append({"Técnico": tec, "tipo": "ativo", "mttr": None})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby("Técnico")
        .agg(
            concluidos=("tipo", lambda s: int((s == "concluido").sum())),
            ativos=("tipo", lambda s: int((s == "ativo").sum())),
            mttr_medio=("mttr", "mean"),
        )
        .reset_index()
    )
    g["mttr_medio"] = g["mttr_medio"].round(2)
    return g.sort_values("concluidos", ascending=False)


def relatorio_resposta_por_prioridade(chamados: list[dict]) -> pd.DataFrame:
    """Tempo médio de resposta (abertura → início) agrupado por prioridade."""
    rows = []
    for c in chamados or []:
        ini = _dt(c.get("data_hora_abertura"))
        at = _dt(c.get("data_hora_inicio"))
        if pd.isna(ini) or pd.isna(at):
            continue
        horas = max(0.0, (at - ini).total_seconds() / 3600.0)
        pri = str(c.get("prioridade") or "Média")
        rows.append({"Prioridade": pri, "Resposta (h)": horas})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby("Prioridade")
        .agg(
            qtd=("Resposta (h)", "count"),
            media_h=("Resposta (h)", "mean"),
            mediana_h=("Resposta (h)", "median"),
        )
        .reset_index()
    )
    g["media_h"] = g["media_h"].round(2)
    g["mediana_h"] = g["mediana_h"].round(2)
    return g.sort_values("media_h", ascending=False)


def relatorio_custo_por_equipamento(manutencoes: list[dict], dias: int = 90) -> pd.DataFrame:
    """Custo de peças e horas por equipamento no período (usa histórico de manutenções)."""
    corte = datetime.now() - timedelta(days=dias)
    rows = []
    for m in manutencoes or []:
        dt = _dt(m.get("data_manutencao"))
        if pd.isna(dt) or dt.to_pydatetime() < corte:
            continue
        eq = str(m.get("equipamento_nome") or m.get("equipamento") or "").strip()
        if not eq:
            continue
        custo = float(m.get("custo_pecas") or 0)
        horas = float(m.get("horas_homem") or 0)
        rows.append({"Equipamento": eq, "Custo": custo, "Horas": horas})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby("Equipamento")
        .agg(
            qtd=("Custo", "count"),
            custo_total=("Custo", "sum"),
            horas_total=("Horas", "sum"),
        )
        .reset_index()
    )
    g["custo_total"] = g["custo_total"].round(2)
    g["horas_total"] = g["horas_total"].round(1)
    return g.sort_values("custo_total", ascending=False)


def relatorio_first_time_fix(chamados: list[dict], dias: int = 90) -> pd.DataFrame:
    """Taxa de resolução na primeira visita (sem reincidência no mesmo equipamento em 30 dias)."""
    corte = datetime.now() - timedelta(days=dias)
    rows = []
    for c in chamados or []:
        if str(c.get("status") or "") != "Concluído":
            continue
        fim = _dt(c.get("data_hora_conclusao"))
        if pd.isna(fim) or fim.to_pydatetime() < corte:
            continue
        eq = str(c.get("equipamento") or "").strip()
        if not eq:
            continue
        # Check if there was another OS for same equipment within 30 days before this one
        ab = _dt(c.get("data_hora_abertura"))
        reincidente = False
        for other in chamados or []:
            if other.get("id") == c.get("id"):
                continue
            oeq = str(other.get("equipamento") or "").strip()
            if oeq != eq:
                continue
            oab = _dt(other.get("data_hora_abertura"))
            if pd.isna(oab) or pd.isna(ab):
                continue
            if 0 < (ab - oab).total_seconds() / 86400 <= 30:
                reincidente = True
                break
        rows.append(
            {"OS": c.get("id"), "Equipamento": eq, "Primeira vez": "Não" if reincidente else "Sim"}
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    total = len(df)
    ftf = int((df["Primeira vez"] == "Sim").sum())
    return pd.DataFrame(
        [
            {
                "Período (dias)": dias,
                "Concluídos": total,
                "First Time Fix": ftf,
                "% FTF": round(ftf / total * 100, 1) if total else 0,
            }
        ]
    )


def relatorio_tendencia_mttr_mensal(chamados: list[dict], meses: int = 6) -> pd.DataFrame:
    """MTTR médio por mês (últimos N meses)."""
    rows = []
    for c in chamados or []:
        if str(c.get("status") or "") != "Concluído":
            continue
        ini = _dt(c.get("data_hora_inicio"))
        fim = _dt(c.get("data_hora_conclusao"))
        if pd.isna(ini) or pd.isna(fim):
            continue
        horas = max(0.0, (fim - ini).total_seconds() / 3600.0)
        mes = fim.to_period("M").strftime("%Y-%m")
        rows.append({"Mês": mes, "MTTR (h)": horas})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = (
        df.groupby("Mês")
        .agg(qtd=("MTTR (h)", "count"), mttr_medio=("MTTR (h)", "mean"))
        .reset_index()
    )
    g["mttr_medio"] = g["mttr_medio"].round(2)
    return g.sort_values("Mês").tail(meses)


def relatorio_volume_mensal_setor(chamados: list[dict], meses: int = 6) -> pd.DataFrame:
    """Volume de chamados abertos por setor nos últimos N meses."""
    rows = []
    for c in chamados or []:
        ab = _dt(c.get("data_hora_abertura"))
        if pd.isna(ab):
            continue
        mes = ab.to_period("M").strftime("%Y-%m")
        setor = str(c.get("setor") or "—").strip() or "—"
        rows.append({"Mês": mes, "Setor": setor})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    g = df.groupby(["Mês", "Setor"]).size().reset_index(name="Qtd")
    return g.sort_values(["Mês", "Qtd"], ascending=[True, False]).groupby("Mês").head(10)
