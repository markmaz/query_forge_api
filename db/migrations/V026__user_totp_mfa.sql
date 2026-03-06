-- V026__user_totp_mfa.sql
-- Add TOTP MFA columns to users.

ALTER TABLE `users`
  ADD COLUMN `otp_totp_secret` VARCHAR(128) NULL AFTER `otp_secret`,
  ADD COLUMN `otp_totp_enabled` TINYINT(1) NOT NULL DEFAULT 0 AFTER `otp_totp_secret`,
  ADD COLUMN `otp_totp_confirmed_at` DATETIME NULL AFTER `otp_totp_enabled`,
  ADD COLUMN `otp_mfa_method` VARCHAR(20) NULL AFTER `otp_totp_confirmed_at`;
