-- Docker 首次启动时自动执行：创建只读用户
CREATE USER IF NOT EXISTS 'readonly'@'%' IDENTIFIED BY 'readonly_pass';
GRANT SELECT ON `olist_ecommerce`.* TO 'readonly'@'%';
FLUSH PRIVILEGES;
