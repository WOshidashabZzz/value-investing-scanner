-- ============================================
-- 股票数据安全双版本更新策略 - 数据库迁移
-- 2026-05-07
-- ============================================

-- 1. stock_valuation 增加 data_version 字段
--    latest:  当前在线使用的稳定数据（默认）
--    backup:  上一次成功更新的数据（回滚用）
--    staging: 正在写入中的临时数据（不可读）
ALTER TABLE stock_valuation
    ADD COLUMN data_version VARCHAR(16) NOT NULL DEFAULT 'latest'
    COMMENT '数据版本: latest=当前使用, backup=上一次有效数据, staging=写入中临时数据',
    ADD INDEX idx_data_version (data_version),
    ADD INDEX idx_version_trade_date (data_version, trade_date);

-- 2. 新增 update_log 表，记录每次更新操作的状态
CREATE TABLE IF NOT EXISTS update_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    update_type VARCHAR(32) NOT NULL COMMENT '更新类型: valuation/financial/full',
    status VARCHAR(16) NOT NULL COMMENT '运行状态: running/success/failed',
    staging_trade_date DATE COMMENT '本次 staging 的交易日',
    stock_count INT COMMENT 'staging 股票数量',
    validation_errors TEXT COMMENT '校验错误信息',
    error_message TEXT COMMENT '异常错误信息',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    INDEX idx_status (status),
    INDEX idx_started_at (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据更新操作日志';

-- 说明：
-- - 只有 stock_valuation 做版本管理，因为它每次写入新的 trade_date 行
-- - stock_financial 用 ON DUPLICATE KEY UPDATE COALESCE 安全覆盖，不做版本管理
-- - stock_basic 用 ON DUPLICATE KEY UPDATE 更新基础信息，不做版本管理
