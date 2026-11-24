"""
Camada de dados e regras de negócio — Gestão de Chamados.
Separado da UI Streamlit para clareza e manutenção.
"""

import os
import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

# ====================== LOGGING ======================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def setup_logger():
    logger = logging.getLogger("chamados_app")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Arquivo rotativo (máx 2 MB, 5 backups)
    fh = RotatingFileHandler(
        LOG_DIR / "app_errors.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Também no console (útil no Streamlit Cloud logs)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


logger = setup_logger()


def log_error(msg: str, exc: Exception | None = None):
    if exc:
        logger.exception("%s | %s", msg, exc)
    else:
        logger.error(msg)


def efeito_concluido(mensagem: str, celebrar: bool = True):
    """
    Feedback visual de sucesso:
    - banner HTML em destaque
    - toast (canto da tela)
    - st.success
    - balloons (ações importantes)
    """
    import html as _html

    msg = str(mensagem or "✅ Concluído!")
    msg_esc = _html.escape(msg)
    # Banner fixo no topo do conteúdo
    try:
        st.markdown(
            f"""
            <div class="fx-sucesso" role="status" aria-live="polite">
                <div class="fx-sucesso-icone">✅</div>
                <div class="fx-sucesso-texto">
                    <div class="fx-sucesso-titulo">Sucesso</div>
                    <div class="fx-sucesso-msg">{msg_esc}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    except Exception:
        pass
    try:
        st.toast(msg, icon="✅")
    except Exception:
        pass
    try:
        st.success(msg)
    except Exception:
        pass
    if celebrar:
        try:
            st.balloons()
        except Exception:
            pass


def agendar_efeito_concluido(mensagem: str, celebrar: bool = True):
    """Agenda o feedback para o próximo rerun (balloons/banner não somem no submit)."""
    st.session_state["_efeito_pendente"] = {
        "mensagem": str(mensagem or "✅ Concluído!"),
        "celebrar": bool(celebrar),
    }


def _mostrar_efeito_pendente():
    pend = st.session_state.pop("_efeito_pendente", None)
    if not pend:
        return
    efeito_concluido(
        pend.get("mensagem", "✅ Concluído!"),
        celebrar=bool(pend.get("celebrar", True)),
    )


# ====================== CONEXÃO HÍBRIDA (LOCAL + SQLITE CLOUD) ======================
def get_connection_string() -> str | None:
    """
    Retorna a URL do SQLite Cloud se configurada, senão None (modo local).

    Aceita:
      - SQLITECLOUD_URL no TOPO do secrets.toml  (recomendado)
      - SQLITECLOUD_URL dentro de [admin]        (erro comum de TOML)
      - variável de ambiente SQLITECLOUD_URL
    """
    # 1) Topo do secrets
    try:
        url = st.secrets.get("SQLITECLOUD_URL")
        if url and str(url).strip():
            return str(url).strip()
    except Exception:
        pass

    # 2) Dentro de [admin] (chave colocada sob a seção por engano no TOML)
    try:
        admin = st.secrets.get("admin", {})
        if admin is not None:
            url = admin.get("SQLITECLOUD_URL") if hasattr(admin, "get") else None
            if url and str(url).strip():
                logger.warning(
                    "SQLITECLOUD_URL lida de [admin]. Mova a chave para o TOPO do secrets.toml."
                )
                return str(url).strip()
    except Exception:
        pass

    try:
        url = st.secrets["admin"]["SQLITECLOUD_URL"]
        if url and str(url).strip():
            logger.warning(
                "SQLITECLOUD_URL lida de [admin]. Mova a chave para o TOPO do secrets.toml."
            )
            return str(url).strip()
    except Exception:
        pass

    # 3) Variável de ambiente
    url = os.getenv("SQLITECLOUD_URL")
    if url and url.strip():
        return url.strip()

    logger.info("SQLITECLOUD_URL não encontrada. Usando apenas banco local.")
    return None


LOCAL_DB_PATH = "banco_chamados.db"


def is_cloud() -> bool:
    return get_connection_string() is not None


class _PersistentConnProxy:
    """
    Encapsula uma conexão (local ou cloud) mantida viva em cache entre
    reruns do Streamlit. Ignora .close() de propósito — todo o código
    existente chama .close() após usar a conexão, mas aqui isso só
    devolveria a conexão real ao pool; ela precisa continuar aberta para
    ser reaproveitada na próxima chamada, evitando reconectar (e refazer
    o handshake de rede/TLS, no caso do Cloud) a cada ação do usuário.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._conn, name)


# Circuit breaker: após N falhas SSL/rede, pausa tentativas Cloud por alguns segundos
# (evita flood de erros + segfault no driver quando o socket está morto).
_CLOUD_CB = {
    "failures": 0,
    "open_until": 0.0,  # time.time() até quando o breaker fica aberto
    "last_warn": 0.0,
}
_CLOUD_CB_THRESHOLD = 2  # falhas consecutivas para abrir o breaker (mais agressivo = menos flood / evita malloc no driver)
_CLOUD_CB_COOLDOWN_SEC = (
    120.0  # segundos sem tentar Cloud (evita reinícios e crashes nativos do driver)
)
_CLOUD_TRANSIENT_MARKERS = (
    "ssl",
    "socket",
    "decrypt",
    "wrong version",
    "incomplete",
    "record layer",
    "rowset signature",
    "command length",
    "connection reset",
    "broken pipe",
    "timed out",
    "timeout",
    "eof occurred",
    "nonetype' object is not iterable",
    "no such file or directory",
    "list index out of range",
    "writing data",
    "invalid literal for int",
    "another row available",
    "cannot parse rowset",
)


def _is_transient_cloud_error(exc: BaseException | str) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _CLOUD_TRANSIENT_MARKERS)


def _cloud_breaker_is_open() -> bool:
    import time

    return time.time() < float(_CLOUD_CB.get("open_until") or 0)


def _cloud_breaker_record_failure(exc: BaseException | str | None = None) -> None:
    """Registra falha; abre o breaker se passar do limiar."""
    import time

    _CLOUD_CB["failures"] = int(_CLOUD_CB.get("failures") or 0) + 1
    if _CLOUD_CB["failures"] >= _CLOUD_CB_THRESHOLD:
        _CLOUD_CB["open_until"] = time.time() + _CLOUD_CB_COOLDOWN_SEC
        now = time.time()
        # Loga no máximo 1x a cada cooldown
        if now - float(_CLOUD_CB.get("last_warn") or 0) >= _CLOUD_CB_COOLDOWN_SEC * 0.8:
            logger.warning(
                "Cloud circuit-breaker ABERTO por %.0fs após %d falhas | %s",
                _CLOUD_CB_COOLDOWN_SEC,
                _CLOUD_CB["failures"],
                (str(exc)[:120] if exc else ""),
            )
            _CLOUD_CB["last_warn"] = now


def _cloud_breaker_record_success() -> None:
    _CLOUD_CB["failures"] = 0
    _CLOUD_CB["open_until"] = 0.0


_schema_ensured_conn_ids = set()


@st.cache_resource(show_spinner=False)
def _local_conn_proxy_cached():
    import sqlite3

    raw = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)
    # Timeout de espera se outro thread estiver escrevendo
    try:
        raw.execute("PRAGMA busy_timeout = 5000")
    except Exception:
        pass
    return _PersistentConnProxy(raw)


def get_local_connection():
    """Conexão local reaproveitada entre reruns (evita reabrir o arquivo a cada ação)."""
    try:
        proxy = _local_conn_proxy_cached()
        proxy.execute("SELECT 1")
        return proxy
    except Exception:
        try:
            _local_conn_proxy_cached.clear()
        except Exception:
            pass
        return _local_conn_proxy_cached()


@st.cache_resource(show_spinner=False)
def _cloud_conn_proxy_cached(cloud_url: str):
    import sqlitecloud

    raw = sqlitecloud.connect(cloud_url)
    return _PersistentConnProxy(raw)


def _invalidate_cloud_conn():
    """Descarta conexão Cloud cacheada (SSL morto / socket quebrado)."""
    try:
        _cloud_conn_proxy_cached.clear()
    except Exception:
        pass
    # Remove ids de schema das conexões antigas (proxy morto)
    try:
        _schema_ensured_conn_ids.clear()
    except Exception:
        pass


def get_cloud_connection():
    """
    Conexão com o SQLite Cloud reaproveitada entre reruns (cache_resource).
    Com circuit-breaker: após falhas SSL/socket consecutivas, deixa de tentar
    Cloud por ~45s e usa só local (evita flood de erros e crash nativo).
    """
    if _cloud_breaker_is_open():
        return None

    cloud_url = get_connection_string()
    if not cloud_url:
        return None
    try:
        proxy = _cloud_conn_proxy_cached(cloud_url)
        proxy.execute("SELECT 1")
        _cloud_breaker_record_success()
        return proxy
    except ImportError as e:
        log_error("Pacote sqlitecloud não instalado. Rode: pip install sqlitecloud", e)
        return None
    except Exception:
        # Conexão cacheada pode ter caído (timeout/rede/SSL) — descarta e tenta reconectar 1x
        try:
            _invalidate_cloud_conn()
            proxy = _cloud_conn_proxy_cached(cloud_url)
            proxy.execute("SELECT 1")
            _cloud_breaker_record_success()
            return proxy
        except Exception as e2:
            msg = str(e2)
            if _is_transient_cloud_error(msg):
                logger.warning("Cloud offline temporário (SSL/rede) | %s", msg[:180])
            else:
                log_error(
                    f"Falha ao conectar no SQLite Cloud | url={cloud_url[:60]}...",
                    e2,
                )
            _invalidate_cloud_conn()
            _cloud_breaker_record_failure(e2)
            return None


def get_db_connection():
    """
    Conexão principal de leitura/escrita.
    Prioridade: Cloud (se configurado e saudável) → Local.
    """
    cloud = get_cloud_connection()
    if cloud is not None:
        return cloud
    return get_local_connection()


def _colunas_tabela(conn, tabela: str) -> set:
    """Retorna o conjunto de nomes de colunas de uma tabela (PRAGMA table_info)."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({tabela})")
        rows = cur.fetchall() or []
        # Consome qualquer residual (sqlitecloud às vezes deixa row pendente)
        try:
            while cur.fetchone() is not None:
                pass
        except Exception:
            pass
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        return {str(r[1]) for r in rows if r and len(r) > 1}
    except Exception:
        return set()


def _alter_add_column(conn, tabela: str, col: str, tipo: str) -> bool:
    """
    ALTER TABLE ADD COLUMN com cursor novo a cada tentativa.
    Evita 'another row available' do driver sqlitecloud (estado residual no cursor).
    Retorna True se a coluna foi adicionada ou já existia.
    """
    msg_ok = ("duplicate column", "already exists")
    for tentativa in range(2):
        try:
            cur = conn.cursor()
            cur.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {tipo}")
            try:
                conn.commit()
            except Exception:
                pass
            return True
        except Exception as e:
            msg = str(e).lower()
            if any(m in msg for m in msg_ok):
                return True
            # Cursor com row pendente: tenta 1x com cursor fresco
            if "another row available" in msg and tentativa == 0:
                try:
                    # Descarta estado residual da conexão
                    cur2 = conn.cursor()
                    try:
                        cur2.execute("SELECT 1")
                        cur2.fetchall()
                    except Exception:
                        pass
                except Exception:
                    pass
                continue
            log_error(f"_migrar_colunas ALTER {col} falhou", e)
            # Erro transitório de Cloud: não insiste (evita crash nativo/malloc)
            if _is_transient_cloud_error(e):
                raise
            return False
    return False


def _ensure_schema(conn):
    """
    Cria tabelas (e roda a migração de colunas) se ainda não existirem.
    Como as conexões agora são reaproveitadas entre reruns (cache_resource),
    a verificação completa só precisa rodar UMA VEZ por conexão — repeti-la
    a cada salvamento era um dos principais motivos da lentidão (vários
    comandos extras via rede a cada clique, no caso do Cloud).
    """
    if id(conn) in _schema_ensured_conn_ids:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chamados (
                id INTEGER PRIMARY KEY,
                solicitante TEXT,
                data_hora_abertura TEXT,
                setor TEXT,
                equipamento TEXT,
                prioridade TEXT,
                descricao TEXT,
                status TEXT,
                executante TEXT,
                data_hora_inicio TEXT,
                data_hora_conclusao TEXT,
                foto_path TEXT,
                solucao_descricao TEXT,
                foto_solucao_path TEXT,
                comentario_conclusao TEXT,
                peca_solicitada TEXT,
                peca_observacao TEXT,
                data_solicitacao_peca TEXT
            )
        """)
        _migrar_colunas_chamados(conn)
        _normalizar_status_chamados(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equipe (
                id INTEGER PRIMARY KEY,
                nome TEXT,
                funcao TEXT,
                contato TEXT,
                ativo INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS setores (
                id INTEGER PRIMARY KEY,
                setor TEXT UNIQUE
            )
        """)
        _migrar_setores(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS config_sla (
                prioridade TEXT PRIMARY KEY,
                minutos INTEGER NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS equipamentos (
                id INTEGER PRIMARY KEY,
                nome TEXT,
                marca TEXT,
                modelo TEXT,
                ano_aquisicao INTEGER,
                numero_patrimonio TEXT,
                setor TEXT,
                sazonalidade_meses INTEGER,
                ultima_preventiva TEXT,
                proxima_preventiva TEXT,
                silenciar_ate TEXT
            )
        """)
        _migrar_colunas_equipamentos(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS manutencoes_historico (
                id INTEGER PRIMARY KEY,
                equipamento_id INTEGER,
                equipamento_nome TEXT,
                tipo TEXT,
                data_manutencao TEXT,
                executante TEXT,
                descricao TEXT,
                pecas_trocadas TEXT,
                custo_pecas REAL DEFAULT 0,
                horas_homem REAL DEFAULT 0,
                chamado_id INTEGER,
                observacao TEXT,
                checklist_json TEXT
            )
        """)
        _migrar_colunas_manutencoes(conn)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS compras_pecas (
                id INTEGER PRIMARY KEY,
                chamado_id INTEGER,
                equipamento TEXT,
                prioridade TEXT,
                item_nome TEXT,
                link_compra TEXT,
                observacao TEXT,
                solicitante TEXT,
                prazo_recebimento TEXT,
                status TEXT,
                aprovado TEXT,
                dias_para_chegada INTEGER,
                valor_item REAL,
                data_solicitacao TEXT,
                data_aprovacao TEXT,
                data_recebimento TEXT,
                comprador TEXT,
                observacao_compras TEXT,
                cotacoes_json TEXT,
                cotacao_escolhida INTEGER
            )
        """)
        _migrar_colunas_compras(conn)
        # ---- Almoxarifado / inventário de manutenção ----
        cur.execute("""
            CREATE TABLE IF NOT EXISTS almox_itens (
                id INTEGER PRIMARY KEY,
                codigo TEXT,
                nome TEXT,
                categoria TEXT,
                subcategoria TEXT,
                unidade TEXT,
                quantidade REAL DEFAULT 0,
                estoque_min REAL DEFAULT 0,
                localizacao TEXT,
                setor TEXT,
                equipamento_ref TEXT,
                especificacao TEXT,
                observacao TEXT,
                ativo INTEGER DEFAULT 1,
                data_cadastro TEXT,
                data_atualizacao TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS almox_maletas (
                id INTEGER PRIMARY KEY,
                codigo TEXT,
                nome TEXT,
                setor TEXT,
                responsavel TEXT,
                observacao TEXT,
                ativo INTEGER DEFAULT 1,
                data_cadastro TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS almox_maleta_itens (
                id INTEGER PRIMARY KEY,
                maleta_id INTEGER,
                item_id INTEGER,
                quantidade REAL DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS almox_movimentacoes (
                id INTEGER PRIMARY KEY,
                item_id INTEGER,
                tipo TEXT,
                quantidade REAL,
                saldo_apos REAL,
                data TEXT,
                responsavel TEXT,
                motivo TEXT,
                chamado_id INTEGER,
                maleta_id INTEGER,
                observacao TEXT
            )
        """)
        # ---- Integrações / eventos / fotos ----
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chamado_eventos (
                id INTEGER PRIMARY KEY,
                chamado_id INTEGER NOT NULL,
                data_hora TEXT,
                tipo TEXT,
                usuario TEXT,
                detalhe TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chamado_fotos (
                id INTEGER PRIMARY KEY,
                chamado_id INTEGER,
                tipo TEXT,
                path_local TEXT,
                url_remota TEXT,
                destino TEXT,
                data_envio TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS integracoes_log (
                id INTEGER PRIMARY KEY,
                data_hora TEXT,
                canal TEXT,
                destino TEXT,
                chamado_id INTEGER,
                ok INTEGER,
                detalhe TEXT
            )
        """)
        try:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_integracoes_data ON integracoes_log(data_hora)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_integracoes_canal ON integracoes_log(canal)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_eventos_chamado ON chamado_eventos(chamado_id)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_fotos_chamado ON chamado_fotos(chamado_id)")
        except Exception:
            pass
        _migrar_colunas_equipe(conn)
        _aplicar_indices(conn)
        conn.commit()
        _schema_ensured_conn_ids.add(id(conn))
    except Exception as e:
        # Não marca como "ensured" se falhou — permite retry na próxima chamada
        # Não propaga: evita derrubar o processo/Streamlit por falha transitória de Cloud
        log_error("_ensure_schema falhou", e)
        if _is_transient_cloud_error(e) or "another row available" in str(e).lower():
            try:
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e)
            except Exception:
                pass
        # Não faz raise — app continua com o que já existir


def _migrar_colunas_chamados(conn):
    """
    Adiciona colunas novas em bancos já existentes (ALTER TABLE), sem quebrar
    instalações antigas. Verifica colunas existentes via PRAGMA antes do ALTER
    (mais confiável que try/except no driver sqlitecloud, que pode deixar a
    conexão em estado inválido após erro de 'duplicate column').
    """
    colunas_novas = {
        "comentario_conclusao": "TEXT",
        "peca_solicitada": "TEXT",
        "peca_observacao": "TEXT",
        "data_solicitacao_peca": "TEXT",
        "foto_url": "TEXT",
        "foto_solucao_url": "TEXT",
        "notificado_whatsapp": "INTEGER",
        "contato_solicitante": "TEXT",
    }
    existentes = _colunas_tabela(conn, "chamados")
    if not existentes:
        # Tabela recém-criada pelo CREATE TABLE acima já tem todas as colunas
        return
    for col, tipo in colunas_novas.items():
        if col in existentes:
            continue
        if _alter_add_column(conn, "chamados", col, tipo):
            existentes.add(col)
        else:
            break  # evita martelar conexão Cloud já instável


def _migrar_colunas_equipe(conn):
    existentes = _colunas_tabela(conn, "equipe")
    if not existentes:
        return
    for col, tipo in (("whatsapp", "TEXT"),):
        if col not in existentes:
            if _alter_add_column(conn, "equipe", col, tipo):
                existentes.add(col)
            else:
                break


def _aplicar_indices(conn) -> None:
    """Índices de consulta — acelera dashboard, filtros e relatórios."""
    stmts = [
        "CREATE INDEX IF NOT EXISTS idx_chamados_status ON chamados(status)",
        "CREATE INDEX IF NOT EXISTS idx_chamados_setor ON chamados(setor)",
        "CREATE INDEX IF NOT EXISTS idx_chamados_equipamento ON chamados(equipamento)",
        "CREATE INDEX IF NOT EXISTS idx_chamados_abertura ON chamados(data_hora_abertura)",
        "CREATE INDEX IF NOT EXISTS idx_chamados_conclusao ON chamados(data_hora_conclusao)",
        "CREATE INDEX IF NOT EXISTS idx_chamados_executante ON chamados(executante)",
        "CREATE INDEX IF NOT EXISTS idx_equip_setor ON equipamentos(setor)",
        "CREATE INDEX IF NOT EXISTS idx_equip_prox ON equipamentos(proxima_preventiva)",
        "CREATE INDEX IF NOT EXISTS idx_manut_equip ON manutencoes_historico(equipamento_id)",
        "CREATE INDEX IF NOT EXISTS idx_manut_data ON manutencoes_historico(data_manutencao)",
        "CREATE INDEX IF NOT EXISTS idx_compras_status ON compras_pecas(status)",
        "CREATE INDEX IF NOT EXISTS idx_compras_chamado ON compras_pecas(chamado_id)",
        "CREATE INDEX IF NOT EXISTS idx_almox_nome ON almox_itens(nome)",
        "CREATE INDEX IF NOT EXISTS idx_mov_item ON almox_movimentacoes(item_id)",
    ]
    try:
        cur = conn.cursor()
        for sql in stmts:
            try:
                cur.execute(sql)
            except Exception:
                pass
        try:
            conn.commit()
        except Exception:
            pass
    except Exception as e:
        log_error("_aplicar_indices", e)


def _normalizar_status_chamados(conn) -> None:
    """
    Corrige valores de status legados / digitados errado no Cloud ou local.
    Ex.: 'Concluido' (sem acento) → 'Concluído' (padrão do app).
    """
    mapa = {
        "Concluido": "Concluído",
        "concluido": "Concluído",
        "CONCLUIDO": "Concluído",
        "concluído": "Concluído",
        "Em atendimento": "Em Atendimento",
        "em atendimento": "Em Atendimento",
        "Aguardando peca": "Aguardando Peça",
        "Aguardando peça": "Aguardando Peça",
        "aguardando peça": "Aguardando Peça",
        "Aberto ": "Aberto",
    }
    try:
        cur = conn.cursor()
        for antigo, novo in mapa.items():
            try:
                cur.execute(
                    "UPDATE chamados SET status = ? WHERE status = ?",
                    (novo, antigo),
                )
            except Exception:
                pass
        try:
            conn.commit()
        except Exception:
            pass
    except Exception as e:
        logger.warning("_normalizar_status_chamados | %s", str(e)[:120])


def _migrar_colunas_equipamentos(conn):
    """Adiciona colunas novas em equipamentos (ex.: silenciar_ate)."""
    colunas_novas = {
        "silenciar_ate": "TEXT",
    }
    existentes = _colunas_tabela(conn, "equipamentos")
    if not existentes:
        return
    for col, tipo in colunas_novas.items():
        if col in existentes:
            continue
        if _alter_add_column(conn, "equipamentos", col, tipo):
            existentes.add(col)
        else:
            break


def _migrar_colunas_manutencoes(conn):
    """Adiciona colunas novas em manutencoes_historico (checklist_json)."""
    colunas_novas = {
        "checklist_json": "TEXT",
    }
    existentes = _colunas_tabela(conn, "manutencoes_historico")
    if not existentes:
        return
    for col, tipo in colunas_novas.items():
        if col in existentes:
            continue
        if _alter_add_column(conn, "manutencoes_historico", col, tipo):
            existentes.add(col)
        else:
            break


def _migrar_colunas_compras(conn):
    """
    Adiciona colunas novas em compras_pecas (cotações e campos de compras)
    em bancos legados que ainda não as possuem.
    """
    colunas_novas = {
        "observacao_compras": "TEXT",
        "cotacoes_json": "TEXT",
        "cotacao_escolhida": "INTEGER",
        "comprador": "TEXT",
        "data_aprovacao": "TEXT",
        "data_recebimento": "TEXT",
        "dias_para_chegada": "INTEGER",
        "valor_item": "REAL",
        "aprovado": "TEXT",
    }
    existentes = _colunas_tabela(conn, "compras_pecas")
    if not existentes:
        # Tabela recém-criada pelo CREATE TABLE acima já tem todas as colunas
        return
    for col, tipo in colunas_novas.items():
        if col in existentes:
            continue
        if _alter_add_column(conn, "compras_pecas", col, tipo):
            existentes.add(col)
        else:
            break


def _migrar_setores(conn):
    """
    Garante que a tabela setores tenha a coluna id.
    Bancos antigos tinham apenas a coluna 'setor' — isso causava
    'table setores has no column named id' em salvar_setores.
    Estratégia: se não houver 'id', recria a tabela preservando os nomes.
    """
    try:
        existentes = _colunas_tabela(conn, "setores")
        if not existentes:
            return
        if "id" in existentes:
            return
        cur = conn.cursor()
        nomes = []
        try:
            cur.execute("SELECT setor FROM setores")
            for row in cur.fetchall() or []:
                if row and row[0] and str(row[0]).strip():
                    nomes.append(str(row[0]).strip())
        except Exception:
            pass
        try:
            cur.execute("DROP TABLE IF EXISTS setores")
            cur.execute("CREATE TABLE setores (id INTEGER PRIMARY KEY, setor TEXT UNIQUE)")
            for i, s in enumerate(nomes, start=1):
                try:
                    cur.execute(
                        "INSERT OR IGNORE INTO setores (id, setor) VALUES (?, ?)",
                        (i, s),
                    )
                except Exception:
                    pass
            conn.commit()
            logger.info("_migrar_setores OK | %d setores preservados", len(nomes))
        except Exception as e:
            log_error("_migrar_setores recriação falhou", e)
    except Exception as e:
        logger.warning("_migrar_setores | %s", str(e)[:120])


def _safe_cell(v):
    """Normaliza célula para INSERT (None / string de data)."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OverflowError):
            return None
    if isinstance(v, str):
        s = v.strip()
        return s if s and s.lower() not in ("nat", "nan", "none", "null") else None
    return v


def _row_to_dict(row, cols) -> dict:
    d = {}
    for i, c in enumerate(cols):
        d[c] = _safe_cell(row[i] if i < len(row) else None)
    return d


def _fetch_all_dicts(conn, tabela: str) -> dict:
    """Lê tabela inteira → {id: row_dict}. Nunca lança se tabela vazia."""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {tabela}")
        rows = cur.fetchall() or []
        cols = [d[0] for d in (cur.description or [])]
    except Exception:
        return {}
    if not cols:
        return {}
    out = {}
    for r in rows:
        d = _row_to_dict(r, cols)
        rid = d.get("id")
        if rid is None and tabela == "setores":
            key = (d.get("setor") or "").strip().lower()
            if key:
                out[key] = d
            continue
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            continue
        out[rid] = d
    return out


def _parse_ts(v) -> float:
    """Converte data/hora em epoch float (0 se inválido)."""
    if v is None or v == "":
        return 0.0
    try:
        if pd.isna(v):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return 0.0
        return float(ts.timestamp())
    except Exception:
        return 0.0


# Ranking de status: maior = mais avançado no fluxo
# Rank só como desempate fraco. NÃO pode bloquear retomada
# (Aguardando Peça → Em Atendimento), por isso Em Atendimento >= Aguardando Peça.
_STATUS_RANK_CHAMADO = {
    "Aberto": 1,
    "Aguardando Peça": 2,
    "Em Atendimento": 3,
    "Concluído": 4,
}
_STATUS_RANK_COMPRA = {
    "Pendente": 1,
    "Rejeitada": 1,
    "Em Cotação": 1,
    "Aguardando retorno do fornecedor": 1,
    "Aprovada": 2,
    "Comprada": 3,
    "Recebida": 4,
}


def _merge_dicts_fieldwise(winner: dict, other: dict) -> dict:
    """Campos do winner prevalecem; preenche lacunas com other (nunca perde dado)."""
    out = dict(winner)
    for k, v in other.items():
        if k not in out or out[k] is None or out[k] == "":
            if v is not None and v != "":
                out[k] = v
        elif (
            k
            in (
                "comentario_conclusao",
                "peca_observacao",
                "observacao",
                "observacao_compras",
                "descricao",
                "solucao_descricao",
            )
            and isinstance(out[k], str)
            and isinstance(v, str)
            and v.strip()
            and v.strip() not in out[k]
        ):
            out[k] = (out[k].rstrip() + "\n---\n" + v.strip()).strip()
    return out


def _chamado_activity_ts(c: dict) -> float:
    """Última atividade conhecida do chamado (para merge)."""
    return max(
        _parse_ts(c.get("data_hora_conclusao")),
        _parse_ts(c.get("data_hora_inicio")),
        _parse_ts(c.get("data_solicitacao_peca")),
        _parse_ts(c.get("data_hora_abertura")),
    )


def _pick_chamado(a: dict, b: dict) -> dict:
    """
    Resolve conflito entre duas cópias do mesmo chamado.
    1) Concluído sempre vence.
    2) Senão, vence a cópia com atividade mais recente.
    3) Empate de data: usa rank (Em Atendimento > Aguardando Peça).
    """
    sa = str(a.get("status") or "")
    sb = str(b.get("status") or "")
    if sa == "Concluído" and sb != "Concluído":
        return _merge_dicts_fieldwise(a, b)
    if sb == "Concluído" and sa != "Concluído":
        return _merge_dicts_fieldwise(b, a)

    ta = _chamado_activity_ts(a)
    tb = _chamado_activity_ts(b)
    if ta != tb:
        winner, other = (a, b) if ta > tb else (b, a)
    else:
        ra = _STATUS_RANK_CHAMADO.get(sa, 0)
        rb = _STATUS_RANK_CHAMADO.get(sb, 0)
        winner, other = (a, b) if ra >= rb else (b, a)
    return _merge_dicts_fieldwise(winner, other)


def _pick_equipamento(a: dict, b: dict) -> dict:
    ta = max(_parse_ts(a.get("ultima_preventiva")), _parse_ts(a.get("proxima_preventiva")))
    tb = max(_parse_ts(b.get("ultima_preventiva")), _parse_ts(b.get("proxima_preventiva")))
    winner, other = (a, b) if ta >= tb else (b, a)
    return _merge_dicts_fieldwise(winner, other)


def _pick_compra(a: dict, b: dict) -> dict:
    ra = _STATUS_RANK_COMPRA.get(str(a.get("status") or ""), 0)
    rb = _STATUS_RANK_COMPRA.get(str(b.get("status") or ""), 0)
    if ra != rb:
        winner, other = (a, b) if ra > rb else (b, a)
    else:
        ta = max(
            _parse_ts(a.get("data_recebimento")),
            _parse_ts(a.get("data_aprovacao")),
            _parse_ts(a.get("data_solicitacao")),
        )
        tb = max(
            _parse_ts(b.get("data_recebimento")),
            _parse_ts(b.get("data_aprovacao")),
            _parse_ts(b.get("data_solicitacao")),
        )
        winner, other = (a, b) if ta >= tb else (b, a)
    merged = _merge_dicts_fieldwise(winner, other)
    try:
        va = float(a.get("valor_item") or 0)
        vb = float(b.get("valor_item") or 0)
        merged["valor_item"] = max(va, vb)
    except (TypeError, ValueError):
        pass
    return merged


def _pick_manutencao(a: dict, b: dict) -> dict:
    ta = _parse_ts(a.get("data_manutencao"))
    tb = _parse_ts(b.get("data_manutencao"))
    winner, other = (a, b) if ta >= tb else (b, a)
    merged = _merge_dicts_fieldwise(winner, other)
    try:
        merged["custo_pecas"] = max(
            float(a.get("custo_pecas") or 0), float(b.get("custo_pecas") or 0)
        )
        merged["horas_homem"] = max(
            float(a.get("horas_homem") or 0), float(b.get("horas_homem") or 0)
        )
    except (TypeError, ValueError):
        pass
    return merged


def _pick_equipe(a: dict, b: dict) -> dict:
    aa = int(a.get("ativo") or 0)
    ba = int(b.get("ativo") or 0)
    winner, other = (a, b) if aa >= ba else (b, a)
    return _merge_dicts_fieldwise(winner, other)


def _pick_almox_item(a: dict, b: dict) -> dict:
    """Prefere o registro com data_atualizacao mais recente; senão maior quantidade."""
    ta = _parse_ts(a.get("data_atualizacao")) or _parse_ts(a.get("data_cadastro"))
    tb = _parse_ts(b.get("data_atualizacao")) or _parse_ts(b.get("data_cadastro"))
    if ta != tb:
        winner, other = (a, b) if ta >= tb else (b, a)
        return _merge_dicts_fieldwise(winner, other)
    qa = float(a.get("quantidade") or 0)
    qb = float(b.get("quantidade") or 0)
    winner, other = (a, b) if qa >= qb else (b, a)
    return _merge_dicts_fieldwise(winner, other)


def _pick_almox_maleta(a: dict, b: dict) -> dict:
    aa = int(a.get("ativo") or 0)
    ba = int(b.get("ativo") or 0)
    if aa != ba:
        winner, other = (a, b) if aa >= ba else (b, a)
        return _merge_dicts_fieldwise(winner, other)
    return _merge_dicts_fieldwise(a, b)


def _pick_almox_mov(a: dict, b: dict) -> dict:
    ta = _parse_ts(a.get("data"))
    tb = _parse_ts(b.get("data"))
    if ta != tb:
        return a if ta >= tb else b
    return _merge_dicts_fieldwise(a, b)


def _pick_by_id_keep(a: dict, b: dict) -> dict:
    return _merge_dicts_fieldwise(a, b)


def _upsert_row_generic(conn, tabela: str, row: dict, colunas: list) -> None:
    """INSERT ou UPDATE genérico por id (nunca DELETE)."""
    cur = conn.cursor()
    rid = row.get("id")
    if rid is None:
        return
    cur.execute(f"SELECT 1 FROM {tabela} WHERE id = ?", (rid,))
    existe = cur.fetchone() is not None
    cols_ok = [c for c in colunas if c in row and c != "id"]
    if not cols_ok and not existe:
        # precisa ao menos do id
        cols_ok = []
    vals = [_safe_cell(row.get(c)) for c in cols_ok]
    if existe:
        if not cols_ok:
            return
        sets = ", ".join(f"{c}=?" for c in cols_ok)
        cur.execute(
            f"UPDATE {tabela} SET {sets} WHERE id = ?",
            (*vals, rid),
        )
    else:
        all_cols = ["id"] + cols_ok
        placeholders = ",".join(["?"] * len(all_cols))
        cur.execute(
            f"INSERT INTO {tabela} ({','.join(all_cols)}) VALUES ({placeholders})",
            (rid, *vals),
        )


def _colunas_ordenadas(conn, tabela: str) -> list:
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({tabela})")
        rows = cur.fetchall() or []
        return [str(r[1]) for r in rows if r and len(r) > 1]
    except Exception:
        return []


def _merge_table_by_id(local, cloud, tabela: str, picker) -> tuple:
    """
    Merge bidirecional por id.
    Retorna (inseridos_local, inseridos_cloud, atualizados).
    NUNCA apaga registros.
    """
    loc_map = _fetch_all_dicts(local, tabela)
    clo_map = _fetch_all_dicts(cloud, tabela)
    cols_local = _colunas_ordenadas(local, tabela)
    cols_cloud = _colunas_ordenadas(cloud, tabela)
    cols = list(cols_local)
    for c in cols_cloud:
        if c not in cols:
            cols.append(c)

    all_ids = set(loc_map.keys()) | set(clo_map.keys())
    ins_l = ins_c = upd = 0

    for rid in all_ids:
        if not isinstance(rid, int):
            continue
        a = loc_map.get(rid)
        b = clo_map.get(rid)
        if a is not None and b is None:
            _upsert_row_generic(cloud, tabela, a, cols)
            ins_c += 1
        elif b is not None and a is None:
            _upsert_row_generic(local, tabela, b, cols)
            ins_l += 1
        elif a is not None and b is not None:
            merged = picker(a, b)
            if merged != a:
                _upsert_row_generic(local, tabela, merged, cols)
                upd += 1
            if merged != b:
                _upsert_row_generic(cloud, tabela, merged, cols)
                upd += 1
    try:
        local.commit()
    except Exception:
        pass
    try:
        cloud.commit()
    except Exception:
        pass
    return ins_l, ins_c, upd


def _merge_setores(local, cloud) -> tuple:
    """União de nomes de setores (sem apagar nenhum)."""
    loc = _fetch_all_dicts(local, "setores")
    clo = _fetch_all_dicts(cloud, "setores")

    nomes = []
    seen = set()

    def _add(name):
        n = (name or "").strip()
        if not n:
            return
        key = n.lower()
        if key in seen:
            return
        seen.add(key)
        nomes.append(n)

    for d in loc.values():
        if isinstance(d, dict):
            _add(d.get("setor"))
    for d in clo.values():
        if isinstance(d, dict):
            _add(d.get("setor"))

    if not nomes:
        nomes = [
            "Fracionamento 1",
            "Fracionamento 2",
            "Mistura 1",
            "Mistura 2",
            "Mistura 3",
            "Mistura 4",
            "Envase 1",
            "Envase 2",
            "RH 1",
            "Laboratório",
            "Outros",
        ]

    def _write(conn, lista):
        if conn is None:
            return 0
        cur = conn.cursor()
        cur.execute("SELECT id, setor FROM setores")
        existentes = {
            str(r[1]).strip().lower(): int(r[0]) for r in (cur.fetchall() or []) if r and r[1]
        }
        max_id = 0
        try:
            # Novo cursor para evitar "another row available"
            cur2 = conn.cursor()
            cur2.execute("SELECT COALESCE(MAX(id), 0) FROM setores")
            max_id = int(cur2.fetchone()[0] or 0)
        except Exception:
            pass
        adicionados = 0
        cur3 = conn.cursor()
        for s in lista:
            key = s.strip().lower()
            if key in existentes:
                continue
            max_id += 1
            cur3.execute(
                "INSERT INTO setores (id, setor) VALUES (?, ?)",
                (max_id, s.strip()),
            )
            existentes[key] = max_id
            adicionados += 1
        conn.commit()
        return adicionados

    a_l = 0
    a_c = 0
    try:
        a_l = _write(local, nomes)
    except Exception as e:
        log_error("_merge_setores local falhou", e)
    try:
        a_c = _write(cloud, nomes)
    except Exception as e:
        log_error("_merge_setores cloud falhou", e)
        if _is_transient_cloud_error(e):
            try:
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e)
            except Exception:
                pass
    return a_l, a_c


def sync_local_to_cloud() -> tuple:
    """
    Sincronização por MERGE bidirecional Local ↔ Cloud.

    - NUNCA apaga registros.
    - Insere no destino o que só existe na origem.
    - Quando o mesmo id existe nos dois lados, escolhe a versão mais
      avançada (status / data) e preenche campos vazios com a outra
      (não perde comentários, valores, etc.).
    """
    if not is_cloud():
        return False, "SQLITECLOUD_URL não configurada nos Secrets."
    if _cloud_breaker_is_open():
        return (
            False,
            "Cloud temporariamente instável (circuit-breaker). Tente em alguns segundos.",
        )

    try:
        local = get_local_connection()
        _ensure_schema(local)

        cloud = get_cloud_connection()
        if cloud is None:
            try:
                local.close()
            except Exception:
                pass
            return False, "Não foi possível conectar no SQLite Cloud."
        _ensure_schema(cloud)

        resumo = []

        il, ic, up = _merge_table_by_id(local, cloud, "chamados", _pick_chamado)
        resumo.append(f"chamados: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "equipe", _pick_equipe)
        resumo.append(f"equipe: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "equipamentos", _pick_equipamento)
        resumo.append(f"equipamentos: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "manutencoes_historico", _pick_manutencao)
        resumo.append(f"manutencoes: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "compras_pecas", _pick_compra)
        resumo.append(f"compras: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "almox_itens", _pick_almox_item)
        resumo.append(f"almox_itens: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "almox_maletas", _pick_almox_maleta)
        resumo.append(f"almox_maletas: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "almox_maleta_itens", _pick_by_id_keep)
        resumo.append(f"almox_maleta_itens: +local={il} +cloud={ic} merge={up}")

        il, ic, up = _merge_table_by_id(local, cloud, "almox_movimentacoes", _pick_almox_mov)
        resumo.append(f"almox_mov: +local={il} +cloud={ic} merge={up}")

        al, ac = _merge_setores(local, cloud)
        resumo.append(f"setores: +local={al} +cloud={ac}")

        try:
            local.close()
        except Exception:
            pass
        try:
            cloud.close()
        except Exception:
            pass

        msg = "Merge Local ↔ Cloud OK (nada apagado) | " + " | ".join(resumo)
        logger.info(msg)
        return True, msg
    except Exception as e:
        log_error("sync_local_to_cloud (merge) falhou", e)
        _invalidate_cloud_conn()
        _cloud_breaker_record_failure(e)
        return False, f"Erro na sincronização (merge): {e}"


def dual_write_execute(sql: str, params: tuple = ()):
    """
    Executa o mesmo SQL no local E no cloud (se configurado).
    Garante que os dois bancos fiquem alinhados.
    Falha no Cloud NÃO impede o sucesso local (fonte da verdade offline).
    """
    erros = []

    # 1) Local (sempre)
    try:
        local = get_local_connection()
        _ensure_schema(local)
        local.execute(sql, params)
        local.commit()
        local.close()
    except Exception as e:
        log_error(f"dual_write LOCAL falhou: {sql[:80]}", e)
        erros.append(f"local: {e}")

    # 2) Cloud (se houver e breaker fechado)
    if is_cloud() and not _cloud_breaker_is_open():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()
                _cloud_breaker_record_success()
        except Exception as e:
            if _is_transient_cloud_error(e):
                logger.warning("dual_write CLOUD transiente: %s | %s", sql[:60], str(e)[:140])
            else:
                log_error(f"dual_write CLOUD falhou: {sql[:80]}", e)
            _invalidate_cloud_conn()
            _cloud_breaker_record_failure(e)
            erros.append(f"cloud: {e}")

    # Sucesso se o local gravou (cloud é best-effort quando flaky)
    local_ok = not any(str(e).startswith("local:") for e in erros)
    return local_ok, erros


# ====================== BANCO DE DADOS ======================
def _count_rows(conn, tabela: str) -> int:
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {tabela}")
        row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _bootstrap_local_from_cloud() -> str:
    """
    Copia/atualiza dados do Cloud → Local por UPSERT (nunca DELETE).
    Essencial no Streamlit Cloud: o disco local é efêmero e começa vazio
    a cada restart — sem isso o app "perde" os chamados que só estão no Cloud
    e ainda pode sobrescrever IDs ao gravar novos tickets.
    """
    if not is_cloud() or _cloud_breaker_is_open():
        return "bootstrap ignorado (cloud offline/breaker)"
    try:
        cloud = get_cloud_connection()
        if cloud is None:
            return "bootstrap ignorado (sem conexão cloud)"
        local = get_local_connection()
        _ensure_schema(local)
        try:
            _ensure_schema(cloud)
        except Exception as e_sch:
            if _is_transient_cloud_error(e_sch):
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e_sch)
                return f"bootstrap abortado (schema cloud instável): {e_sch}"
            raise
        if _cloud_breaker_is_open():
            return "bootstrap abortado (breaker aberto após schema)"

        tabelas_id = [
            ("chamados", _pick_chamado),
            ("equipe", _pick_equipe),
            ("equipamentos", _pick_equipamento),
            ("manutencoes_historico", _pick_manutencao),
            ("compras_pecas", _pick_compra),
            ("almox_itens", _pick_almox_item),
            ("almox_maletas", _pick_almox_maleta),
            ("almox_maleta_itens", _pick_by_id_keep),
            ("almox_movimentacoes", _pick_almox_mov),
        ]
        partes = []
        for tabela, picker in tabelas_id:
            if _cloud_breaker_is_open():
                partes.append(f"{tabela}:abortado")
                break
            try:
                clo = _fetch_all_dicts(cloud, tabela)
            except Exception as e_fetch:
                if _is_transient_cloud_error(e_fetch):
                    _invalidate_cloud_conn()
                    _cloud_breaker_record_failure(e_fetch)
                    partes.append(f"{tabela}:cloud_offline")
                    break
                raise
            loc = _fetch_all_dicts(local, tabela)
            cols = _colunas_ordenadas(local, tabela) or _colunas_ordenadas(cloud, tabela)
            n_new = n_upd = 0
            for rid, crow in clo.items():
                if not isinstance(rid, int):
                    continue
                lrow = loc.get(rid)
                if lrow is None:
                    _upsert_row_generic(local, tabela, crow, cols)
                    n_new += 1
                else:
                    merged = picker(lrow, crow)
                    if merged != lrow:
                        _upsert_row_generic(local, tabela, merged, cols)
                        n_upd += 1
            partes.append(f"{tabela}:+{n_new}/~{n_upd}")

        # setores: união de nomes (só se cloud ainda saudável)
        if not _cloud_breaker_is_open():
            al, _ac = _merge_setores(local, cloud)
            partes.append(f"setores:+{al}")
        else:
            partes.append("setores:pulado")

        try:
            local.commit()
        except Exception:
            pass
        try:
            local.close()
        except Exception:
            pass
        try:
            cloud.close()
        except Exception:
            pass
        msg = "bootstrap Cloud→Local OK | " + " ".join(partes)
        logger.info(msg)
        return msg
    except Exception as e:
        log_error("bootstrap Cloud→Local falhou", e)
        _invalidate_cloud_conn()
        return f"bootstrap falhou: {e}"


def init_db(force: bool = False):
    """
    Cria tabelas no local e no cloud (se configurado).
    Por padrão roda só uma vez por sessão — o autorefresh a cada 30s
    não deve reabrir handshake Cloud nem lotar o log.

    Após conectar no Cloud, faz bootstrap Cloud→Local (UPSERT, sem apagar)
    para o disco efêmero do Streamlit Cloud não ficar vazio.
    """
    if not force and st.session_state.get("_db_init_done"):
        return
    cloud_ok = False
    cloud_msg = "não configurado"
    bootstrap_msg = ""
    try:
        # Local sempre
        local = get_local_connection()
        _ensure_schema(local)
        n_local = _count_rows(local, "chamados")
        local.close()

        url = get_connection_string()
        if url:
            cloud = get_cloud_connection()
            if cloud is not None:
                try:
                    _ensure_schema(cloud)
                    # Se schema Cloud falhou com erro transitório, breaker pode ter aberto
                    if _cloud_breaker_is_open():
                        cloud_msg = "schema Cloud instável (usando só local)"
                        logger.warning("init_db: breaker aberto após schema Cloud")
                    else:
                        cur = cloud.cursor()
                        cur.execute("SELECT COUNT(*) FROM chamados")
                        n_cloud = int((cur.fetchone() or [0])[0] or 0)
                        try:
                            cloud.close()
                        except Exception:
                            pass
                        cloud_ok = True
                        cloud_msg = f"conectado OK ({n_cloud} chamados)"
                        # Bootstrap só se local vazio ou bem atrás do cloud
                        # (evita carga pesada / instabilidade a cada sessão)
                        if n_local == 0 or (n_cloud > 0 and n_local < n_cloud):
                            try:
                                bootstrap_msg = _bootstrap_local_from_cloud()
                            except Exception as e_boot:
                                bootstrap_msg = f"bootstrap falhou (app segue no local): {e_boot}"
                                logger.warning(bootstrap_msg)
                        else:
                            bootstrap_msg = (
                                f"bootstrap dispensado (local={n_local} cloud={n_cloud})"
                            )
                except Exception as e:
                    cloud_msg = f"conectado mas schema/query falhou: {e}"
                    logger.warning("init_db cloud schema/query | %s", str(e)[:160])
                    try:
                        _invalidate_cloud_conn()
                        _cloud_breaker_record_failure(e)
                    except Exception:
                        pass
                    try:
                        cloud.close()
                    except Exception:
                        pass
            else:
                cloud_msg = "URL encontrada mas conexão falhou (veja log)"
        else:
            cloud_msg = "SQLITECLOUD_URL ausente nos secrets"

        modo = "local+cloud" if cloud_ok else "local"
        logger.info(
            "init_db OK | modo=%s | cloud=%s | local_antes=%s | %s",
            modo,
            cloud_msg,
            n_local,
            bootstrap_msg,
        )

        st.session_state.db_status = {
            "modo": modo,
            "cloud_ok": cloud_ok,
            "cloud_msg": cloud_msg,
            "bootstrap": bootstrap_msg,
            "local_chamados_antes": n_local,
        }
        st.session_state._db_init_done = True
    except Exception as e:
        log_error("init_db falhou", e)
        st.error(f"Erro ao inicializar banco: {e}")


def _normalize_datetime_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["data_hora_abertura", "data_hora_inicio", "data_hora_conclusao"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _ler_sql_com_fallback(sql: str, prefer_cloud: bool = True):
    """
    Executa SELECT priorizando Cloud; se a conexão Cloud falhar (SSL/socket),
    invalida o cache, registra no circuit-breaker e lê do banco local.
    Nunca propaga erros transitórios do Cloud para a UI.
    """
    if prefer_cloud and is_cloud() and not _cloud_breaker_is_open():
        try:
            conn = get_cloud_connection()
            if conn is not None:
                # Usa cursor manual: pd.read_sql + driver sqlitecloud às vezes
                # devolve description=None após falha parcial de protocolo.
                cur = conn.cursor()
                cur.execute(sql)
                rows = cur.fetchall()
                cols = []
                if cur.description:
                    cols = [d[0] for d in cur.description]
                conn.close()
                _cloud_breaker_record_success()
                if not cols:
                    return pd.DataFrame()
                return pd.DataFrame(rows, columns=cols)
        except Exception as e:
            # Erros transitórios: log curto, sem traceback completo a cada 30s
            if _is_transient_cloud_error(e):
                logger.warning(
                    "leitura Cloud falhou (transiente), fallback local | sql=%s | %s",
                    sql[:50],
                    str(e)[:140],
                )
            else:
                log_error(f"leitura Cloud falhou, fallback local | sql={sql[:60]}", e)
            _invalidate_cloud_conn()
            _cloud_breaker_record_failure(e)

    local = get_local_connection()
    try:
        # Garante schema local antes de ler (corrige "no such table: config_sla" etc.)
        try:
            _ensure_schema(local)
        except Exception:
            pass
        df = pd.read_sql(sql, local)
    except Exception as e:
        msg = str(e).lower()
        if "no such table" in msg:
            # Tenta criar schema e reler uma vez
            try:
                _schema_ensured_conn_ids.discard(id(local))
                _ensure_schema(local)
                df = pd.read_sql(sql, local)
            except Exception as e2:
                log_error(f"leitura LOCAL falhou (após ensure) | sql={sql[:60]}", e2)
                df = pd.DataFrame()
        else:
            log_error(f"leitura LOCAL falhou | sql={sql[:60]}", e)
            df = pd.DataFrame()
    finally:
        try:
            local.close()
        except Exception:
            pass
    return df


def _df_to_chamado_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    df = _normalize_datetime_cols(df.copy())
    for col in [
        "data_hora_abertura",
        "data_hora_inicio",
        "data_hora_conclusao",
        "data_solicitacao_peca",
    ]:
        if col in df.columns:
            df[col] = df[col].apply(_fmt_data)
    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    for rec in records:
        for k, v in list(rec.items()):
            try:
                if v is not None and pd.isna(v):
                    rec[k] = None
            except (TypeError, ValueError):
                pass
            if k.startswith("data_") or "hora" in k:
                rec[k] = _fmt_data(v)
        try:
            if rec.get("id") is not None:
                rec["id"] = int(rec["id"])
        except (TypeError, ValueError):
            pass
    return records


def _ler_tabela_direto(conn, sql: str) -> pd.DataFrame:
    """SELECT via cursor (compatível com sqlitecloud)."""
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall() or []
        cols = [d[0] for d in (cur.description or [])]
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        return pd.DataFrame()


def carregar_dados() -> list[dict]:
    """
    Carrega chamados com união Local + Cloud (merge por id).
    Nunca abre conexão Cloud fora do cache (evita segfault no driver).
    Qualquer falha no Cloud cai para o local sem derrubar o app.
    """
    try:
        maps: dict[int, dict] = {}

        # 1) Local (sempre — base estável)
        try:
            local = get_local_connection()
            df_l = _ler_tabela_direto(local, "SELECT * FROM chamados")
            try:
                local.close()
            except Exception:
                pass
            for rec in _df_to_chamado_records(df_l):
                rid = rec.get("id")
                if rid is None:
                    continue
                try:
                    maps[int(rid)] = rec
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            logger.warning("carregar_dados LOCAL | %s", str(e)[:140])

        # 2) Cloud só via get_cloud_connection (cacheado) e se breaker fechado
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    df_c = _ler_tabela_direto(cloud, "SELECT * FROM chamados")
                    try:
                        cloud.close()
                    except Exception:
                        pass
                    for rec in _df_to_chamado_records(df_c):
                        rid = rec.get("id")
                        if rid is None:
                            continue
                        try:
                            rid = int(rid)
                        except (TypeError, ValueError):
                            continue
                        if rid in maps:
                            maps[rid] = _pick_chamado(maps[rid], rec)
                        else:
                            maps[rid] = rec
                    # Cacheia max id do cloud para proximo_id seguro
                    if maps:
                        try:
                            st.session_state["_cloud_max_chamado_id"] = max(maps.keys())
                        except Exception:
                            pass
                    _cloud_breaker_record_success()
            except Exception as e:
                logger.warning("carregar_dados CLOUD | %s", str(e)[:140])
                try:
                    _invalidate_cloud_conn()
                    _cloud_breaker_record_failure(e)
                except Exception:
                    pass

        records = list(maps.values())
        try:
            records.sort(key=lambda r: int(r.get("id") or 0))
        except Exception:
            pass
        return records
    except Exception as e:
        try:
            log_error("carregar_dados falhou", e)
        except Exception:
            pass
        return []


def _fmt_data(v):
    """Normaliza datas para string ISO (trata None, NaN, NaT, Timestamp)."""
    if v is None or v == "":
        return None
    # NaT / NA (pandas) — nunca chamar strftime em NaT
    try:
        if v is pd.NaT:
            return None
    except Exception:
        pass
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    # String já limpa
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in ("nat", "nan", "none", "null"):
            return None
        try:
            ts = pd.to_datetime(s, errors="coerce")
            if pd.isna(ts):
                return s  # mantém string original se não for data
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return s
    # datetime / Timestamp
    try:
        if hasattr(v, "strftime") and not pd.isna(v):
            # Timestamp com tz → naive
            if getattr(v, "tzinfo", None) is not None:
                try:
                    v = v.replace(tzinfo=None)
                except Exception:
                    pass
            return v.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError, AttributeError):
        pass
    try:
        ts = pd.to_datetime(v, errors="coerce")
        if pd.isna(ts):
            return None
        if getattr(ts, "tzinfo", None) is not None:
            try:
                ts = ts.tz_localize(None) if ts.tzinfo else ts
            except Exception:
                try:
                    ts = ts.replace(tzinfo=None)
                except Exception:
                    pass
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    s = str(v).strip()
    return s if s and s.lower() not in ("nat", "nan", "none", "null") else None


def _upsert_chamado_em(conn, campos: dict) -> None:
    """Executa INSERT ou UPDATE de um chamado em uma conexão."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM chamados WHERE id = ?", (campos["id"],))
    existe = cur.fetchone() is not None

    if existe:
        cur.execute(
            """
            UPDATE chamados SET
                solicitante=?, data_hora_abertura=?, setor=?, equipamento=?,
                prioridade=?, descricao=?, status=?, executante=?,
                data_hora_inicio=?, data_hora_conclusao=?, foto_path=?,
                solucao_descricao=?, foto_solucao_path=?, comentario_conclusao=?,
                peca_solicitada=?, peca_observacao=?, data_solicitacao_peca=?
            WHERE id=?
        """,
            (
                campos["solicitante"],
                campos["data_hora_abertura"],
                campos["setor"],
                campos["equipamento"],
                campos["prioridade"],
                campos["descricao"],
                campos["status"],
                campos["executante"],
                campos["data_hora_inicio"],
                campos["data_hora_conclusao"],
                campos["foto_path"],
                campos["solucao_descricao"],
                campos["foto_solucao_path"],
                campos["comentario_conclusao"],
                campos["peca_solicitada"],
                campos["peca_observacao"],
                campos["data_solicitacao_peca"],
                campos["id"],
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO chamados (
                id, solicitante, data_hora_abertura, setor, equipamento,
                prioridade, descricao, status, executante,
                data_hora_inicio, data_hora_conclusao, foto_path,
                solucao_descricao, foto_solucao_path, comentario_conclusao,
                peca_solicitada, peca_observacao, data_solicitacao_peca
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                campos["id"],
                campos["solicitante"],
                campos["data_hora_abertura"],
                campos["setor"],
                campos["equipamento"],
                campos["prioridade"],
                campos["descricao"],
                campos["status"],
                campos["executante"],
                campos["data_hora_inicio"],
                campos["data_hora_conclusao"],
                campos["foto_path"],
                campos["solucao_descricao"],
                campos["foto_solucao_path"],
                campos["comentario_conclusao"],
                campos["peca_solicitada"],
                campos["peca_observacao"],
                campos["data_solicitacao_peca"],
            ),
        )
    existentes = _colunas_tabela(conn, "chamados")
    extras = []
    vals = []
    for col in (
        "foto_url",
        "foto_solucao_url",
        "notificado_whatsapp",
        "contato_solicitante",
    ):
        if col in existentes and col in campos:
            extras.append(f"{col}=?")
            vals.append(campos.get(col))
    if extras:
        vals.append(campos["id"])
        cur.execute(
            f"UPDATE chamados SET {', '.join(extras)} WHERE id=?",
            tuple(vals),
        )
    conn.commit()


def _ler_chamado_por_id(conn, cid: int) -> dict | None:
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM chamados WHERE id = ?", (int(cid),))
        row = cur.fetchone()
        if not row or not cur.description:
            return None
        cols = [d[0] for d in cur.description]
        return _row_to_dict(row, cols)
    except Exception:
        return None


def salvar_chamado(chamado: dict) -> bool:
    """
    Upsert de um chamado no LOCAL e no CLOUD (dual-write).

    Antes de gravar no Cloud, faz merge com o registro já existente lá
    (se houver), para NUNCA sobrescrever um chamado do Cloud com uma
    versão incompleta vinda do disco local efêmero.
    """
    try:
        campos = {
            "id": chamado.get("id"),
            "solicitante": chamado.get("solicitante"),
            "data_hora_abertura": _fmt_data(chamado.get("data_hora_abertura")),
            "setor": chamado.get("setor"),
            "equipamento": chamado.get("equipamento"),
            "prioridade": chamado.get("prioridade"),
            "descricao": chamado.get("descricao"),
            "status": chamado.get("status"),
            "executante": chamado.get("executante") or "",
            "data_hora_inicio": _fmt_data(chamado.get("data_hora_inicio")),
            "data_hora_conclusao": _fmt_data(chamado.get("data_hora_conclusao")),
            "foto_path": chamado.get("foto_path"),
            "solucao_descricao": chamado.get("solucao_descricao") or "",
            "foto_solucao_path": chamado.get("foto_solucao_path"),
            "comentario_conclusao": chamado.get("comentario_conclusao") or "",
            "peca_solicitada": chamado.get("peca_solicitada") or "",
            "peca_observacao": chamado.get("peca_observacao") or "",
            "data_solicitacao_peca": _fmt_data(chamado.get("data_solicitacao_peca")),
            "foto_url": chamado.get("foto_url"),
            "foto_solucao_url": chamado.get("foto_solucao_url"),
            "notificado_whatsapp": chamado.get("notificado_whatsapp"),
            "contato_solicitante": chamado.get("contato_solicitante") or "",
        }

        # 1) Local — a alteração da UI (campos) SEMPRE prevalece no status.
        #    Campos vazios são preenchidos com o que já existia (não perde dado).
        local = get_local_connection()
        _ensure_schema(local)
        existente_local = _ler_chamado_por_id(local, campos["id"])
        if existente_local:
            campos_local = _merge_dicts_fieldwise(campos, existente_local)
            campos_local["status"] = campos["status"]  # status da UI vence
        else:
            campos_local = dict(campos)
        _upsert_chamado_em(local, campos_local)
        local.close()

        # 2) Cloud — mesma regra: status vindo da UI não pode ser revertido
        dual_ok = False
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    existente_cloud = _ler_chamado_por_id(cloud, campos["id"])
                    if existente_cloud:
                        campos_cloud = _merge_dicts_fieldwise(campos, existente_cloud)
                        campos_cloud["status"] = campos["status"]
                    else:
                        campos_cloud = dict(campos)
                    _upsert_chamado_em(cloud, campos_cloud)
                    cloud.close()
                    dual_ok = True
                    _cloud_breaker_record_success()
            except Exception as e_cloud:
                if _is_transient_cloud_error(e_cloud):
                    logger.warning(
                        "salvar_chamado CLOUD transiente id=%s | %s",
                        campos["id"],
                        str(e_cloud)[:140],
                    )
                else:
                    log_error(
                        f"salvar_chamado CLOUD id={campos['id']} falhou (local OK)",
                        e_cloud,
                    )
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e_cloud)

        logger.info(
            "salvar_chamado OK | id=%s status=%s | dual=%s",
            campos["id"],
            campos["status"],
            dual_ok,
        )
        return True
    except Exception as e:
        log_error(f"salvar_chamado id={chamado.get('id')} falhou", e)
        st.error(f"Erro ao salvar chamado: {e}")
        return False


def salvar_dados(chamados_list: list[dict]) -> bool:
    """
    Salva lista completa de forma segura (um a um com upsert).
    Mantém compatibilidade com o código legado que passa a lista inteira.
    """
    ok = True
    for c in chamados_list:
        if not salvar_chamado(c):
            ok = False
    return ok


def proximo_id_chamado() -> int:
    """
    Maior ID entre local e cloud + 1.
    Nunca abre conexão Cloud fora do cache.
    Se Cloud offline, usa max conhecido em session_state ou faixa segura.
    """
    ids = []
    cloud_max_ok = False
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM chamados")
        ids.append(int(cur.fetchone()[0] or 0))
        try:
            local.close()
        except Exception:
            pass
    except Exception as e:
        logger.warning("proximo_id local | %s", str(e)[:120])

    if is_cloud() and not _cloud_breaker_is_open():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM chamados")
                cmax = int(cur.fetchone()[0] or 0)
                ids.append(cmax)
                cloud_max_ok = True
                try:
                    st.session_state["_cloud_max_chamado_id"] = cmax
                except Exception:
                    pass
                try:
                    cloud.close()
                except Exception:
                    pass
        except Exception as e:
            logger.warning("proximo_id cloud | %s", str(e)[:120])
            try:
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e)
            except Exception:
                pass

    # Usa último max conhecido do cloud (sessão) se a consulta falhou
    try:
        cached = st.session_state.get("_cloud_max_chamado_id")
        if cached is not None:
            ids.append(int(cached))
    except Exception:
        pass

    base = max(ids) if ids else 0
    if is_cloud() and not cloud_max_ok and not ids:
        import time

        base = max(base, 1_000_000 + (int(time.time()) % 100000))
        logger.warning("proximo_id: Cloud offline — faixa segura base=%s", base)
    elif is_cloud() and not cloud_max_ok and base < 1000:
        # Local quase vazio e cloud inacessível: evita id baixo
        try:
            cached = int(st.session_state.get("_cloud_max_chamado_id") or 0)
        except Exception:
            cached = 0
        if cached > base:
            base = cached
        else:
            import time

            base = max(base, 1_000_000 + (int(time.time()) % 100000))
    return int(base) + 1


def carregar_equipe() -> pd.DataFrame:
    try:
        df = _ler_sql_com_fallback("SELECT * FROM equipe")
        return df
    except Exception as e:
        log_error("carregar_equipe falhou", e)
        return pd.DataFrame(columns=["id", "nome", "funcao", "contato", "ativo"])


def _write_equipe_em(conn, df: pd.DataFrame):
    cur = conn.cursor()
    cur.execute("DELETE FROM equipe")
    for _, row in df.iterrows():
        cur.execute(
            "INSERT INTO equipe (id, nome, funcao, contato, ativo) VALUES (?,?,?,?,?)",
            (
                int(row["id"]) if pd.notnull(row.get("id")) else None,
                row.get("nome"),
                row.get("funcao"),
                row.get("contato"),
                int(row.get("ativo", 1)),
            ),
        )
    conn.commit()


def salvar_equipe(df: pd.DataFrame) -> bool:
    """Salva equipe no local e no cloud."""
    try:
        local = get_local_connection()
        _ensure_schema(local)
        _write_equipe_em(local, df)
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _write_equipe_em(cloud, df)
                cloud.close()
        logger.info("salvar_equipe OK | %d registros | dual=%s", len(df), is_cloud())
        return True
    except Exception as e:
        log_error("salvar_equipe falhou", e)
        st.error(f"Erro ao salvar equipe: {e}")
        return False


def adicionar_membro_equipe(nome: str, funcao: str, contato: str) -> bool:
    try:
        # ID a partir do local
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM equipe")
        novo_id = cur.fetchone()[0]
        local.close()

        sql = "INSERT INTO equipe (id, nome, funcao, contato, ativo) VALUES (?,?,?,?,1)"
        params = (novo_id, nome, funcao, contato)

        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()

        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()

        logger.info("adicionar_membro_equipe OK | %s", nome)
        return True
    except Exception as e:
        log_error("adicionar_membro_equipe falhou", e)
        st.error(f"Erro ao cadastrar membro: {e}")
        return False


def _proximo_id_equipe() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM equipe")
        ids.append(int(cur.fetchone()[0] or 0))
        try:
            local.close()
        except Exception:
            pass
    except Exception:
        pass
    if is_cloud() and not _cloud_breaker_is_open():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM equipe")
                ids.append(int(cur.fetchone()[0] or 0))
                try:
                    cloud.close()
                except Exception:
                    pass
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def _upsert_membro_em(
    conn, membro_id: int, nome: str, funcao: str, contato: str, ativo: int
) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM equipe WHERE id = ?", (int(membro_id),))
    existe = cur.fetchone() is not None
    if existe:
        cur.execute(
            "UPDATE equipe SET nome = ?, funcao = ?, contato = ?, ativo = ? WHERE id = ?",
            (nome, funcao, contato, int(ativo), int(membro_id)),
        )
    else:
        cur.execute(
            "INSERT INTO equipe (id, nome, funcao, contato, ativo) VALUES (?,?,?,?,?)",
            (int(membro_id), nome, funcao, contato, int(ativo)),
        )
    conn.commit()


def atualizar_membro_equipe(
    membro_id,
    nome: str,
    funcao: str,
    contato: str,
    ativo: int = 1,
) -> bool:
    """
    Atualiza membro da equipe. Se não houver id (None/vazio), gera um novo
    e faz INSERT — assim registros legados sem id passam a ter.
    """
    try:
        nome_l = (nome or "").strip()
        if not nome_l:
            st.error("Informe o nome.")
            return False

        # Normaliza id
        mid = None
        try:
            if membro_id is not None and str(membro_id).strip() not in (
                "",
                "None",
                "nan",
                "NaN",
            ):
                mid = int(float(membro_id))
        except (TypeError, ValueError):
            mid = None

        if mid is None:
            mid = _proximo_id_equipe()
            logger.info("atualizar_membro_equipe: gerando novo id=%s para '%s'", mid, nome_l)

        local = get_local_connection()
        _ensure_schema(local)
        _upsert_membro_em(local, mid, nome_l, funcao or "", contato or "", int(ativo))
        try:
            local.close()
        except Exception:
            pass

        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_membro_em(cloud, mid, nome_l, funcao or "", contato or "", int(ativo))
                    try:
                        cloud.close()
                    except Exception:
                        pass
            except Exception as e_cloud:
                logger.warning("atualizar_membro_equipe CLOUD | %s", str(e_cloud)[:140])
                try:
                    _invalidate_cloud_conn()
                    _cloud_breaker_record_failure(e_cloud)
                except Exception:
                    pass

        logger.info("atualizar_membro_equipe OK | id=%s nome=%s", mid, nome_l)
        return True
    except Exception as e:
        log_error("atualizar_membro_equipe falhou", e)
        st.error(f"Erro ao atualizar membro: {e}")
        return False


def excluir_membro_equipe(membro_id: int) -> bool:
    try:
        sql = "DELETE FROM equipe WHERE id = ?"
        params = (membro_id,)
        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()
        return True
    except Exception as e:
        log_error("excluir_membro_equipe falhou", e)
        return False


def carregar_setores() -> list[str]:
    default_setores = [
        "Fracionamento 1",
        "Fracionamento 2",
        "Mistura 1",
        "Mistura 2",
        "Mistura 3",
        "Mistura 4",
        "Envase 1",
        "Envase 2",
        "RH 1",
        "Laboratório",
        "Outros",
    ]
    try:
        df = _ler_sql_com_fallback("SELECT setor FROM setores ORDER BY setor")
        if df.empty:
            # popula defaults na primeira execução
            salvar_setores(default_setores)
            return default_setores
        return df["setor"].dropna().tolist()
    except Exception as e:
        log_error("carregar_setores falhou", e)
        return default_setores


def _write_setores_em(conn, lista: list[str]):
    # Garante coluna id (bancos legados)
    try:
        _migrar_setores(conn)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("DELETE FROM setores")
    for i, s in enumerate(lista, start=1):
        if s and str(s).strip():
            cur.execute(
                "INSERT INTO setores (id, setor) VALUES (?,?)",
                (i, str(s).strip()),
            )
    conn.commit()


def salvar_setores(lista: list[str]) -> bool:
    try:
        local = get_local_connection()
        _ensure_schema(local)
        _write_setores_em(local, lista)
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _write_setores_em(cloud, lista)
                cloud.close()
        logger.info("salvar_setores OK | %d itens | dual=%s", len(lista), is_cloud())
        return True
    except Exception as e:
        log_error("salvar_setores falhou", e)
        st.error(f"Erro ao salvar setores: {e}")
        return False


def carregar_equipamentos() -> list[dict]:
    try:
        df = _ler_sql_com_fallback("SELECT * FROM equipamentos")
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_equipamentos falhou", e)
        return []


def _upsert_equipamento_em(conn, eq: dict):
    cur = conn.cursor()
    eq_id = eq.get("id")
    cur.execute("SELECT 1 FROM equipamentos WHERE id = ?", (eq_id,))
    existe = cur.fetchone() is not None
    vals = (
        eq.get("nome"),
        eq.get("marca"),
        eq.get("modelo"),
        eq.get("ano_aquisicao"),
        eq.get("numero_patrimonio"),
        eq.get("setor"),
        eq.get("sazonalidade_meses"),
        eq.get("ultima_preventiva"),
        eq.get("proxima_preventiva"),
        eq.get("silenciar_ate"),
    )
    if existe:
        cur.execute(
            """
            UPDATE equipamentos SET
                nome=?, marca=?, modelo=?, ano_aquisicao=?,
                numero_patrimonio=?, setor=?, sazonalidade_meses=?,
                ultima_preventiva=?, proxima_preventiva=?, silenciar_ate=?
            WHERE id=?
        """,
            (*vals, eq_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO equipamentos (
                id, nome, marca, modelo, ano_aquisicao, numero_patrimonio,
                setor, sazonalidade_meses, ultima_preventiva, proxima_preventiva,
                silenciar_ate
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
            (eq_id, *vals),
        )
    conn.commit()


def salvar_equipamento(eq: dict) -> bool:
    """Upsert de equipamento no local e no cloud."""
    try:
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_equipamento_em(local, eq)
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                _ensure_schema(cloud)
                _upsert_equipamento_em(cloud, eq)
                cloud.close()
        logger.info("salvar_equipamento OK | id=%s | dual=%s", eq.get("id"), is_cloud())
        return True
    except Exception as e:
        log_error("salvar_equipamento falhou", e)
        st.error(f"Erro ao salvar equipamento: {e}")
        return False


def excluir_equipamento(eq_id: int) -> bool:
    try:
        sql = "DELETE FROM equipamentos WHERE id = ?"
        params = (eq_id,)
        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()
        if is_cloud():
            cloud = get_cloud_connection()
            if cloud is not None:
                cloud.execute(sql, params)
                cloud.commit()
                cloud.close()
        return True
    except Exception as e:
        log_error("excluir_equipamento falhou", e)
        return False


def proximo_id_equipamento() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM equipamentos")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception:
        pass
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM equipamentos")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def nome_equipamento(eq: dict) -> str:
    return eq.get("nome") or eq.get("Equipamento") or "N/A"


def proximo_id_manutencao() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM manutencoes_historico")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception:
        pass
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM manutencoes_historico")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def _upsert_manutencao_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO manutencoes_historico (
            id, equipamento_id, equipamento_nome, tipo, data_manutencao,
            executante, descricao, pecas_trocadas, custo_pecas, horas_homem,
            chamado_id, observacao, checklist_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            reg["id"],
            reg.get("equipamento_id"),
            reg.get("equipamento_nome"),
            reg.get("tipo"),
            reg.get("data_manutencao"),
            reg.get("executante") or "",
            reg.get("descricao") or "",
            reg.get("pecas_trocadas") or "",
            float(reg.get("custo_pecas") or 0),
            float(reg.get("horas_homem") or 0),
            reg.get("chamado_id"),
            reg.get("observacao") or "",
            reg.get("checklist_json") or "",
        ),
    )
    conn.commit()


def salvar_manutencao(reg: dict) -> bool:
    """Persiste registro de manutenção no local e no cloud."""
    try:
        if not reg.get("id"):
            reg["id"] = proximo_id_manutencao()
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_manutencao_em(local, reg)
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_manutencao_em(cloud, reg)
                    cloud.close()
                    _cloud_breaker_record_success()
            except Exception as e_cloud:
                if _is_transient_cloud_error(e_cloud):
                    logger.warning(
                        "salvar_manutencao CLOUD transiente id=%s | %s",
                        reg.get("id"),
                        str(e_cloud)[:140],
                    )
                else:
                    log_error(f"salvar_manutencao CLOUD id={reg.get('id')} falhou", e_cloud)
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e_cloud)
        logger.info(
            "salvar_manutencao OK | id=%s tipo=%s eq=%s",
            reg.get("id"),
            reg.get("tipo"),
            reg.get("equipamento_nome"),
        )
        return True
    except Exception as e:
        log_error("salvar_manutencao falhou", e)
        st.error(f"Erro ao salvar manutenção: {e}")
        return False


def carregar_historico_manutencao(equipamento_id: int | None = None) -> list[dict]:
    """
    Histórico de manutenções.
    Por padrão lê só o LOCAL (rápido e estável). O bootstrap Cloud→Local
    já repõe o disco no startup. Consultas por equipamento em loop na UI
    não devem abrir dezenas de conexões Cloud (causava SSL/crash).
    """
    try:
        if equipamento_id is not None:
            sql = (
                "SELECT * FROM manutencoes_historico "
                f"WHERE equipamento_id = {int(equipamento_id)} "
                "ORDER BY data_manutencao DESC"
            )
        else:
            sql = "SELECT * FROM manutencoes_historico ORDER BY data_manutencao DESC"

        # Preferência: local (estável). Cloud só se local vazio e breaker fechado.
        local = get_local_connection()
        df = _ler_tabela_direto(local, sql)
        try:
            local.close()
        except Exception:
            pass

        if df.empty and is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    df = _ler_tabela_direto(cloud, sql)
                    try:
                        cloud.close()
                    except Exception:
                        pass
                    # Reinsere no local o que veio do cloud (sem apagar)
                    if not df.empty and equipamento_id is None:
                        try:
                            loc = get_local_connection()
                            cols = list(df.columns)
                            for rec in df.where(pd.notnull(df), None).to_dict(orient="records"):
                                _upsert_row_generic(loc, "manutencoes_historico", rec, cols)
                            try:
                                loc.commit()
                            except Exception:
                                pass
                            try:
                                loc.close()
                            except Exception:
                                pass
                        except Exception:
                            pass
            except Exception as e:
                logger.warning("historico CLOUD | %s", str(e)[:120])
                try:
                    _invalidate_cloud_conn()
                    _cloud_breaker_record_failure(e)
                except Exception:
                    pass

        if df is None or df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        try:
            log_error("carregar_historico_manutencao falhou", e)
        except Exception:
            pass
        return []


# ====================== COMPRAS DE PEÇAS ======================
def proximo_id_compra() -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM compras_pecas")
        ids.append(int(cur.fetchone()[0]))
        local.close()
    except Exception:
        pass
    if is_cloud():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM compras_pecas")
                ids.append(int(cur.fetchone()[0]))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def parse_cotacoes(reg: dict | None) -> list[dict]:
    """Lê lista de cotações de um registro de compra (JSON em cotacoes_json)."""
    import json

    if not reg:
        return []
    raw = reg.get("cotacoes_json")
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    try:
        data = json.loads(str(raw))
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
    except Exception:
        pass
    return []


def serialize_cotacoes(cotacoes: list[dict] | None) -> str:
    """Serializa lista de cotações para JSON (coluna cotacoes_json)."""
    import json

    if not cotacoes:
        return "[]"
    limpas = []
    for c in cotacoes:
        if not isinstance(c, dict):
            continue
        limpas.append(
            {
                "fornecedor": str(c.get("fornecedor") or "").strip(),
                "valor": float(c.get("valor") or 0),
                "prazo_dias": int(c.get("prazo_dias") or 0),
                "link": str(c.get("link") or "").strip(),
                "observacao": str(c.get("observacao") or "").strip(),
                "data": str(c.get("data") or "").strip(),
                "registrado_por": str(c.get("registrado_por") or "").strip(),
            }
        )
    return json.dumps(limpas, ensure_ascii=False)


def adicionar_cotacao(
    compra: dict,
    fornecedor: str,
    valor: float = 0.0,
    prazo_dias: int = 0,
    link: str = "",
    observacao: str = "",
    registrado_por: str = "",
) -> dict | None:
    """
    Acrescenta uma cotação à compra e grava.
    Move status Pendente → Em Cotação automaticamente.
    """
    try:
        forn = (fornecedor or "").strip()
        if not forn:
            st.error("Informe o fornecedor da cotação.")
            return None
        cotacoes = parse_cotacoes(compra)
        cotacoes.append(
            {
                "fornecedor": forn,
                "valor": float(valor or 0),
                "prazo_dias": int(prazo_dias or 0),
                "link": (link or "").strip(),
                "observacao": (observacao or "").strip(),
                "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "registrado_por": (registrado_por or "").strip(),
            }
        )
        compra["cotacoes_json"] = serialize_cotacoes(cotacoes)
        st_atual = str(compra.get("status") or "Pendente")
        if st_atual in ("Pendente", ""):
            compra["status"] = "Em Cotação"
        if registrado_por and not compra.get("comprador"):
            compra["comprador"] = registrado_por.strip()
        if salvar_compra(compra):
            return compra
        return None
    except Exception as e:
        log_error("adicionar_cotacao falhou", e)
        st.error(f"Erro ao adicionar cotação: {e}")
        return None


def remover_cotacao(compra: dict, indice: int) -> dict | None:
    """Remove cotação pelo índice e grava."""
    try:
        cotacoes = parse_cotacoes(compra)
        if indice < 0 or indice >= len(cotacoes):
            st.error("Índice de cotação inválido.")
            return None
        escolhida = compra.get("cotacao_escolhida")
        try:
            escolhida = int(escolhida) if escolhida is not None else None
        except (TypeError, ValueError):
            escolhida = None
        cotacoes.pop(indice)
        compra["cotacoes_json"] = serialize_cotacoes(cotacoes)
        if escolhida is not None:
            if escolhida == indice:
                compra["cotacao_escolhida"] = None
            elif escolhida > indice:
                compra["cotacao_escolhida"] = escolhida - 1
        if salvar_compra(compra):
            return compra
        return None
    except Exception as e:
        log_error("remover_cotacao falhou", e)
        return None


def _upsert_compra_em(conn, reg: dict) -> None:
    # Garante colunas de cotação em bancos legados
    try:
        _migrar_colunas_compras(conn)
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM compras_pecas WHERE id = ?", (reg["id"],))
    existe = cur.fetchone() is not None
    cot_json = reg.get("cotacoes_json")
    if isinstance(cot_json, list):
        cot_json = serialize_cotacoes(cot_json)
    elif cot_json is None:
        cot_json = "[]"
    else:
        cot_json = str(cot_json)
    cot_esc = reg.get("cotacao_escolhida")
    try:
        cot_esc = int(cot_esc) if cot_esc is not None and str(cot_esc).strip() != "" else None
    except (TypeError, ValueError):
        cot_esc = None
    vals = (
        reg.get("chamado_id"),
        reg.get("equipamento") or "",
        reg.get("prioridade") or "",
        reg.get("item_nome") or "",
        reg.get("link_compra") or "",
        reg.get("observacao") or "",
        reg.get("solicitante") or "",
        reg.get("prazo_recebimento"),
        reg.get("status") or "Pendente",
        reg.get("aprovado") or "",
        reg.get("dias_para_chegada"),
        float(reg.get("valor_item") or 0),
        reg.get("data_solicitacao"),
        reg.get("data_aprovacao"),
        reg.get("data_recebimento"),
        reg.get("comprador") or "",
        reg.get("observacao_compras") or "",
        cot_json,
        cot_esc,
    )
    if existe:
        cur.execute(
            """
            UPDATE compras_pecas SET
                chamado_id=?, equipamento=?, prioridade=?, item_nome=?,
                link_compra=?, observacao=?, solicitante=?, prazo_recebimento=?,
                status=?, aprovado=?, dias_para_chegada=?, valor_item=?,
                data_solicitacao=?, data_aprovacao=?, data_recebimento=?,
                comprador=?, observacao_compras=?, cotacoes_json=?,
                cotacao_escolhida=?
            WHERE id=?
            """,
            (*vals, reg["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO compras_pecas (
                id, chamado_id, equipamento, prioridade, item_nome,
                link_compra, observacao, solicitante, prazo_recebimento,
                status, aprovado, dias_para_chegada, valor_item,
                data_solicitacao, data_aprovacao, data_recebimento,
                comprador, observacao_compras, cotacoes_json, cotacao_escolhida
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (reg["id"], *vals),
        )
    conn.commit()


def salvar_compra(reg: dict) -> bool:
    try:
        if not reg.get("id"):
            reg["id"] = proximo_id_compra()
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_compra_em(local, reg)
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_compra_em(cloud, reg)
                    cloud.close()
                    _cloud_breaker_record_success()
            except Exception as e_cloud:
                if _is_transient_cloud_error(e_cloud):
                    logger.warning(
                        "salvar_compra CLOUD transiente id=%s | %s",
                        reg.get("id"),
                        str(e_cloud)[:140],
                    )
                else:
                    log_error(f"salvar_compra CLOUD id={reg.get('id')} falhou", e_cloud)
                _invalidate_cloud_conn()
                _cloud_breaker_record_failure(e_cloud)
        # Ao marcar como Recebida, lança entrada no almoxarifado (idempotente)
        try:
            if str(reg.get("status") or "").strip() == "Recebida":
                entrada_estoque_de_compra(reg)
        except Exception as e_est:
            log_error("entrada_estoque_de_compra (pos salvar_compra) falhou", e_est)
        logger.info(
            "salvar_compra OK | id=%s item=%s status=%s",
            reg.get("id"),
            reg.get("item_nome"),
            reg.get("status"),
        )
        return True
    except Exception as e:
        log_error("salvar_compra falhou", e)
        st.error(f"Erro ao salvar solicitação de compra: {e}")
        return False


def carregar_compras(status: str | None = None) -> list[dict]:
    try:
        if status:
            sql = (
                "SELECT * FROM compras_pecas WHERE status = "
                f"'{str(status).replace(chr(39), '')}' "
                "ORDER BY data_solicitacao DESC"
            )
        else:
            sql = "SELECT * FROM compras_pecas ORDER BY data_solicitacao DESC"
        df = _ler_sql_com_fallback(sql)
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_compras falhou", e)
        return []


def carregar_compras_por_chamado(chamado_id: int) -> list[dict]:
    try:
        sql = (
            "SELECT * FROM compras_pecas WHERE chamado_id = "
            f"{int(chamado_id)} ORDER BY data_solicitacao DESC"
        )
        df = _ler_sql_com_fallback(sql)
        if df.empty:
            return []
        return df.where(pd.notnull(df), None).to_dict(orient="records")
    except Exception as e:
        log_error("carregar_compras_por_chamado falhou", e)
        return []


def historico_compras_item(item_nome: str, equipamento: str | None = None) -> list[dict]:
    """Compras anteriores do mesmo item (opcionalmente no mesmo equipamento)."""
    try:
        todas = carregar_compras()
        nome = (item_nome or "").strip().lower()
        if not nome:
            return []
        hist = []
        for c in todas:
            if (c.get("item_nome") or "").strip().lower() != nome:
                continue
            if c.get("status") not in ("Aprovada", "Recebida", "Comprada"):
                # inclui também rejeitadas para contexto? só compradas/recebidas
                if c.get("aprovado") != "Sim":
                    continue
            hist.append(c)
        if equipamento:
            eq = equipamento.strip().lower()
            hist_eq = [h for h in hist if (h.get("equipamento") or "").strip().lower() == eq]
            # prioriza mesmo equipamento, depois outros
            outros = [h for h in hist if h not in hist_eq]
            hist = hist_eq + outros
        return hist
    except Exception as e:
        log_error("historico_compras_item falhou", e)
        return []


def criar_solicitacao_compra_do_chamado(
    cham: dict,
    item_nome: str,
    link_compra: str = "",
    observacao: str = "",
    prazo_recebimento: str | None = None,
    solicitante: str = "",
) -> dict | None:
    """Gera solicitação de compra vinculada ao chamado (status Pendente)."""
    reg = {
        "id": proximo_id_compra(),
        "chamado_id": cham.get("id"),
        "equipamento": cham.get("equipamento") or "",
        "prioridade": cham.get("prioridade") or "",
        "item_nome": item_nome.strip(),
        "link_compra": (link_compra or "").strip(),
        "observacao": (observacao or "").strip(),
        "solicitante": (solicitante or cham.get("executante") or "").strip(),
        "prazo_recebimento": prazo_recebimento,
        "status": "Pendente",
        "aprovado": "",
        "dias_para_chegada": None,
        "valor_item": 0,
        "data_solicitacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_aprovacao": None,
        "data_recebimento": None,
        "comprador": "",
        "observacao_compras": "",
    }
    if salvar_compra(reg):
        return reg
    return None


def _notificar_chamado_compra(chamado_id: int, texto: str) -> None:
    """Anexa notificação no comentário do chamado e grava."""
    try:
        chamados = st.session_state.get("chamados") or carregar_dados()
        for c in chamados:
            if c.get("id") == chamado_id:
                base = (c.get("comentario_conclusao") or "").strip()
                stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
                novo = f"{base}\n[{stamp} COMPRAS] {texto}".strip()
                c["comentario_conclusao"] = novo
                # também reforça observação da peça
                obs = (c.get("peca_observacao") or "").strip()
                c["peca_observacao"] = f"{obs}\n[{stamp}] {texto}".strip()
                salvar_chamado(c)
                break
        st.session_state.chamados = carregar_dados()
    except Exception as e:
        log_error("_notificar_chamado_compra falhou", e)


def concluir_preventiva(
    eq: dict,
    executante: str = "",
    descricao: str = "",
    pecas: str = "",
    custo_pecas: float = 0.0,
    horas_homem: float = 0.0,
    observacao: str = "",
    checklist_json: str = "",
) -> bool:
    """
    Marca preventiva como feita: atualiza ultima/proxima_preventiva,
    limpa silenciar_ate e grava no histórico.
    checklist_json: JSON com itens {texto: {sim: bool, obs: str}}
    """
    try:
        hoje = datetime.now().date()
        meses = int(eq.get("sazonalidade_meses") or 6)
        prox = (hoje + timedelta(days=meses * 30)).isoformat()
        eq["ultima_preventiva"] = hoje.isoformat()
        eq["proxima_preventiva"] = prox
        eq["silenciar_ate"] = None
        if not salvar_equipamento(eq):
            return False
        reg = {
            "id": proximo_id_manutencao(),
            "equipamento_id": eq.get("id"),
            "equipamento_nome": nome_equipamento(eq),
            "tipo": "Preventiva",
            "data_manutencao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "executante": executante,
            "descricao": descricao or "Manutenção preventiva concluída",
            "pecas_trocadas": pecas,
            "custo_pecas": custo_pecas,
            "horas_homem": horas_homem,
            "chamado_id": None,
            "observacao": observacao,
            "checklist_json": checklist_json or "",
        }
        return salvar_manutencao(reg)
    except Exception as e:
        log_error("concluir_preventiva falhou", e)
        st.error(f"Erro ao concluir preventiva: {e}")
        return False


def adiar_alerta_preventiva(eq: dict, dias: int = 7) -> bool:
    """Silencia o alerta preventivo até hoje + N dias."""
    try:
        ate = (datetime.now().date() + timedelta(days=int(dias))).isoformat()
        eq["silenciar_ate"] = ate
        return salvar_equipamento(eq)
    except Exception as e:
        log_error("adiar_alerta_preventiva falhou", e)
        st.error(f"Erro ao adiar alerta: {e}")
        return False


def custo_e_horas_por_equipamento(
    historico: list[dict] | None = None,
    chamados: list[dict] | None = None,
) -> pd.DataFrame:
    """
    Consolida custo de peças e horas-homem por equipamento
    (histórico de manutenções + chamados concluídos).
    """
    rows: dict[str, dict] = {}

    def _acc(nome: str, custo: float, horas: float, n: int = 1):
        if not nome or nome == "N/A":
            return
        if nome not in rows:
            rows[nome] = {
                "Equipamento": nome,
                "Custo Peças (R$)": 0.0,
                "Horas-Homem": 0.0,
                "Qtd Manutenções": 0,
            }
        rows[nome]["Custo Peças (R$)"] += float(custo or 0)
        rows[nome]["Horas-Homem"] += float(horas or 0)
        rows[nome]["Qtd Manutenções"] += n

    if historico is None:
        historico = carregar_historico_manutencao()
    for h in historico:
        _acc(
            h.get("equipamento_nome") or "N/A",
            h.get("custo_pecas") or 0,
            h.get("horas_homem") or 0,
        )

    if chamados is None:
        chamados = st.session_state.get("chamados") or []
    for c in chamados:
        if c.get("status") != "Concluído":
            continue
        nome = c.get("equipamento") or "N/A"
        horas = 0.0
        try:
            ini_raw = c.get("data_hora_inicio")
            fim_raw = c.get("data_hora_conclusao")
            if ini_raw and fim_raw:
                ini = pd.to_datetime(ini_raw, errors="coerce")
                fim = pd.to_datetime(fim_raw, errors="coerce")
                if pd.notna(ini) and pd.notna(fim) and fim >= ini:
                    horas = (fim - ini).total_seconds() / 3600.0
        except Exception:
            horas = 0.0
        # Chamados concluídos contribuem com horas; custo de peça fica no histórico
        _acc(nome, 0.0, horas, n=1)

    if not rows:
        return pd.DataFrame(
            columns=["Equipamento", "Custo Peças (R$)", "Horas-Homem", "Qtd Manutenções"]
        )
    df = pd.DataFrame(list(rows.values()))
    df["Custo Peças (R$)"] = df["Custo Peças (R$)"].round(2)
    df["Horas-Homem"] = df["Horas-Homem"].round(2)
    return df.sort_values("Custo Peças (R$)", ascending=False)


# ====================== CONFIG SLA ======================
_SLA_DEFAULT = {
    "Crítica": 20,
    "Alta": 60,
    "Média": 240,
    "Baixa": 1440,
}


def carregar_sla() -> dict:
    """Retorna {prioridade: minutos}. Fallback para padrão se vazio."""
    try:
        df = _ler_sql_com_fallback("SELECT prioridade, minutos FROM config_sla")
        if df is None or df.empty:
            return dict(_SLA_DEFAULT)
        out = dict(_SLA_DEFAULT)
        for _, row in df.iterrows():
            p = str(row.get("prioridade") or "").strip()
            try:
                m = int(float(row.get("minutos")))
            except (TypeError, ValueError):
                continue
            if p and m > 0:
                out[p] = m
        return out
    except Exception as e:
        logger.warning("carregar_sla | %s", str(e)[:120])
        return dict(_SLA_DEFAULT)


def salvar_sla(mapa: dict) -> bool:
    """Grava metas de SLA (minutos por prioridade) no local e cloud."""
    try:
        rows = []
        for p, m in (mapa or {}).items():
            p = str(p).strip()
            try:
                m = int(m)
            except (TypeError, ValueError):
                continue
            if p and m > 0:
                rows.append((p, m))
        if not rows:
            return False

        def _write(conn):
            _ensure_schema(conn)
            cur = conn.cursor()
            for p, m in rows:
                cur.execute(
                    "INSERT OR REPLACE INTO config_sla (prioridade, minutos) VALUES (?, ?)",
                    (p, m),
                )
            conn.commit()

        local = get_local_connection()
        _write(local)
        try:
            local.close()
        except Exception:
            pass

        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _write(cloud)
                    try:
                        cloud.close()
                    except Exception:
                        pass
            except Exception as e_cloud:
                logger.warning("salvar_sla CLOUD | %s", str(e_cloud)[:120])
                try:
                    _invalidate_cloud_conn()
                    _cloud_breaker_record_failure(e_cloud)
                except Exception:
                    pass
        logger.info("salvar_sla OK | %s", rows)
        return True
    except Exception as e:
        log_error("salvar_sla falhou", e)
        try:
            st.error(f"Erro ao salvar SLA: {e}")
        except Exception:
            pass
        return False


# ====================== ALMOXARIFADO / INVENTÁRIO MANUTENÇÃO ======================

ALMOX_CATEGORIAS = [
    "Peça / Componente",
    "Lubrificante",
    "Retentor",
    "Cabeamento",
    "Plug / Conector",
    "Conexão Pneumática",
    "Lâmpada",
    "Ferramenta",
    "Consumível",
    "Outro",
]

ALMOX_UNIDADES = ["UN", "PC", "KG", "L", "M", "CX", "KIT", "PAR"]

ALMOX_TIPOS_MOV = [
    "Entrada",
    "Saída",
    "Baixa quebrado",
    "Ajuste",
    "Transferência para maleta",
    "Retorno da maleta",
]


def _row_from_cursor(cur, row) -> dict:
    """Converte row do cursor atual em dict (não sobrescreve _row_to_dict(row, cols))."""
    if row is None:
        return {}
    if hasattr(row, "keys"):
        try:
            return {k: row[k] for k in row.keys()}
        except Exception:
            pass
    cols = [d[0] for d in (cur.description or [])] if cur is not None else []
    if not cols:
        return {}
    return _row_to_dict(row, cols)


def _proximo_id_tabela(tabela: str) -> int:
    ids = []
    try:
        local = get_local_connection()
        cur = local.cursor()
        cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {tabela}")
        ids.append(int(cur.fetchone()[0] or 0))
        local.close()
    except Exception:
        pass
    if is_cloud() and not _cloud_breaker_is_open():
        try:
            cloud = get_cloud_connection()
            if cloud is not None:
                cur = cloud.cursor()
                cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {tabela}")
                ids.append(int(cur.fetchone()[0] or 0))
                cloud.close()
        except Exception:
            pass
    return (max(ids) + 1) if ids else 1


def proximo_id_almox_item() -> int:
    return _proximo_id_tabela("almox_itens")


def proximo_id_almox_maleta() -> int:
    return _proximo_id_tabela("almox_maletas")


def proximo_id_almox_maleta_item() -> int:
    return _proximo_id_tabela("almox_maleta_itens")


def proximo_id_almox_mov() -> int:
    return _proximo_id_tabela("almox_movimentacoes")


def _upsert_almox_item_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM almox_itens WHERE id = ?", (reg["id"],))
    existe = cur.fetchone() is not None
    vals = (
        reg.get("codigo") or "",
        reg.get("nome") or "",
        reg.get("categoria") or "Outro",
        reg.get("subcategoria") or "",
        reg.get("unidade") or "UN",
        float(reg.get("quantidade") or 0),
        float(reg.get("estoque_min") or 0),
        reg.get("localizacao") or "",
        reg.get("setor") or "",
        reg.get("equipamento_ref") or "",
        reg.get("especificacao") or "",
        reg.get("observacao") or "",
        int(reg.get("ativo") if reg.get("ativo") is not None else 1),
        reg.get("data_cadastro") or datetime.now().isoformat(),
        reg.get("data_atualizacao") or datetime.now().isoformat(),
    )
    if existe:
        cur.execute(
            """
            UPDATE almox_itens SET
                codigo=?, nome=?, categoria=?, subcategoria=?, unidade=?,
                quantidade=?, estoque_min=?, localizacao=?, setor=?,
                equipamento_ref=?, especificacao=?, observacao=?, ativo=?,
                data_cadastro=?, data_atualizacao=?
            WHERE id=?
            """,
            (*vals, reg["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO almox_itens (
                id, codigo, nome, categoria, subcategoria, unidade,
                quantidade, estoque_min, localizacao, setor,
                equipamento_ref, especificacao, observacao, ativo,
                data_cadastro, data_atualizacao
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (reg["id"], *vals),
        )
    conn.commit()


def salvar_almox_item(reg: dict) -> bool:
    try:
        if not reg.get("id"):
            reg["id"] = proximo_id_almox_item()
        agora = datetime.now().isoformat()
        if not reg.get("data_cadastro"):
            reg["data_cadastro"] = agora
        reg["data_atualizacao"] = agora
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_almox_item_em(local, reg)
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_almox_item_em(cloud, reg)
                    cloud.close()
                    _cloud_breaker_record_success()
            except Exception as e_cloud:
                logger.warning("salvar_almox_item CLOUD | %s", str(e_cloud)[:120])
                try:
                    _invalidate_cloud_conn()
                    _cloud_breaker_record_failure(e_cloud)
                except Exception:
                    pass
        return True
    except Exception as e:
        log_error("salvar_almox_item falhou", e)
        return False


def carregar_almox_itens(
    categoria: str | None = None,
    setor: str | None = None,
    apenas_ativos: bool = True,
    abaixo_minimo: bool = False,
) -> list[dict]:
    try:
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        sql = "SELECT * FROM almox_itens WHERE 1=1"
        params: list = []
        if apenas_ativos:
            sql += " AND COALESCE(ativo, 1) = 1"
        if categoria:
            sql += " AND categoria = ?"
            params.append(categoria)
        if setor:
            sql += " AND setor = ?"
            params.append(setor)
        sql += " ORDER BY categoria, nome"
        cur.execute(sql, params)
        rows = [_row_from_cursor(cur, r) for r in (cur.fetchall() or [])]
        local.close()
        if abaixo_minimo:
            rows = [
                r
                for r in rows
                if float(r.get("quantidade") or 0) <= float(r.get("estoque_min") or 0)
            ]
        return rows
    except Exception as e:
        log_error("carregar_almox_itens falhou", e)
        return []


def obter_almox_item(item_id: int) -> dict | None:
    try:
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        cur.execute("SELECT * FROM almox_itens WHERE id = ?", (item_id,))
        row = cur.fetchone()
        d = _row_from_cursor(cur, row) if row else None
        local.close()
        return d
    except Exception as e:
        log_error("obter_almox_item falhou", e)
        return None


def _upsert_almox_maleta_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM almox_maletas WHERE id = ?", (reg["id"],))
    existe = cur.fetchone() is not None
    vals = (
        reg.get("codigo") or "",
        reg.get("nome") or "",
        reg.get("setor") or "",
        reg.get("responsavel") or "",
        reg.get("observacao") or "",
        int(reg.get("ativo") if reg.get("ativo") is not None else 1),
        reg.get("data_cadastro") or datetime.now().isoformat(),
    )
    if existe:
        cur.execute(
            """
            UPDATE almox_maletas SET
                codigo=?, nome=?, setor=?, responsavel=?, observacao=?,
                ativo=?, data_cadastro=?
            WHERE id=?
            """,
            (*vals, reg["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO almox_maletas (
                id, codigo, nome, setor, responsavel, observacao, ativo, data_cadastro
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (reg["id"], *vals),
        )
    conn.commit()


def salvar_almox_maleta(reg: dict) -> bool:
    try:
        if not reg.get("id"):
            reg["id"] = proximo_id_almox_maleta()
        if not reg.get("data_cadastro"):
            reg["data_cadastro"] = datetime.now().isoformat()
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_almox_maleta_em(local, reg)
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_almox_maleta_em(cloud, reg)
                    cloud.close()
                    _cloud_breaker_record_success()
            except Exception as e_cloud:
                logger.warning("salvar_almox_maleta CLOUD | %s", str(e_cloud)[:120])
        return True
    except Exception as e:
        log_error("salvar_almox_maleta falhou", e)
        return False


def carregar_almox_maletas(apenas_ativos: bool = True) -> list[dict]:
    try:
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        if apenas_ativos:
            cur.execute("SELECT * FROM almox_maletas WHERE COALESCE(ativo, 1) = 1 ORDER BY nome")
        else:
            cur.execute("SELECT * FROM almox_maletas ORDER BY nome")
        rows = [_row_from_cursor(cur, r) for r in (cur.fetchall() or [])]
        local.close()
        return rows
    except Exception as e:
        log_error("carregar_almox_maletas falhou", e)
        return []


def carregar_itens_maleta(maleta_id: int) -> list[dict]:
    """Retorna itens da maleta com dados do catálogo (nome, categoria...)."""
    try:
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        cur.execute(
            """
            SELECT mi.id AS vinculo_id, mi.maleta_id, mi.item_id, mi.quantidade AS qtd_maleta,
                   i.codigo, i.nome, i.categoria, i.unidade, i.quantidade AS qtd_estoque
            FROM almox_maleta_itens mi
            LEFT JOIN almox_itens i ON i.id = mi.item_id
            WHERE mi.maleta_id = ?
            ORDER BY i.nome
            """,
            (maleta_id,),
        )
        rows = [_row_from_cursor(cur, r) for r in (cur.fetchall() or [])]
        local.close()
        return rows
    except Exception as e:
        log_error("carregar_itens_maleta falhou", e)
        return []


def _upsert_maleta_item_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM almox_maleta_itens WHERE id = ?", (reg["id"],))
    existe = cur.fetchone() is not None
    vals = (
        int(reg.get("maleta_id") or 0),
        int(reg.get("item_id") or 0),
        float(reg.get("quantidade") or 1),
    )
    if existe:
        cur.execute(
            """
            UPDATE almox_maleta_itens SET maleta_id=?, item_id=?, quantidade=?
            WHERE id=?
            """,
            (*vals, reg["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO almox_maleta_itens (id, maleta_id, item_id, quantidade)
            VALUES (?,?,?,?)
            """,
            (reg["id"], *vals),
        )
    conn.commit()


def adicionar_item_maleta(maleta_id: int, item_id: int, quantidade: float = 1) -> bool:
    try:
        # Se já existe vínculo, soma quantidade
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        cur.execute(
            "SELECT id, quantidade FROM almox_maleta_itens WHERE maleta_id=? AND item_id=?",
            (maleta_id, item_id),
        )
        row = cur.fetchone()
        if row:
            rid = row[0]
            qtd = float(row[1] or 0) + float(quantidade or 0)
            reg = {"id": rid, "maleta_id": maleta_id, "item_id": item_id, "quantidade": qtd}
        else:
            reg = {
                "id": proximo_id_almox_maleta_item(),
                "maleta_id": maleta_id,
                "item_id": item_id,
                "quantidade": float(quantidade or 1),
            }
        local.close()
        local = get_local_connection()
        _upsert_maleta_item_em(local, reg)
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_maleta_item_em(cloud, reg)
                    cloud.close()
            except Exception:
                pass
        return True
    except Exception as e:
        log_error("adicionar_item_maleta falhou", e)
        return False


def remover_item_maleta(vinculo_id: int) -> bool:
    try:
        sql = "DELETE FROM almox_maleta_itens WHERE id = ?"
        params = (vinculo_id,)
        local = get_local_connection()
        local.execute(sql, params)
        local.commit()
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    cloud.execute(sql, params)
                    cloud.commit()
                    cloud.close()
            except Exception:
                pass
        return True
    except Exception as e:
        log_error("remover_item_maleta falhou", e)
        return False


def _upsert_mov_em(conn, reg: dict) -> None:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM almox_movimentacoes WHERE id = ?", (reg["id"],))
    existe = cur.fetchone() is not None
    vals = (
        int(reg.get("item_id") or 0),
        reg.get("tipo") or "Ajuste",
        float(reg.get("quantidade") or 0),
        float(reg.get("saldo_apos") or 0) if reg.get("saldo_apos") is not None else None,
        reg.get("data") or datetime.now().isoformat(),
        reg.get("responsavel") or "",
        reg.get("motivo") or "",
        reg.get("chamado_id"),
        reg.get("maleta_id"),
        reg.get("observacao") or "",
    )
    if existe:
        cur.execute(
            """
            UPDATE almox_movimentacoes SET
                item_id=?, tipo=?, quantidade=?, saldo_apos=?, data=?,
                responsavel=?, motivo=?, chamado_id=?, maleta_id=?, observacao=?
            WHERE id=?
            """,
            (*vals, reg["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO almox_movimentacoes (
                id, item_id, tipo, quantidade, saldo_apos, data,
                responsavel, motivo, chamado_id, maleta_id, observacao
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (reg["id"], *vals),
        )
    conn.commit()


def registrar_movimentacao_almox(
    item_id: int,
    tipo: str,
    quantidade: float,
    responsavel: str = "",
    motivo: str = "",
    chamado_id: int | None = None,
    maleta_id: int | None = None,
    observacao: str = "",
) -> dict | None:
    """
    Registra movimentação e atualiza saldo do item.
    Tipos: Entrada (+), Saída (-), Baixa quebrado (-), Ajuste (define saldo absoluto via motivo),
           Transferência para maleta (- estoque + item maleta), Retorno da maleta (+).
    """
    try:
        item = obter_almox_item(int(item_id))
        if not item:
            return None
        qtd = abs(float(quantidade or 0))
        saldo_atual = float(item.get("quantidade") or 0)
        tipo_n = (tipo or "Ajuste").strip()

        if tipo_n in ("Entrada", "Retorno da maleta"):
            novo_saldo = saldo_atual + qtd
        elif tipo_n in ("Saída", "Baixa quebrado", "Transferência para maleta"):
            novo_saldo = max(0.0, saldo_atual - qtd)
        elif tipo_n == "Ajuste":
            # quantidade = novo saldo absoluto
            novo_saldo = float(quantidade or 0)
            qtd = abs(novo_saldo - saldo_atual)
        else:
            novo_saldo = saldo_atual

        item["quantidade"] = novo_saldo
        item["data_atualizacao"] = datetime.now().isoformat()
        if not salvar_almox_item(item):
            return None

        if tipo_n == "Transferência para maleta" and maleta_id:
            adicionar_item_maleta(int(maleta_id), int(item_id), qtd)

        mov = {
            "id": proximo_id_almox_mov(),
            "item_id": int(item_id),
            "tipo": tipo_n,
            "quantidade": qtd,
            "saldo_apos": novo_saldo,
            "data": datetime.now().isoformat(),
            "responsavel": responsavel or "",
            "motivo": motivo or "",
            "chamado_id": chamado_id,
            "maleta_id": maleta_id,
            "observacao": observacao or "",
        }
        local = get_local_connection()
        _ensure_schema(local)
        _upsert_mov_em(local, mov)
        local.close()
        if is_cloud() and not _cloud_breaker_is_open():
            try:
                cloud = get_cloud_connection()
                if cloud is not None:
                    _ensure_schema(cloud)
                    _upsert_mov_em(cloud, mov)
                    cloud.close()
            except Exception:
                pass
        return mov
    except Exception as e:
        log_error("registrar_movimentacao_almox falhou", e)
        return None


def carregar_movimentacoes_almox(
    item_id: int | None = None,
    limite: int = 200,
) -> list[dict]:
    try:
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        if item_id:
            cur.execute(
                """
                SELECT m.*, i.nome AS item_nome, i.codigo AS item_codigo
                FROM almox_movimentacoes m
                LEFT JOIN almox_itens i ON i.id = m.item_id
                WHERE m.item_id = ?
                ORDER BY m.data DESC, m.id DESC
                LIMIT ?
                """,
                (item_id, limite),
            )
        else:
            cur.execute(
                """
                SELECT m.*, i.nome AS item_nome, i.codigo AS item_codigo
                FROM almox_movimentacoes m
                LEFT JOIN almox_itens i ON i.id = m.item_id
                ORDER BY m.data DESC, m.id DESC
                LIMIT ?
                """,
                (limite,),
            )
        rows = [_row_from_cursor(cur, r) for r in (cur.fetchall() or [])]
        local.close()
        return rows
    except Exception as e:
        log_error("carregar_movimentacoes_almox falhou", e)
        return []


def resumo_almox() -> dict:
    """KPIs rápidos do almoxarifado."""
    itens = carregar_almox_itens(apenas_ativos=True)
    maletas = carregar_almox_maletas(apenas_ativos=True)
    abaixo = [
        i for i in itens if float(i.get("quantidade") or 0) <= float(i.get("estoque_min") or 0)
    ]
    por_cat: dict[str, int] = {}
    for i in itens:
        c = i.get("categoria") or "Outro"
        por_cat[c] = por_cat.get(c, 0) + 1
    return {
        "total_itens": len(itens),
        "abaixo_minimo": len(abaixo),
        "total_maletas": len(maletas),
        "por_categoria": por_cat,
        "itens_criticos": abaixo[:20],
    }


def _mov_ja_lancada_compra(compra_id: int) -> bool:
    """Evita lançar duas vezes a mesma compra no estoque."""
    try:
        tag = f"[compra#{int(compra_id)}]"
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        cur.execute(
            "SELECT 1 FROM almox_movimentacoes WHERE motivo LIKE ? LIMIT 1",
            (f"%{tag}%",),
        )
        ok = cur.fetchone() is not None
        local.close()
        return ok
    except Exception:
        return False


def buscar_almox_item_por_nome(nome: str) -> dict | None:
    """Busca item ativo pelo nome (case-insensitive, exact match trim)."""
    nome_n = (nome or "").strip().lower()
    if not nome_n:
        return None
    for it in carregar_almox_itens(apenas_ativos=True):
        if str(it.get("nome") or "").strip().lower() == nome_n:
            return it
    return None


def entrada_estoque_de_compra(compra: dict, quantidade: float | None = None) -> dict | None:
    """
    Quando uma compra é marcada como Recebida:
    - localiza item no almox pelo nome (ou cria)
    - soma quantidade ao estoque
    - registra movimentação tipo Entrada (idempotente por compra_id)
    Retorna o item atualizado ou None.
    """
    try:
        if not compra or not compra.get("id"):
            return None
        if str(compra.get("status") or "").strip() != "Recebida":
            return None
        cid = int(compra["id"])
        if _mov_ja_lancada_compra(cid):
            logger.info("entrada_estoque_de_compra já lançada | compra#%s", cid)
            return buscar_almox_item_por_nome(str(compra.get("item_nome") or ""))

        nome = (compra.get("item_nome") or "").strip()
        if not nome:
            return None

        # Quantidade: parâmetro > campo no reg > 1
        qtd = quantidade
        if qtd is None:
            for k in ("quantidade_recebida", "quantidade", "qtd"):
                if compra.get(k) is not None and str(compra.get(k)).strip() != "":
                    try:
                        qtd = float(compra.get(k))
                        break
                    except (TypeError, ValueError):
                        pass
        if qtd is None or qtd <= 0:
            qtd = 1.0

        item = buscar_almox_item_por_nome(nome)
        if not item:
            item = {
                "id": proximo_id_almox_item(),
                "codigo": f"CP{cid}",
                "nome": nome,
                "categoria": "Peça / Componente",
                "subcategoria": "",
                "unidade": "UN",
                "quantidade": 0,
                "estoque_min": 1,
                "localizacao": "",
                "setor": "",
                "equipamento_ref": (compra.get("equipamento") or "").strip(),
                "especificacao": (compra.get("observacao") or "").strip(),
                "observacao": f"Criado automaticamente pela compra #{cid}",
                "ativo": 1,
            }
            if not salvar_almox_item(item):
                return None

        tag = f"[compra#{cid}]"
        motivo = f"{tag} Recebimento compra #{cid}" + (
            f" · OS {compra.get('chamado_id')}" if compra.get("chamado_id") else ""
        )
        mov = registrar_movimentacao_almox(
            item_id=int(item["id"]),
            tipo="Entrada",
            quantidade=float(qtd),
            responsavel=(compra.get("comprador") or "Compras").strip(),
            motivo=motivo,
            chamado_id=int(compra["chamado_id"]) if compra.get("chamado_id") else None,
            observacao=(compra.get("observacao_compras") or compra.get("observacao") or "")[:200],
        )
        if not mov:
            return None
        logger.info(
            "entrada_estoque_de_compra OK | compra#%s item=%s +%s saldo=%s",
            cid,
            nome,
            qtd,
            mov.get("saldo_apos"),
        )
        return obter_almox_item(int(item["id"]))
    except Exception as e:
        log_error("entrada_estoque_de_compra falhou", e)
        return None


def parse_datetime_safe(value, default: datetime | None = None) -> datetime:
    """
    Converte string / Timestamp / NaN / None em datetime de forma segura.
    Evita ValueError: cannot convert float NaN to integer.
    """
    if default is None:
        default = datetime.now()
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        # Garante timezone-naive para cálculos simples
        if getattr(value, "tzinfo", None) is not None:
            try:
                return value.replace(tzinfo=None)
            except Exception:
                return default
        return value
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except Exception:
            pass
    try:
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return default
        dt = ts.to_pydatetime()
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return default


def comprimir_imagem(image_bytes, prefixo="chamado", max_size=900, quality=82):
    try:
        img = Image.open(image_bytes)
        img = ImageOps.exif_transpose(img)
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        output_path = f"fotos_chamados/{prefixo}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        img.save(output_path, "JPEG", quality=quality, optimize=True)
        return output_path
    except Exception as e:
        log_error("comprimir_imagem falhou", e)
        st.error(f"Erro ao comprimir imagem: {e}")
        return None


def reload_data():
    st.session_state.chamados = carregar_dados()
    st.session_state.equipe = carregar_equipe()
    st.session_state.setores = carregar_setores()
    st.session_state.equipamentos = carregar_equipamentos()


# ====================== AUTH ADMIN (via secrets) ======================
def verificar_login_admin(usuario: str, senha: str) -> bool:
    """
    Usa secrets.toml:
      [admin]
      username = "Leandro Coelho"
      password_hash = "sha256..."
    Fallback: usuário/senha legados se secrets não existirem.
    """
    try:
        admin = st.secrets.get("admin", {})
        expected_user = admin.get("username", "Leandro Coelho")
        expected_hash = admin.get("password_hash")
        if expected_hash:
            dig = hashlib.sha256(senha.encode("utf-8")).hexdigest()
            return usuario.strip() == expected_user and dig == expected_hash
    except Exception:
        pass
    # Fallback legado
    return usuario.strip() == "Leandro Coelho" and senha == "123"


def carregar_integracoes_log(
    limite: int = 200,
    canal: str | None = None,
    apenas_erro: bool = False,
    chamado_id: int | None = None,
) -> list[dict]:
    """
    Retorna logs da tabela integracoes_log (WhatsApp, Drive, webhooks).
    Ordenado do mais recente para o mais antigo.
    """
    try:
        local = get_local_connection()
        _ensure_schema(local)
        cur = local.cursor()
        sql = (
            "SELECT id, data_hora, canal, destino, chamado_id, ok, detalhe "
            "FROM integracoes_log WHERE 1=1"
        )
        params: list = []
        if canal:
            sql += " AND canal = ?"
            params.append(canal)
        if apenas_erro:
            sql += " AND (ok = 0 OR ok IS NULL)"
        if chamado_id is not None:
            sql += " AND chamado_id = ?"
            params.append(int(chamado_id))
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limite))
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        local.close()
        return [_row_to_dict(r, cols) for r in rows] if rows else []
    except Exception as e:
        log_error("carregar_integracoes_log", e)
        return []
