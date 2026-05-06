CREATE DATABASE IF NOT EXISTS stock_screener
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;

USE stock_screener;

CREATE TABLE IF NOT EXISTS stock_basic (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bs_code VARCHAR(20) NOT NULL COMMENT 'Baostock股票代码，例如sh.600519',
    symbol VARCHAR(20) NOT NULL COMMENT '股票代码，例如600519',
    name VARCHAR(100) COMMENT '股票名称',
    market VARCHAR(20) COMMENT '市场，例如sh或sz',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_bs_code (bs_code),
    INDEX idx_symbol (symbol)
) COMMENT='股票基础信息表';

CREATE TABLE IF NOT EXISTS stock_valuation (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL,
    trade_date DATE NOT NULL,

    close_price DECIMAL(12, 4) COMMENT '收盘价',
    pe_ttm DECIMAL(12, 4) COMMENT 'TTM市盈率',
    pb DECIMAL(12, 4) COMMENT '市净率',
    ps_ttm DECIMAL(12, 4) COMMENT 'TTM市销率',
    pcf_ncf_ttm DECIMAL(12, 4) COMMENT '市现率',

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_stock_date (stock_id, trade_date),
    INDEX idx_trade_date (trade_date),
    INDEX idx_pe_ttm (pe_ttm),
    INDEX idx_pb (pb),

    CONSTRAINT fk_valuation_stock
        FOREIGN KEY (stock_id)
        REFERENCES stock_basic(id)
) COMMENT='股票每日估值表';

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
