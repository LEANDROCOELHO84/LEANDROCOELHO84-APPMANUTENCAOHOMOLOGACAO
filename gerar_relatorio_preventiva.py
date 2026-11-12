"""
Gera PDF de Relatório de Manutenção Preventiva — tema CRN DISTRIBUIDORA.

Melhorias:
- Checklist individualizado por tipo de equipamento (compressor, envasadora,
  misturador, empilhadeira, etc.)
- Layout e branding CRN (logo, cores vermelho/preto, rodapé institucional)
- API compatível com o app (CHECKLIST_ITENS, gerar_pdf_preventiva,
  montar_checklist_json, parse_checklist_json, checklist_para_equipamento)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Checklists por tipo de equipamento
# Cada item: (texto, marcado_SIM_por_padrao)
# ---------------------------------------------------------------------------


def _ck(*items: tuple[str, bool]) -> list[tuple[str, bool]]:
    return list(items)


CHECKLISTS: dict[str, list[tuple[str, bool]]] = {
    "compressora": _ck(
        ("VERIFICOU O NÍVEL DE ÓLEO DO COMPRESSOR ?", True),
        ("VERIFICOU PRESSÃO DE TRABALHO E VÁLVULAS DE SEGURANÇA ?", True),
        ("FEZ A LIMPEZA DO FILTRO DE AR / ADMISSÃO ?", True),
        ("FEZ A LIMPEZA DO RADIADOR / TROCADOR DE CALOR ?", True),
        ("VERIFICOU CORREIAS, POLIAS E TENSÃO ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS E TERMINAIS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU VAZAMENTOS DE AR OU ÓLEO ?", False),
        ("OS MANCAIS E COXINS ESTÃO EM BOM ESTADO ?", True),
        ("VERIFICOU O FUNCIONAMENTO DO PRESSOSTATO ?", True),
        ("FEZ A DRENAGEM DO CONDENSADO / PURGA ?", True),
        ("POSSUI FOCOS DE CORROSÃO OU OXIDAÇÃO ?", False),
        ("OS ISOLANTES E MANGUEIRAS ESTÃO DETERIORADOS ?", False),
    ),
    "seladora": _ck(
        ("VERIFICOU A TEMPERATURA E POTÊNCIA DE SELAGEM ?", True),
        ("FEZ A LIMPEZA DAS MANDÍBULAS / BOBINA DE INDUÇÃO ?", True),
        ("VERIFICOU O ALINHAMENTO E PRESSÃO DE SELAGEM ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU O SISTEMA DE RESFRIAMENTO ?", True),
        ("AS PARTES MÓVEIS ESTÃO LUBRIFICADAS ?", True),
        ("VERIFICOU A QUALIDADE DO SELO (TESTE) ?", True),
        ("OS SUPORTES E FIXAÇÕES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E ISOLANTES ESTÃO DETERIORADOS ?", False),
    ),
    "rotuladeira": _ck(
        ("VERIFICOU O ALINHAMENTO DO APLICADOR DE RÓTULOS ?", True),
        ("FEZ A LIMPEZA DOS ROLOS E GUIA DE RÓTULO ?", True),
        ("OS SENSORES ÓPTICOS ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU A TENSÃO E AVANÇO DO RÓTULO ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU TRAVAMENTOS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU CILINDROS PNEUMÁTICOS (SE HOUVER) ?", True),
        ("AS CORREIAS E ROLAMENTOS ESTÃO EM BOM ESTADO ?", True),
        ("VERIFICOU A QUALIDADE DA APLICAÇÃO (TESTE) ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "codificadora": _ck(
        ("VERIFICOU O NÍVEL E QUALIDADE DA TINTA / SOLVENTE ?", True),
        ("FEZ A LIMPEZA DO CABEÇOTE DE IMPRESSÃO ?", True),
        ("OS SENSORES E ENCODER ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU A QUALIDADE DA IMPRESSÃO (TESTE) ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA FALHAS DE IMPRESSÃO OU BORRÕES ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU O SISTEMA DE RECIRCULAÇÃO DE TINTA ?", True),
        ("OS FILTROS DE TINTA ESTÃO LIMPOS / TROCADOS ?", True),
        ("VERIFICOU ALINHAMENTO DO CABEÇOTE ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI VAZAMENTOS DE TINTA ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "fechadora": _ck(
        ("VERIFICOU O ALINHAMENTO DA FITA / SISTEMA DE FECHAMENTO ?", True),
        ("FEZ A LIMPEZA DOS ROLOS E GUIAS ?", True),
        ("OS SENSORES ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU A TENSÃO E CORTE DA FITA ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU TRAVAMENTOS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU CILINDROS E SISTEMA PNEUMÁTICO ?", True),
        ("AS PARTES MÓVEIS ESTÃO LUBRIFICADAS ?", True),
        ("VERIFICOU A QUALIDADE DO FECHAMENTO (TESTE) ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "tunel": _ck(
        ("VERIFICOU A TEMPERATURA E FLUXO DE VAPOR / CALOR ?", True),
        ("FEZ A LIMPEZA INTERNA DO TÚNEL ?", True),
        ("OS SENSORES E TERMOSTATOS ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU A VELOCIDADE DA ESTEIRA ?", True),
        ("FEZ A LIMPEZA DE FILTROS E ENTRADAS DE AR ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU RESISTÊNCIAS / SISTEMA DE AQUECIMENTO ?", True),
        ("AS CORREIAS E ROLOS ESTÃO EM BOM ESTADO ?", True),
        ("VERIFICOU A QUALIDADE DO ENCOLHIMENTO (TESTE) ?", True),
        ("OS SUPORTES E ISOLANTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("ISOLANTES TÉRMICOS ESTÃO DETERIORADOS ?", False),
    ),
    "envolvedora": _ck(
        ("VERIFICOU O ALINHAMENTO E TENSÃO DO FILME STRETCH ?", True),
        ("FEZ A LIMPEZA DOS ROLOS E BRAÇO ROTATIVO ?", True),
        ("OS SENSORES E FIM DE CURSO ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU A ROTAÇÃO E PRENSAGEM ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU FREIOS E EMBREAGEM (SE HOUVER) ?", True),
        ("AS CORREIAS, CORRENTES E MANCAIS ESTÃO OK ?", True),
        ("VERIFICOU A QUALIDADE DO ENVOLVIMENTO (TESTE) ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "encapsuladora": _ck(
        ("VERIFICOU A DOSAGEM E PRECISÃO DO ENCHIMENTO ?", True),
        ("FEZ A LIMPEZA DAS MATRIZES E FUNIS ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU O SISTEMA DE VÁCUO / COMPRESSÃO ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU TRAVAMENTOS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU PARTES MÓVEIS E LUBRIFICAÇÃO ?", True),
        ("AS GUIAS E TRILHOS ESTÃO EM BOM ESTADO ?", True),
        ("VERIFICOU A QUALIDADE DAS CÁPSULAS (TESTE) ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "envasadora": _ck(
        ("VERIFICOU A PRECISÃO DE DOSAGEM / VOLUME ?", True),
        ("FEZ A LIMPEZA DE BICOS, FUNIS E TANQUES ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU O SISTEMA PNEUMÁTICO / BOMBAS ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA VAZAMENTOS DE PRODUTO ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU VÁLVULAS E CILINDROS ?", True),
        ("AS PARTES MÓVEIS ESTÃO LUBRIFICADAS ?", True),
        ("VERIFICOU A QUALIDADE DO ENVASE (TESTE) ?", True),
        ("OS SUPORTES E FIXAÇÕES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("MANGUEIRAS E VEDAÇÕES ESTÃO DETERIORADAS ?", False),
    ),
    "portao": _ck(
        ("VERIFICOU O FUNCIONAMENTO DA ABERTURA/FECHAMENTO ?", True),
        ("FEZ A LIMPEZA DE TRILHOS E GUIAS ?", True),
        ("OS SENSORES DE SEGURANÇA ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU MOTORES E REDUTORES ?", True),
        ("FEZ A LUBRIFICAÇÃO DE PARTES MÓVEIS ?", True),
        ("APRESENTA RUÍDOS OU TRAVAMENTOS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU FIM DE CURSO E FOTOCÉLULAS ?", True),
        ("AS CORRENTES, CABOS E MOLAS ESTÃO OK ?", True),
        ("VERIFICOU TRAVAS E SISTEMA DE SEGURANÇA ?", True),
        ("OS SUPORTES E FIXAÇÕES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "computador": _ck(
        ("VERIFICOU O FUNCIONAMENTO GERAL DO EQUIPAMENTO ?", True),
        ("FEZ A LIMPEZA EXTERNA E DE VENTILAÇÃO ?", True),
        ("OS PERIFÉRICOS ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU CONEXÕES DE REDE E ENERGIA ?", True),
        ("FEZ A LIMPEZA INTERNA (PÓ / VENTILADORES) ?", True),
        ("APRESENTA SUPERAQUECIMENTO OU RUÍDOS ?", False),
        ("VERIFICOU ESTABILIZADOR / NOBREAK (SE HOUVER) ?", True),
        ("VERIFICOU ATUALIZAÇÕES E ANTIVÍRUS ?", True),
        ("OS CABOS ESTÃO EM BOM ESTADO ?", True),
        ("VERIFICOU ESPAÇO EM DISCO E DESEMPENHO ?", True),
        ("TECLADO, MOUSE E MONITOR OK ?", True),
        ("A FIXAÇÃO / SUPORTE ESTÁ FIRME ?", True),
        ("POSSUI DANOS FÍSICOS VISÍVEIS ?", False),
        ("CONECTORES ESTÃO OXIDADOS OU FOLGADOS ?", False),
    ),
    "veiculo": _ck(
        ("VERIFICOU NÍVEL DE ÓLEO, ÁGUA E FLUIDOS ?", True),
        ("VERIFICOU PNEUS (PRESSÃO E ESTADO) ?", True),
        ("OS FREIOS E LUZES ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU BATERIA E SISTEMA ELÉTRICO ?", True),
        ("FEZ A LIMPEZA EXTERNA E INTERNA ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("VERIFICOU EXTINTOR E ITENS DE SEGURANÇA ?", True),
        ("VERIFICOU DOCUMENTAÇÃO E LICENCIAMENTO ?", True),
        ("VERIFICOU SUSPENSÃO E DIREÇÃO ?", True),
        ("OS CINTOS E RETROVISORES ESTÃO OK ?", True),
        ("VERIFICOU VAZAMENTOS (ÓLEO / COMBUSTÍVEL) ?", False),
        ("O ESTEPE E FERRAMENTAS ESTÃO PRESENTES ?", True),
        ("POSSUI FOCOS DE CORROSÃO / FERRUGEM ?", False),
        ("PALHETAS E LIMPADORES ESTÃO DETERIORADOS ?", False),
    ),
    "empilhadeira": _ck(
        ("VERIFICOU NÍVEL DE ÓLEO HIDRÁULICO E MOTOR ?", True),
        ("VERIFICOU GARFOS, CORRENTES E MASTRO ?", True),
        ("OS FREIOS E FREIO DE ESTACIONAMENTO OK ?", True),
        ("VERIFICOU BATERIA / COMBUSTÍVEL ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU VAZAMENTOS ?", False),
        ("VERIFICOU RODAS, PNEUS E ROLAMENTOS ?", True),
        ("VERIFICOU SISTEMA ELÉTRICO E LUZES ?", True),
        ("VERIFICOU CILINDROS HIDRÁULICOS ?", True),
        ("OS CONTROLES E ALAVANCAS ESTÃO OK ?", True),
        ("VERIFICOU EXTINTOR E ITENS DE SEGURANÇA ?", True),
        ("A ESTRUTURA E SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("MANGUEIRAS HIDRÁULICAS ESTÃO DETERIORADAS ?", False),
    ),
    "cameras": _ck(
        ("VERIFICOU A IMAGEM DE TODAS AS CÂMERAS ?", True),
        ("FEZ A LIMPEZA DAS LENTES ?", True),
        ("OS SENSORES / IV NOTURNO ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU GRAVAÇÃO E ARMAZENAMENTO ?", True),
        ("VERIFICOU CONEXÕES DE REDE E ENERGIA ?", True),
        ("APRESENTA FALHAS DE IMAGEM OU ÁUDIO ?", False),
        ("VERIFICOU O DVR / NVR E HD ?", True),
        ("VERIFICOU ÂNGULOS E FIXAÇÃO DAS CÂMERAS ?", True),
        ("OS CABOS ESTÃO EM BOM ESTADO ?", True),
        ("VERIFICOU ACESSO REMOTO (SE HOUVER) ?", True),
        ("A ILUMINAÇÃO DO AMBIENTE É ADEQUADA ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI DANOS FÍSICOS NAS CÂMERAS ?", False),
        ("CONECTORES ESTÃO OXIDADOS ?", False),
    ),
    "secadora": _ck(
        ("VERIFICOU O PONTO DE ORVALHO / UMIDADE DE SAÍDA ?", True),
        ("FEZ A LIMPEZA DE FILTROS E DRENOS ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU PRESSÃO DE ENTRADA E SAÍDA ?", True),
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("APRESENTA VAZAMENTOS DE AR ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU ELEMENTO SECADOR / DESSECANTE ?", True),
        ("AS VÁLVULAS E PURGADORES ESTÃO OK ?", True),
        ("VERIFICOU O FUNCIONAMENTO DO DRENO AUTOMÁTICO ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("MANGUEIRAS E VEDAÇÕES ESTÃO DETERIORADAS ?", False),
    ),
    "exaustor": _ck(
        ("FEZ A LIMPEZA DO GABINETE / CARENAGEM ?", True),
        ("FEZ A LIMPEZA DAS GRADES E ENTRADAS DE AR ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("FEZ A LIMPEZA DOS DUTOS E CONEXÕES ?", True),
        ("FEZ A LIMPEZA DO MOTOR E VENTILADOR / PÁS ?", True),
        ("APRESENTA RUÍDOS E VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DOS TERMINAIS ELÉTRICOS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU PRESSÃO / VAZÃO DE TRABALHO ?", True),
        ("AS CORREIAS, POLIAS E MANCAIS ESTÃO OK ?", True),
        ("OS SUPORTES E COXINS ESTÃO EM BOM ESTADO ?", True),
        ("FEZ A LIMPEZA DAS PÁS / HÉLICE ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("ISOLANTES / VEDAÇÕES ESTÃO DETERIORADOS ?", False),
    ),
    "misturador": _ck(
        ("VERIFICOU O FUNCIONAMENTO DO AGITADOR / HÉLICE ?", True),
        ("FEZ A LIMPEZA INTERNA DO TANQUE / CUBA ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("VERIFICOU VEDAÇÕES E GAXETAS ?", True),
        ("FEZ A LIMPEZA EXTERNA DO EQUIPAMENTO ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU O REDUTOR / MOTOR ?", True),
        ("AS CORREIAS, CORRENTES E MANCAIS ESTÃO OK ?", True),
        ("VERIFICOU VÁLVULAS DE DESCARGA ?", True),
        ("OS SUPORTES E ESTRUTURA ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("VEDAÇÕES ESTÃO DETERIORADAS OU VAZANDO ?", False),
    ),
    "elevador": _ck(
        ("VERIFICOU O FUNCIONAMENTO DE SUBIDA/DESCIDA ?", True),
        ("FEZ A LIMPEZA DE TRILHOS E GUIAS ?", True),
        ("OS SENSORES E FIM DE CURSO ESTÃO OK ?", True),
        ("VERIFICOU CABOS DE AÇO / CORRENTES ?", True),
        ("FEZ A LUBRIFICAÇÃO DE PARTES MÓVEIS ?", True),
        ("APRESENTA RUÍDOS OU TRAVAMENTOS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU FREIOS E SISTEMA DE SEGURANÇA ?", True),
        ("OS ROLAMENTOS E POLIAS ESTÃO OK ?", True),
        ("VERIFICOU A CAPACIDADE / SOBRECARGA ?", True),
        ("A ESTRUTURA E SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
    "geral": _ck(
        ("FEZ A LIMPEZA GERAL DO EQUIPAMENTO ?", True),
        ("VERIFICOU O FUNCIONAMENTO GERAL ?", True),
        ("OS SENSORES E CONTROLES ESTÃO FUNCIONANDO ?", True),
        ("FEZ A LUBRIFICAÇÃO DAS PARTES MÓVEIS ?", True),
        ("VERIFICOU FIXAÇÕES E SUPORTES ?", True),
        ("APRESENTA RUÍDOS OU VIBRAÇÕES ANORMAIS ?", False),
        ("FEZ O REAPERTO DE CONEXÕES ELÉTRICAS ?", True),
        ("VERIFICOU CORRENTE, TENSÃO E DISJUNTOR ?", True),
        ("VERIFICOU PARTES MECÂNICAS E DESGASTE ?", True),
        ("OS COMPONENTES ESTÃO EM BOM ESTADO ?", True),
        ("REALIZOU TESTE DE FUNCIONAMENTO ?", True),
        ("OS SUPORTES ESTÃO FIRMES ?", True),
        ("POSSUI FOCOS DE CORROSÃO ?", False),
        ("CABOS E CONEXÕES ESTÃO DETERIORADOS ?", False),
    ),
}

# Labels amigáveis por chave
TIPO_LABELS: dict[str, str] = {
    "compressora": "COMPRESSOR / COMPRESSORA",
    "seladora": "SELADORA DE INDUÇÃO",
    "rotuladeira": "ROTULADEIRA",
    "codificadora": "CODIFICADORA",
    "fechadora": "FECHADORA DE CAIXA",
    "tunel": "TÚNEL DE ENCOLHIMENTO",
    "envolvedora": "ENVOLVEDORA DE PALLET",
    "encapsuladora": "ENCAPSULADORA",
    "envasadora": "ENVASADORA",
    "portao": "PORTÃO / PORTA",
    "computador": "COMPUTADOR / NOTEBOOK",
    "veiculo": "VEÍCULO",
    "empilhadeira": "EMPILHADEIRA",
    "cameras": "CÂMERAS / CFTV",
    "secadora": "SECADORA DE AR",
    "exaustor": "EXAUSTOR",
    "misturador": "MISTURADOR",
    "elevador": "ELEVADOR DE CARGA",
    "geral": "EQUIPAMENTO",
}

# Compatibilidade: checklist padrão (geral) exportado como CHECKLIST_ITENS
CHECKLIST_ITENS: list[tuple[str, bool]] = CHECKLISTS["geral"]


def detectar_tipo_equipamento(nome: str | None) -> str:
    """Retorna a chave do checklist com base no nome do equipamento."""
    n = (nome or "").lower()
    if "compressora" in n or ("compressor" in n and "ar" in n) or "compressor de ar" in n:
        return "compressora"
    if "seladora" in n:
        return "seladora"
    if "rotuladeira" in n:
        return "rotuladeira"
    if "codificadora" in n:
        return "codificadora"
    if "fechadora" in n or "fita gomada" in n:
        return "fechadora"
    if "tunel" in n or "túnel" in n or "encolhimento" in n:
        return "tunel"
    if "stresh" in n or "stretch" in n or "envolvedora" in n or "pallet" in n:
        return "envolvedora"
    if "encapsuladora" in n:
        return "encapsuladora"
    if "envasadora" in n:
        return "envasadora"
    if "portao" in n or "portão" in n or "porta de vidro" in n or n.startswith("porta "):
        return "portao"
    if "computador" in n or "notebook" in n:
        return "computador"
    if any(x in n for x in ("veiculo", "veículo", "doblo", "transiti", "caminhao", "caminhão")):
        return "veiculo"
    if "empilhadeira" in n:
        return "empilhadeira"
    if "camera" in n or "câmera" in n or "cameras" in n:
        return "cameras"
    if "secadora" in n:
        return "secadora"
    if "exaustor" in n:
        return "exaustor"
    if "misturador" in n:
        return "misturador"
    if "elevador" in n:
        return "elevador"
    return "geral"


def checklist_para_equipamento(nome: str | None) -> list[tuple[str, bool]]:
    """Retorna a lista de itens de checklist adequada ao equipamento."""
    chave = detectar_tipo_equipamento(nome)
    return list(CHECKLISTS.get(chave, CHECKLISTS["geral"]))


def label_tipo_equipamento(nome: str | None) -> str:
    """Label amigável do tipo (ex.: ENVASADORA)."""
    chave = detectar_tipo_equipamento(nome)
    return TIPO_LABELS.get(chave, "EQUIPAMENTO")


def _safe(val: Any, default: str = "") -> str:
    """Converte qualquer valor para texto seguro (None, NaN, float → string)."""
    if val is None:
        return default
    try:
        if isinstance(val, float):
            import math

            if math.isnan(val) or math.isinf(val):
                return default
        try:
            import pandas as pd

            if pd.isna(val):
                return default
        except Exception:
            pass
    except Exception:
        pass
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return default
    return s


def _parse_data(data_str: str | None) -> datetime:
    if not data_str:
        return datetime.now()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%y",
    ):
        try:
            return datetime.strptime(str(data_str)[:19], fmt)
        except ValueError:
            continue
    return datetime.now()


def parse_checklist_json(raw: str | None) -> dict:
    """
    Retorna dict no formato:
      { texto_item: {"sim": bool, "obs": str} }
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return {}
        out = {}
        for k, v in data.items():
            if isinstance(v, dict):
                out[str(k)] = {
                    "sim": bool(v.get("sim", True)),
                    "obs": _safe(v.get("obs")),
                }
            elif isinstance(v, bool):
                out[str(k)] = {"sim": v, "obs": ""}
            else:
                out[str(k)] = {"sim": True, "obs": _safe(v)}
        return out
    except Exception:
        return {}


def montar_checklist_json(itens: list[dict]) -> str:
    """
    itens: lista de {"texto": str, "sim": bool, "obs": str}
    """
    d = {}
    for it in itens:
        texto = it.get("texto") or ""
        if not texto:
            continue
        d[texto] = {"sim": bool(it.get("sim", True)), "obs": _safe(it.get("obs"))}
    return json.dumps(d, ensure_ascii=False)


def _logo_path() -> str | None:
    """Procura logo_crn.png ao lado deste módulo ou em caminhos comuns."""
    base = Path(__file__).resolve().parent
    candidates = [
        base / "logo_crn.png",
        base / "LOGO CRN.png",
        base / "assets" / "logo_crn.png",
        Path("/home/workdir/artifacts/app_versao_revisada/logo_crn.png"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def gerar_pdf_preventiva(
    equipamento: dict,
    manutencao: dict | None = None,
    *,
    tipo_aparelho: str = "",
    capacidade: str = "",
    voltagem: str = "",
    cor: str = "",
    local_instalado: str | None = None,
    titulo_cliente: str = "CRN NUTRITON",
    observacoes_gerais: str = "",
    checklist_overrides: dict[str, bool] | None = None,
    checklist_obs: dict[str, str] | None = None,
    checklist_data: dict | None = None,
) -> bytes:
    """
    Gera o PDF do Relatório de Manutenção Preventiva (tema CRN).

    equipamento: dict do cadastro (nome, marca, modelo, setor, ...)
    manutencao: registro do histórico (data_manutencao, executante, observacao, checklist_json ...)

    O checklist é escolhido automaticamente pelo nome do equipamento.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError as e:
        raise ImportError(
            "Biblioteca reportlab não instalada. Execute: pip install reportlab"
        ) from e

    # Cores CRN
    CRN_RED = colors.Color(0.89, 0.02, 0.08)
    CRN_BLACK = colors.Color(0.08, 0.08, 0.08)
    CRN_GRAY = colors.Color(0.25, 0.25, 0.25)
    CRN_LIGHT = colors.Color(0.97, 0.95, 0.95)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    margin = 12 * mm
    usable_w = W - 2 * margin

    # ---------- dados ----------
    nome_eq = _safe(equipamento.get("nome") or equipamento.get("equipamento_nome"))
    marca = _safe(equipamento.get("marca"))
    modelo = _safe(equipamento.get("modelo"))
    setor = _safe(local_instalado or equipamento.get("setor"), "—")
    patrimonio = _safe(
        equipamento.get("numero_patrimonio")
        or equipamento.get("patrimonio")
        or equipamento.get("Patrimônio")
    )

    tipo_label = (tipo_aparelho or "").strip().upper() or label_tipo_equipamento(nome_eq)
    checklist_itens = checklist_para_equipamento(nome_eq)

    # checklist a partir do registro ou parâmetros
    ck_from_reg: dict = {}
    obs_extra = _safe(observacoes_gerais)
    if manutencao:
        data_man = _parse_data(manutencao.get("data_manutencao"))
        executante = _safe(manutencao.get("executante"))
        obs = _safe(manutencao.get("observacao")) or _safe(manutencao.get("descricao"))
        if obs_extra:
            obs = (obs + "\n" + obs_extra).strip() if obs else obs_extra
        ck_from_reg = parse_checklist_json(manutencao.get("checklist_json"))
    else:
        data_man = datetime.now()
        executante = ""
        obs = obs_extra

    # merge: checklist_data > overrides/obs > registro > padrão do tipo
    resolved: dict[str, dict] = {}
    for texto, padrao_sim in checklist_itens:
        sim = padrao_sim
        item_obs = ""
        if texto in ck_from_reg:
            sim = ck_from_reg[texto].get("sim", padrao_sim)
            item_obs = ck_from_reg[texto].get("obs", "")
        if checklist_overrides and texto in checklist_overrides:
            sim = bool(checklist_overrides[texto])
        if checklist_obs and texto in checklist_obs:
            item_obs = _safe(checklist_obs[texto])
        if checklist_data and texto in checklist_data:
            v = checklist_data[texto]
            if isinstance(v, dict):
                sim = bool(v.get("sim", sim))
                item_obs = _safe(v.get("obs", item_obs))
            elif isinstance(v, bool):
                sim = v
        resolved[texto] = {"sim": sim, "obs": item_obs}

    meses = int(equipamento.get("sazonalidade_meses") or equipamento.get("sazonalidade") or 6)
    prox = data_man + timedelta(days=meses * 30)
    data_str = data_man.strftime("%d/%m/%Y")
    prox_str = prox.strftime("%d/%m/%Y")

    capacidade_txt = capacidade or _safe(modelo)

    # ---------- CABEÇALHO CRN ----------
    y = H - margin - 1 * mm
    c.setFillColor(CRN_RED)
    c.rect(margin, y - 18 * mm, usable_w, 18 * mm, stroke=0, fill=1)

    logo_file = _logo_path()
    logo_w, logo_h = 38 * mm, 13 * mm
    c.setFillColor(colors.white)
    c.roundRect(
        margin + 2 * mm, y - 16 * mm, logo_w + 3 * mm, logo_h + 2 * mm, 1.5 * mm, stroke=0, fill=1
    )
    if logo_file:
        try:
            c.drawImage(
                logo_file,
                margin + 3.5 * mm,
                y - 15 * mm,
                width=logo_w,
                height=logo_h,
                mask="auto",
                preserveAspectRatio=True,
            )
        except Exception:
            c.setFillColor(CRN_RED)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(margin + 5 * mm, y - 10 * mm, "CRN")
    else:
        c.setFillColor(CRN_RED)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin + 5 * mm, y - 10 * mm, "CRN")

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(margin + usable_w - 3 * mm, y - 6 * mm, "RELATÓRIO DE MANUTENÇÃO PREVENTIVA")
    c.setFont("Helvetica", 7.5)
    c.drawRightString(margin + usable_w - 3 * mm, y - 10.5 * mm, "CRN DISTRIBUIDORA")
    c.setFont("Helvetica-Bold", 7)
    c.drawRightString(margin + usable_w - 3 * mm, y - 15 * mm, tipo_label[:42])

    y -= 22 * mm

    # Título
    c.setFillColor(CRN_LIGHT)
    c.setStrokeColor(CRN_RED)
    c.setLineWidth(1.5)
    box_h = 9 * mm
    c.rect(margin, y - box_h, usable_w, box_h, stroke=1, fill=1)
    c.setFillColor(CRN_BLACK)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(
        W / 2, y - box_h + 3 * mm, f"RELATÓRIO DE MANUTENÇÃO PREVENTIVA – {titulo_cliente}"
    )
    y -= box_h + 2 * mm

    # ---------- DADOS DO EQUIPAMENTO ----------
    c.setFillColor(CRN_RED)
    c.rect(margin, y - 6 * mm, usable_w, 6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, y - 4.2 * mm, "DADOS DO EQUIPAMENTO")
    y -= 6 * mm
    c.setFillColor(CRN_BLACK)

    row_h = 6.5 * mm
    col1_w = 40 * mm
    col2_w = 58 * mm
    col3_w = 30 * mm
    col_local_w = usable_w - (col1_w + col2_w + col3_w)

    def _row(label: str, val1: str, val2: str = "") -> None:
        nonlocal y
        c.setFont("Helvetica-Bold", 6.5)
        c.setStrokeColor(colors.Color(0.6, 0.6, 0.6))
        c.rect(margin, y - row_h, col1_w, row_h, stroke=1, fill=0)
        c.setFillColor(CRN_GRAY)
        c.drawString(margin + 1.5 * mm, y - row_h + 2.2 * mm, label)
        c.setFillColor(CRN_BLACK)
        c.setFont("Helvetica", 7)
        c.rect(margin + col1_w, y - row_h, col2_w, row_h, stroke=1, fill=0)
        c.drawString(margin + col1_w + 1.5 * mm, y - row_h + 2.2 * mm, str(val1)[:42])
        c.rect(margin + col1_w + col2_w, y - row_h, col3_w, row_h, stroke=1, fill=0)
        c.drawString(margin + col1_w + col2_w + 1.5 * mm, y - row_h + 2.2 * mm, str(val2)[:22])
        y -= row_h

    local_box_h = 4 * row_h
    c.setStrokeColor(CRN_RED)
    c.setLineWidth(1.2)
    c.rect(
        margin + col1_w + col2_w + col3_w,
        y - local_box_h,
        col_local_w,
        local_box_h,
        stroke=1,
        fill=0,
    )
    c.setLineWidth(0.8)
    c.setFillColor(CRN_RED)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(
        margin + col1_w + col2_w + col3_w + col_local_w / 2,
        y - 4.5 * mm,
        "LOCAL INSTALADO",
    )
    c.setFillColor(CRN_BLACK)
    c.setFont("Helvetica-Bold", 9)
    setor_txt = setor.upper()
    max_local_w = col_local_w - 4 * mm
    words = setor_txt.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if c.stringWidth(test, "Helvetica-Bold", 9) < max_local_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if not lines:
        lines = ["—"]
    ly = y - 11 * mm
    for ln in lines[:3]:
        c.drawCentredString(margin + col1_w + col2_w + col3_w + col_local_w / 2, ly, ln)
        ly -= 4 * mm

    c.setStrokeColor(colors.Color(0.6, 0.6, 0.6))
    _row("TIPO DE APARELHO :", tipo_label)
    _row("MARCA E CAPACIDADE :", marca.upper() or "—", (capacidade_txt or "").upper()[:20])
    _row("MODELO E SÉRIE:", (modelo or "—").upper(), patrimonio)
    _row("EQUIPAMENTO :", (nome_eq or "—").upper()[:40], (voltagem or "").upper())

    # ---------- CHECK LIST ----------
    y -= 1.5 * mm
    c.setFillColor(CRN_RED)
    c.rect(margin, y - 6 * mm, usable_w, 6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, y - 4.2 * mm, f"CHECK LIST — {tipo_label}")
    y -= 6 * mm
    c.setFillColor(CRN_BLACK)

    col_item = usable_w - 18 * mm - 18 * mm - 42 * mm
    col_sim = 18 * mm
    col_nao = 18 * mm
    col_obs = 42 * mm
    hdr_h = 5.5 * mm
    c.setFont("Helvetica-Bold", 7)
    for x0, w0, lab in [
        (margin, col_item, "ITEM"),
        (margin + col_item, col_sim, "SIM"),
        (margin + col_item + col_sim, col_nao, "NÃO"),
        (margin + col_item + col_sim + col_nao, col_obs, "OBSERVAÇÕES"),
    ]:
        c.setFillColor(CRN_LIGHT)
        c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
        c.rect(x0, y - hdr_h, w0, hdr_h, stroke=1, fill=1)
        c.setFillColor(CRN_BLACK)
        c.drawCentredString(x0 + w0 / 2, y - hdr_h + 1.8 * mm, lab)
    y -= hdr_h

    item_h = 5.8 * mm
    for texto, _padrao in checklist_itens:
        info = resolved.get(texto, {"sim": True, "obs": ""})
        marcado_sim = info["sim"]
        item_obs = info.get("obs") or ""

        c.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
        c.setFont("Helvetica", 6.5)
        c.rect(margin, y - item_h, col_item, item_h, stroke=1, fill=0)
        t = texto
        while c.stringWidth(t, "Helvetica", 6.5) > col_item - 3 * mm and len(t) > 12:
            t = t[:-1]
        if t != texto:
            t = t[:-2] + "…"
        c.setFillColor(CRN_BLACK)
        c.drawString(margin + 1.2 * mm, y - item_h + 1.8 * mm, t)

        c.rect(margin + col_item, y - item_h, col_sim, item_h, stroke=1, fill=0)
        c.rect(margin + col_item + col_sim, y - item_h, col_nao, item_h, stroke=1, fill=0)
        c.rect(
            margin + col_item + col_sim + col_nao,
            y - item_h,
            col_obs,
            item_h,
            stroke=1,
            fill=0,
        )

        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(CRN_RED)
        if marcado_sim:
            c.drawCentredString(margin + col_item + col_sim / 2, y - item_h + 1.6 * mm, "X")
        else:
            c.drawCentredString(
                margin + col_item + col_sim + col_nao / 2, y - item_h + 1.6 * mm, "X"
            )
        c.setFillColor(CRN_BLACK)

        if item_obs:
            c.setFont("Helvetica", 5.5)
            max_obs_w = col_obs - 2.5 * mm
            ot = item_obs
            while c.stringWidth(ot, "Helvetica", 5.5) > max_obs_w and len(ot) > 3:
                ot = ot[:-1]
            if ot != item_obs:
                ot = ot[:-1] + "…"
            c.drawString(
                margin + col_item + col_sim + col_nao + 1 * mm,
                y - item_h + 1.8 * mm,
                ot,
            )

        y -= item_h

    # linha extra
    for x0, w0 in [
        (margin, col_item),
        (margin + col_item, col_sim),
        (margin + col_item + col_sim, col_nao),
        (margin + col_item + col_sim + col_nao, col_obs),
    ]:
        c.rect(x0, y - item_h, w0, item_h, stroke=1, fill=0)
    y -= item_h + 2 * mm

    # ---------- OBSERVAÇÕES + DATAS ----------
    obs_box_h = 28 * mm
    left_w = usable_w * 0.55
    right_w = usable_w - left_w

    c.setStrokeColor(CRN_RED)
    c.setLineWidth(1)
    c.rect(margin, y - obs_box_h, left_w, obs_box_h, stroke=1, fill=0)
    c.setFillColor(CRN_RED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin + 2 * mm, y - 5 * mm, "OBSERVAÇÕES")
    c.setFillColor(CRN_BLACK)
    c.setFont("Helvetica", 7)
    words = (obs or "").replace("\n", " ").split()
    lines = []
    cur = ""
    max_obs_w = left_w - 5 * mm
    for w in words:
        test = (cur + " " + w).strip()
        if c.stringWidth(test, "Helvetica", 7) <= max_obs_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    oy = y - 10 * mm
    for ln in lines[:5]:
        c.drawString(margin + 2 * mm, oy, ln)
        oy -= 3.5 * mm

    c.rect(margin + left_w, y - obs_box_h, right_w, obs_box_h, stroke=1, fill=0)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(CRN_BLACK)
    c.drawString(margin + left_w + 2.5 * mm, y - 7 * mm, f"MANUTENÇÃO REALIZADA EM: {data_str}")
    c.drawString(margin + left_w + 2.5 * mm, y - 12.5 * mm, f"PRÓXIMA MANUTENÇÃO: {prox_str}")
    c.drawString(margin + left_w + 2.5 * mm, y - 18 * mm, "VISTO LOJISTA: ________________")
    if executante:
        c.setFont("Helvetica", 7)
        c.drawString(margin + left_w + 2.5 * mm, y - 23.5 * mm, f"Executante: {executante}")

    y -= obs_box_h + 8 * mm

    # ---------- RODAPÉ CRN ----------
    c.setStrokeColor(CRN_RED)
    c.setLineWidth(1.5)
    c.line(margin, y + 5 * mm, margin + usable_w, y + 5 * mm)
    c.setFillColor(CRN_GRAY)
    c.setFont("Helvetica", 6.5)
    for i, linha in enumerate(
        [
            "CRN DISTRIBUIDORA  •  CNPJ: 36.719.507/0001-47",
            "Tel.: (11) 2364-9800 / 2364-9809  •  atendimento@crnutrition.com.br",
            "Rua dos Trabalhadores, 460 – Terra Preta – CEP 07661-625 – São Paulo",
            "Uma empresa do grupo CRN GROUP",
        ]
    ):
        c.drawCentredString(W / 2, y - i * 3.3 * mm, linha)

    c.save()
    buf.seek(0)
    return buf.read()
