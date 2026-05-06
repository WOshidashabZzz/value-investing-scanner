USE stock_screener;

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
