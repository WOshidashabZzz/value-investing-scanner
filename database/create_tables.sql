-- 创建数据库表的 SQL 语句

CREATE TABLE IF NOT EXISTS stock_basic (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL COMMENT '股票代码',
    name VARCHAR(100) NOT NULL COMMENT '股票名称',
    board VARCHAR(20) COMMENT '板块',
    market VARCHAR(10) COMMENT '市场',
    ipo_date DATE COMMENT '上市日期',
    status TINYINT DEFAULT 1 COMMENT '状态 1-正常 0-退市',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='股票基本信息表';

CREATE TABLE IF NOT EXISTS stock_valuation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL COMMENT '关联 stock_basic.id',
    trade_date DATE NOT NULL COMMENT '交易日',
    pe_ttm DECIMAL(10,4) COMMENT '滚动市盈率',
    pb DECIMAL(10,4) COMMENT '市净率',
    ps_ttm DECIMAL(10,4) COMMENT '滚动市销率',
    pcf_ttm DECIMAL(10,4) COMMENT '滚动市现率',
    market_cap DECIMAL(20,2) COMMENT '总市值',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_stock_date (stock_id, trade_date),
    FOREIGN KEY (stock_id) REFERENCES stock_basic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='估值数据表';

CREATE TABLE IF NOT EXISTS stock_financial (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_id INT NOT NULL COMMENT '关联 stock_basic.id',
    report_date DATE NOT NULL COMMENT '报告期',
    roe DECIMAL(10,4) COMMENT '净资产收益率',
    revenue_growth DECIMAL(10,4) COMMENT '营收增长率',
    profit_growth DECIMAL(10,4) COMMENT '利润增长率',
    gross_margin DECIMAL(10,4) COMMENT '毛利率',
    net_margin DECIMAL(10,4) COMMENT '净利率',
    eps DECIMAL(10,4) COMMENT '每股收益',
    bvps DECIMAL(10,4) COMMENT '每股净资产',
    dividend_yield DECIMAL(10,4) COMMENT '股息率',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_stock_report (stock_id, report_date),
    FOREIGN KEY (stock_id) REFERENCES stock_basic(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='财务数据表';
