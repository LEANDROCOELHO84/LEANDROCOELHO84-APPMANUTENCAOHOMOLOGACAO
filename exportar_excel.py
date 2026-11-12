"""
Utilitários de exportação para Excel (.xlsx).
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd


def _df_limpo(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or (hasattr(df, "empty") and df.empty):
        return pd.DataFrame()
    out = df.copy()
    # evita colunas totalmente vazias de objetos não serializáveis
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].apply(
                lambda v: "" if v is None else (v if not isinstance(v, (dict, list)) else str(v))
            )
    return out


def dataframe_para_excel(
    dados: pd.DataFrame | dict[str, pd.DataFrame] | list[tuple[str, pd.DataFrame]],
    *,
    sheet_name: str = "Dados",
) -> bytes:
    """
    Converte DataFrame(s) em bytes de arquivo .xlsx.

    - Um DataFrame → uma aba
    - dict {nome_aba: df} ou lista [(nome, df)] → várias abas
    """
    buf = BytesIO()
    if isinstance(dados, pd.DataFrame):
        sheets: list[tuple[str, pd.DataFrame]] = [(sheet_name, _df_limpo(dados))]
    elif isinstance(dados, dict):
        sheets = [
            (str(k)[:31] or f"Aba{i}", _df_limpo(v)) for i, (k, v) in enumerate(dados.items())
        ]
    else:
        sheets = [(str(n)[:31] or f"Aba{i}", _df_limpo(d)) for i, (n, d) in enumerate(dados)]

    if not sheets:
        sheets = [("Dados", pd.DataFrame())]

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for nome, df in sheets:
            if df is None or df.empty:
                pd.DataFrame({"info": ["Sem registros"]}).to_excel(
                    writer, sheet_name=nome or "Vazio", index=False
                )
            else:
                df.to_excel(writer, sheet_name=nome or "Dados", index=False)
    buf.seek(0)
    return buf.read()


def nome_arquivo_excel(prefixo: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in prefixo.strip())
    return f"{safe}_{ts}.xlsx"


def historico_manutencao_para_df(historico: list[dict] | None) -> pd.DataFrame:
    """Monta DataFrame legível do histórico de manutenções (inclui checklist resumido)."""
    if not historico:
        return pd.DataFrame()
    rows = []
    for h in historico:
        ck = h.get("checklist_json") or ""
        rows.append(
            {
                "ID": h.get("id"),
                "Equipamento ID": h.get("equipamento_id"),
                "Equipamento": h.get("equipamento_nome"),
                "Tipo": h.get("tipo"),
                "Data": h.get("data_manutencao"),
                "Executante": h.get("executante"),
                "Descrição": h.get("descricao"),
                "Peças trocadas": h.get("pecas_trocadas"),
                "Custo peças (R$)": h.get("custo_pecas"),
                "Horas-homem": h.get("horas_homem"),
                "OS / Chamado": h.get("chamado_id"),
                "Observação": h.get("observacao"),
                "Checklist (JSON)": ck if isinstance(ck, str) else str(ck),
            }
        )
    return pd.DataFrame(rows)


def equipamentos_para_df(equipamentos: list[dict] | None) -> pd.DataFrame:
    if not equipamentos:
        return pd.DataFrame()
    rows = []
    for eq in equipamentos:
        rows.append(
            {
                "ID": eq.get("id"),
                "Nome": eq.get("nome"),
                "Marca": eq.get("marca"),
                "Modelo": eq.get("modelo"),
                "Patrimônio": eq.get("numero_patrimonio"),
                "Setor": eq.get("setor"),
                "Ano aquisição": eq.get("ano_aquisicao"),
                "Sazonalidade (meses)": eq.get("sazonalidade_meses"),
                "Última preventiva": eq.get("ultima_preventiva"),
                "Próxima preventiva": eq.get("proxima_preventiva"),
                "Silenciar até": eq.get("silenciar_ate"),
            }
        )
    return pd.DataFrame(rows)


def chamados_para_df(chamados: list[dict] | None) -> pd.DataFrame:
    if not chamados:
        return pd.DataFrame()
    df = pd.DataFrame(chamados)
    # ordena colunas comuns na frente, se existirem
    preferidas = [
        "id",
        "status",
        "prioridade",
        "setor",
        "equipamento",
        "solicitante",
        "executante",
        "data_hora_abertura",
        "data_hora_inicio",
        "data_hora_conclusao",
        "descricao",
        "solucao_descricao",
        "comentario_conclusao",
        "peca_solicitada",
        "peca_observacao",
    ]
    cols = [c for c in preferidas if c in df.columns] + [
        c for c in df.columns if c not in preferidas
    ]
    return df[cols]
