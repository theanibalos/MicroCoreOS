-- depends: users/001_create_users.sql
ALTER TABLE users ADD COLUMN roles TEXT NOT NULL DEFAULT '["user"]';
