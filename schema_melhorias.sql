-- ============================================================
-- Gestão de Chamados — scripts de banco (SQLite / SQLite Cloud)
-- Idempotentes: podem rodar mais de uma vez.
-- ============================================================

-- Índices para telas e relatórios (status, SLA, equipamento, técnico)
CREATE INDEX IF NOT EXISTS idx_chamados_status
    ON chamados (status);
CREATE INDEX IF NOT EXISTS idx_chamados_abertura
    ON chamados (data_hora_abertura);
CREATE INDEX IF NOT EXISTS idx_chamados_equipamento
    ON chamados (equipamento);
CREATE INDEX IF NOT EXISTS idx_chamados_executante
    ON chamados (executante);
CREATE INDEX IF NOT EXISTS idx_chamados_setor
    ON chamados (setor);
CREATE INDEX IF NOT EXISTS idx_chamados_prioridade
    ON chamados (prioridade);

CREATE INDEX IF NOT EXISTS idx_equip_proxima
    ON equipamentos (proxima_preventiva);
CREATE INDEX IF NOT EXISTS idx_equip_setor
    ON equipamentos (setor);

CREATE INDEX IF NOT EXISTS idx_hist_equip
    ON manutencoes_historico (equipamento_id);
CREATE INDEX IF NOT EXISTS idx_hist_data
    ON manutencoes_historico (data_manutencao);
CREATE INDEX IF NOT EXISTS idx_hist_chamado
    ON manutencoes_historico (chamado_id);

CREATE INDEX IF NOT EXISTS idx_compras_status
    ON compras_pecas (status);
CREATE INDEX IF NOT EXISTS idx_compras_chamado
    ON compras_pecas (chamado_id);

CREATE INDEX IF NOT EXISTS idx_almox_nome
    ON almox_itens (nome);
CREATE INDEX IF NOT EXISTS idx_mov_item
    ON almox_movimentacoes (item_id);

-- Histórico de eventos do chamado (abertura, peça, conclusão…)
CREATE TABLE IF NOT EXISTS chamado_eventos (
    id INTEGER PRIMARY KEY,
    chamado_id INTEGER NOT NULL,
    data_hora TEXT,
    tipo TEXT,
    usuario TEXT,
    detalhe TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_chamado
    ON chamado_eventos (chamado_id);

-- Várias fotos por OS (abertura / solução / extra)
CREATE TABLE IF NOT EXISTS chamado_fotos (
    id INTEGER PRIMARY KEY,
    chamado_id INTEGER,
    tipo TEXT,
    path_local TEXT,
    url_remota TEXT,
    destino TEXT,
    data_envio TEXT
);
CREATE INDEX IF NOT EXISTS idx_fotos_chamado
    ON chamado_fotos (chamado_id);

-- Log das integrações (WhatsApp / Drive / webhook)
CREATE TABLE IF NOT EXISTS integracoes_log (
    id INTEGER PRIMARY KEY,
    data_hora TEXT,
    canal TEXT,
    destino TEXT,
    chamado_id INTEGER,
    ok INTEGER,
    detalhe TEXT
);
