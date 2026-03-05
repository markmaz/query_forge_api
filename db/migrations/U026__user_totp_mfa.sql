-- U026__user_totp_mfa.sql
-- Roll back TOTP MFA columns from users.

ALTER TABLE `users`
  DROP COLUMN `otp_mfa_method`,
  DROP COLUMN `otp_totp_confirmed_at`,
  DROP COLUMN `otp_totp_enabled`,
  DROP COLUMN `otp_totp_secret`;
