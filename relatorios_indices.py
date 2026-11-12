"""
Índices e relatórios de gestão — consultas que otimizam a equipe.

Todos os dataframes usam as tabelas já existentes. Funções puras
para o Dashboard / Excel / WhatsApp.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


def _ts(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return pd.NaT
    return pd.to_datetime(v, errors="coerce")


def preparar_chamados(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for col in ("data_hora_abertura", "data_hora_inicio", "data_hora_conclusao"):
        if col in out.columns:
            out[col] = out[col].map(_ts)
    agora = pd.Timestamp.now()
    if "data_hora_abertura" in out.columns:
        fim = out["data_hora_conclusao"].fillna(agora)
        out["idade_horas"] = (fim - out["data_hora_abertura"]).dt.total_seconds() / 3600.0
        out["idade_dias"] = out["idade_horas"] / 24.0
    if {"data_hora_inicio", "data_hora_conclusao"} <= set(out.columns):
        out["mttr_horas"] = (
            out["data_hora_conclusao"] - out["data_hora_inicio"]
        ).dt.total_seconds() / 3600.0
    return out


def kpis_periodo(df: pd.DataFrame, dias: int = 30) -> dict:
    base = preparar_chamados(df)
    if base.empty:
        return {
            "abertos": 0,
            "em_atendimento": 0,
            "aguardando_peca": 0,
            "concluidos": 0,
            "mttr_med_h": None,
            "idade_media_abertos_h": None,
            "reincidentes": 0,
        }
    corte = pd.Timestamp.now() - pd.Timedelta(days=dias)
    rec = base
    if "data_hora_abertura" in rec.columns:
        rec = rec[rec["data_hora_abertura"].isna() | (rec["data_hora_abertura"] >= corte)]
    status = rec["status"].fillna("") if "status" in rec.columns else pd.Series(dtype=str)
    concl = rec[status == "Concluído"] if not rec.empty else rec
    abertos = rec[status.isin(["Aberto", "Em Atendimento", "Aguardando Peça"])]
    mttr = concl["mttr_horas"].dropna() if "mttr_horas" in concl.columns else pd.Series(dtype=float)
    idade = (
        abertos["idade_horas"].dropna()
        if "idade_horas" in abertos.columns
        else pd.Series(dtype=float)
    )
    reincidente = 0
    if "equipamento" in rec.columns:
        vc = rec["equipamento"].dropna().astype(str)
        vc = vc[vc.str.strip() != ""]
        reincidente = int((vc.value_counts() >= 2).sum())
    return {
        "abertos": int((status == "Aberto").sum()),
        "em_atendimento": int((status == "Em Atendimento").sum()),
        "aguardando_peca": int((status == "Aguardando Peça").sum()),
        "concluidos": int((status == "Concluído").sum()),
        "mttr_med_h": float(mttr.median()) if len(mttr) else None,
        "idade_media_abertos_h": float(idade.mean()) if len(idade) else None,
        "reincidentes": reincidente,
        "periodo_dias": dias,
    }


def ranking_equipamentos(df: pd.DataFrame, top: int = 15) -> pd.DataFrame:
    base = preparar_chamados(df)
    if base.empty or "equipamento" not in base.columns:
        return pd.DataFrame()
    g = (
        base.groupby(base["equipamento"].fillna("—").astype(str))
        .agg(
            qtd=("id", "count") if "id" in base.columns else ("equipamento", "count"),
            concluidos=("status", lambda s: int((s == "Concluído").sum())),
            mttr_med_h=(
                ("mttr_horas", "median")
                if "mttr_horas" in base.columns
                else ("equipamento", "count")
            ),
        )
        .reset_index()
        .rename(columns={"equipamento": "equipamento"})
    )
    return g.sort_values("qtd", ascending=False).head(top)


def ranking_setores(df: pd.DataFrame) -> pd.DataFrame:
    base = preparar_chamados(df)
    if base.empty or "setor" not in base.columns:
        return pd.DataFrame()
    return (
        base.groupby(base["setor"].fillna("—").astype(str))
        .agg(
            qtd=("id", "count") if "id" in base.columns else ("setor", "count"),
            concluidos=("status", lambda s: int((s == "Concluído").sum())),
            idade_med_h=(
                ("idade_horas", "median") if "idade_horas" in base.columns else ("setor", "count")
            ),
        )
        .reset_index()
        .sort_values("qtd", ascending=False)
    )


def ranking_tecnicos(df: pd.DataFrame) -> pd.DataFrame:
    base = preparar_chamados(df)
    if base.empty or "executante" not in base.columns:
        return pd.DataFrame()
    concl = base[base.get("status", "") == "Concluído"] if "status" in base.columns else base
    if concl.empty:
        return pd.DataFrame()
    return (
        concl.groupby(concl["executante"].fillna("—").astype(str))
        .agg(
            concluidos=("id", "count") if "id" in concl.columns else ("executante", "count"),
            mttr_med_h=(
                ("mttr_horas", "median")
                if "mttr_horas" in concl.columns
                else ("executante", "count")
            ),
        )
        .reset_index()
        .sort_values("concluidos", ascending=False)
    )


def backlog_envelhecido(df: pd.DataFrame, horas: float = 48) -> pd.DataFrame:
    base = preparar_chamados(df)
    if base.empty:
        return pd.DataFrame()
    ativos = base[base["status"].isin(["Aberto", "Em Atendimento", "Aguardando Peça"])]
    if ativos.empty or "idade_horas" not in ativos.columns:
        return ativos
    return ativos[ativos["idade_horas"] >= horas].sort_values("idade_horas", ascending=False)


def preventivas_vencidas(eq: pd.DataFrame) -> pd.DataFrame:
    if eq is None or eq.empty or "proxima_preventiva" not in eq.columns:
        return pd.DataFrame()
    out = eq.copy()
    out["proxima_preventiva"] = pd.to_datetime(out["proxima_preventiva"], errors="coerce")
    hoje = pd.Timestamp.now().normalize()
    sil = None
    if "silenciar_ate" in out.columns:
        sil = pd.to_datetime(out["silenciar_ate"], errors="coerce")
    mask = out["proxima_preventiva"].notna() & (out["proxima_preventiva"] <= hoje)
    if sil is not None:
        mask = mask & (sil.isna() | (sil < hoje))
    return out.loc[mask].sort_values("proxima_preventiva")


def estoque_critico(itens: pd.DataFrame) -> pd.DataFrame:
    if itens is None or itens.empty:
        return pd.DataFrame()
    out = itens.copy()
    if "ativo" in out.columns:
        out = out[out["ativo"].fillna(1).astype(int) == 1]
    if not {"quantidade", "estoque_min"} <= set(out.columns):
        return pd.DataFrame()
    q = pd.to_numeric(out["quantidade"], errors="coerce").fillna(0)
    m = pd.to_numeric(out["estoque_min"], errors="coerce").fillna(0)
    return out.loc[q <= m].copy()


def compras_pendentes(compras: pd.DataFrame) -> pd.DataFrame:
    if compras is None or compras.empty:
        return pd.DataFrame()
    stt = (
        compras["status"].fillna("")
        if "status" in compras.columns
        else pd.Series("", index=compras.index)
    )
    return compras[
        ~stt.str.lower().isin(["recebido", "cancelado", "concluído", "concluido"])
    ].copy()
