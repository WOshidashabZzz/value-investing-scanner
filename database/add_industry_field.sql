-- 为 stock_basic 表添加 sector（一级板块）字段
ALTER TABLE stock_basic
ADD COLUMN sector VARCHAR(20) DEFAULT NULL COMMENT '一级板块：金融/消费/医药/科技/制造/周期/地产基建/公用环保'
AFTER market;

-- 添加索引以加速板块过滤查询
ALTER TABLE stock_basic
ADD INDEX idx_sector (sector);
