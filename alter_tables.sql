USE stock_screener;

SET @has_board := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'stock_basic'
      AND COLUMN_NAME = 'board'
);
SET @sql := IF(
    @has_board = 0,
    'ALTER TABLE stock_basic ADD COLUMN board VARCHAR(30) NULL COMMENT ''股票板块：main_board/gem/star/bse/unknown'' AFTER market',
    'SELECT ''stock_basic.board already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_idx_board := (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'stock_basic'
      AND INDEX_NAME = 'idx_board'
);
SET @sql := IF(
    @has_idx_board = 0,
    'CREATE INDEX idx_board ON stock_basic (board)',
    'SELECT ''stock_basic.idx_board already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS stock_financial (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL,
    report_date DATE NOT NULL COMMENT '报告期日期',

    roe DECIMAL(12, 4) COMMENT 'ROE，净资产收益率',
    revenue_growth DECIMAL(12, 4) COMMENT '营收增长率',
    profit_growth DECIMAL(12, 4) COMMENT '净利润增长率',
    dividend_yield DECIMAL(12, 4) COMMENT '股息率',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_stock_report (stock_id, report_date),
    INDEX idx_report_date (report_date),
    INDEX idx_roe (roe),
    INDEX idx_profit_growth (profit_growth),
    INDEX idx_dividend_yield (dividend_yield),

    CONSTRAINT fk_financial_stock
        FOREIGN KEY (stock_id)
        REFERENCES stock_basic(id)
) COMMENT='股票财务指标表';
